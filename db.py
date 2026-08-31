"""跨 session 持久化（Supabase Postgres）——回饋＋歷史＋同意。見 FEEDBACK_PERSISTENCE.md。

分層原則（為了可單元測試、且 Supabase 沒設好時 import 本模組也不會炸）：
  - **純邏輯**（user_key 雜湊、key_str、params 組裝、row→entry 映射）不碰網路/DB，直接 pytest。
  - **DB 函式**都收一個 psycopg 風格的 `conn`（可注入假物件測試）；真正的連線由
    `connection()` 從 `get_pool()` 的連線池借出，**psycopg / psycopg_pool 都是延遲載入**
    ——本模組頂層不 import 它們，所以雲端還沒裝也能 import 本模組。
    ⚠️ 每次操作都要走 `with connection() as conn:`，**不要把連線抓出來長期共用**：
    交易邊界是連線層級的，共用會讓不同使用者的交易互相污染（見「連線池」段的驗證數據）。
  - 設定（連線字串、HMAC 祕密）從 env 讀，缺了才退而問 `st.secrets`（延遲 import streamlit）。

呼叫端（app.py，Phase 2）務必把每個 DB 函式包在 try/except 裡：**DB 壞掉一律降級成 session 級，
絕不讓生成失敗**（比照 spotify_api.append_to_persistent_history 的態度）。

依賴：`psycopg[binary]==<版本>` ＋ `psycopg-pool==<版本>`（照 == 釘版紀律；⚠️ pool 是**獨立套件**，
`psycopg[binary]` 裡沒有）。Streamlit Secrets 要設 `SUPABASE_DB_URL`（Supabase 的
**pooler / Transaction mode** 連線字串，serverless 別用直連 5432）與 `PERSIST_HMAC_SECRET`。
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import threading
from contextlib import contextmanager
from datetime import datetime, timezone

from recommend import _track_key_from  # 曲目正規化的單一真相來源

CONSENT_VERSION = 1     # 隱私條款版本；改條款就 bump，觸發使用者重新同意
HISTORY_KEEP = 500      # 每位使用者歷史保留上限（比照 recommend.PERSISTENT_HISTORY_MAX）

_FB_COLS = "user_key, track_key, title, artist, state, fame, is_discovery, reason, ctx, updated_at"
_HIST_COLS = "user_key, track_key, title, artist, recommended_at"


# ── 純邏輯（不碰網路/DB，直接可測）───────────────────────────
def user_key(spotify_user_id: str, secret: str) -> str:
    """Spotify user id → 以站方祕密 HMAC-SHA256 的**不可逆假名鍵**。

    DB 只存這個，永不存原始 id：就算 DB 外洩也不直接對到「這是誰的 Spotify」。
    """
    return hmac.new(
        (secret or "").encode(), (spotify_user_id or "").encode(), hashlib.sha256
    ).hexdigest()


def guest_user_key(local_id: str, secret: str) -> str:
    """訪客的**每瀏覽器**假名鍵＝ HMAC(secret, "guest:"+localStorage UUID)。見 FEEDBACK_PERSISTENCE.md「Phase 5」。

    - 加 `guest:` 前綴命名空間，保證與登入的 user_key（HMAC(spotify_id)）**不可能相撞**。
    - 只到「瀏覽器」層級、不跨裝置；DB 只存這個雜湊，原始 UUID 只活在瀏覽器 localStorage。
    - ⚠️ 呼叫端拿不到 local_id（無痕/尚未回傳）時**不要**用固定字串補（那會把所有這類訪客算成同一人、
      互相污染），一律降級成 session 級——這裡對空字串仍會回一個穩定雜湊，判斷「有沒有 id」是呼叫端的責任。
    """
    return user_key("guest:" + (local_id or ""), secret)


def key_str(title: str, artist: str) -> str:
    """曲目在 DB 的主鍵字串＝ recommend 正規化後的 (歌名, 主藝人)，以 US(\\x1f) 分隔。

    用 recommend._track_key_from 當唯一真相來源——跟 session 端的去重/回饋用同一把鑰匙，
    才不會「存進去的 key」和「比對用的 key」對不上。
    """
    nt, na = _track_key_from(title, artist)
    return f"{nt}\x1f{na}"


def _now(now: datetime | None = None) -> datetime:
    """時間戳一律 UTC aware（DB 用 timestamptz）。可注入 now 供測試固定。"""
    return now or datetime.now(timezone.utc)


def feedback_params(
    uk: str, title: str, artist: str, state: str, *,
    fame=None, is_discovery=None, reason=None, ctx=None, now=None,
) -> tuple:
    """組出 feedback upsert 的參數（順序對齊 _FB_COLS）。ctx 存 JSON 字串（欄位是 jsonb）。"""
    return (
        uk, key_str(title, artist), title, artist, state,
        fame, is_discovery, reason, json.dumps(ctx or {}, ensure_ascii=False), _now(now),
    )


def row_to_feedback_entry(row) -> dict:
    """一列 feedback（照 _FB_COLS 順序）→ 乾淨的 entry；ctx 還原成 dict（psycopg3 可能已解成 dict）。"""
    ctx = row[8]
    if not isinstance(ctx, dict):
        ctx = json.loads(ctx or "{}")
    return {
        "track_key": row[1], "title": row[2], "artist": row[3], "state": row[4],
        "fame": row[5], "is_discovery": row[6], "reason": row[7], "ctx": ctx,
    }


def history_params(uk: str, title: str, artist: str, now=None) -> tuple:
    return (uk, key_str(title, artist), title, artist, _now(now))


def row_to_history_entry(row) -> dict:
    """一列 history → session 歷史用的 {title, artist}。"""
    return {"title": row[2], "artist": row[3]}


# ── DB 函式（收 conn，可注入假物件測試）─────────────────────
def upsert_feedback(conn, uk, title, artist, state, **kw) -> None:
    """新增/更新一筆回饋（單選：同一 track_key 覆蓋 state 與情境快照）。"""
    with conn.cursor() as cur:
        cur.execute(
            f"insert into feedback ({_FB_COLS}) "
            "values (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s) "
            "on conflict (user_key, track_key) do update set "
            "state = excluded.state, fame = excluded.fame, "
            "is_discovery = excluded.is_discovery, reason = excluded.reason, "
            "ctx = excluded.ctx, updated_at = excluded.updated_at",
            feedback_params(uk, title, artist, state, **kw),
        )
    conn.commit()


def delete_feedback(conn, uk, title, artist) -> None:
    """取消回饋（使用者再點一次同一顆 pill）。"""
    with conn.cursor() as cur:
        cur.execute(
            "delete from feedback where user_key = %s and track_key = %s",
            (uk, key_str(title, artist)),
        )
    conn.commit()


def load_feedback(conn, uk) -> list[dict]:
    """讀回這位使用者的全部回饋（登入時重建 session 用）。"""
    with conn.cursor() as cur:
        cur.execute(f"select {_FB_COLS} from feedback where user_key = %s", (uk,))
        rows = cur.fetchall()
    return [row_to_feedback_entry(r) for r in rows]


def upsert_history(conn, uk, tracks, now=None) -> None:
    """把這批推薦寫進歷史（同曲只更新時間，取代靠歌單名字找回的舊機制）。

    tracks: [{"title":..., "artist":...}, ...]
    """
    with conn.cursor() as cur:
        for t in tracks:
            cur.execute(
                f"insert into history ({_HIST_COLS}) values (%s, %s, %s, %s, %s) "
                "on conflict (user_key, track_key) do update set "
                "recommended_at = excluded.recommended_at",
                history_params(uk, t.get("title", ""), t.get("artist", ""), now),
            )
    conn.commit()


def load_history(conn, uk, limit=HISTORY_KEEP) -> list[dict]:
    """讀回最新 limit 筆歷史，回傳**舊→新**（跟 session 歷史的順序一致）。"""
    with conn.cursor() as cur:
        cur.execute(
            f"select {_HIST_COLS} from history where user_key = %s "
            "order by recommended_at desc limit %s",
            (uk, limit),
        )
        rows = cur.fetchall()
    return [row_to_history_entry(r) for r in reversed(rows)]


def trim_history(conn, uk, keep=HISTORY_KEEP) -> None:
    """只保留最新 keep 筆，其餘刪除（避免無限成長）。"""
    with conn.cursor() as cur:
        cur.execute(
            "delete from history where user_key = %s and track_key not in "
            "(select track_key from history where user_key = %s "
            "order by recommended_at desc limit %s)",
            (uk, uk, keep),
        )
    conn.commit()


_PLAYLIST_FB_COLS = "user_key, gen_id, rating, saved, copied, num_songs, ctx, created_at, updated_at"


def upsert_playlist_feedback(conn, uk, gen_id, *, rating=None, saved=False, copied=False,
                             num_songs=None, ctx=None, now=None) -> None:
    """歌單層級訊號（每次生成一列，gen_id 為鍵）。文獻依據見 FEEDBACK_PERSISTENCE.md：
    拿到歌單當下使用者答得出的是「整份合不合味」與「想不想收」，不是逐首「喜不喜歡」。

    - `rating` 3 段滿意度（1=不太合 / 2=還不錯 / 3=超合），看一眼就能答、不需聆聽。
    - `saved`/`copied` 行為訊號（點了加入/複製）——比嘴巴說的更可信，且二元無極端值問題。
    多次呼叫累積：rating 用 coalesce 保留已填的、saved/copied 用 OR 累加（同一份歌單先評分再收藏）。
    """
    ts = _now(now)
    with conn.cursor() as cur:
        cur.execute(
            f"insert into playlist_feedback ({_PLAYLIST_FB_COLS}) "
            "values (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s) "
            "on conflict (user_key, gen_id) do update set "
            "rating = coalesce(excluded.rating, playlist_feedback.rating), "
            "saved  = playlist_feedback.saved  or excluded.saved, "
            "copied = playlist_feedback.copied or excluded.copied, "
            "updated_at = excluded.updated_at",
            (uk, gen_id, rating, saved, copied, num_songs,
             json.dumps(ctx or {}, ensure_ascii=False), ts, ts),
        )
    conn.commit()


def has_consent(conn, uk, version=CONSENT_VERSION) -> bool:
    """這位使用者是否已同意（且同意的版本 >= 目前條款版本）。未同意前一律不讀不寫其他表。"""
    with conn.cursor() as cur:
        cur.execute("select consent_version from consent where user_key = %s", (uk,))
        row = cur.fetchone()
    return bool(row) and row[0] >= version


def set_consent(conn, uk, version=CONSENT_VERSION, now=None) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "insert into consent (user_key, consented_at, consent_version) values (%s, %s, %s) "
            "on conflict (user_key) do update set "
            "consented_at = excluded.consented_at, consent_version = excluded.consent_version",
            (uk, _now(now), version),
        )
    conn.commit()


def delete_all(conn, uk) -> None:
    """『刪除我在本站的所有資料』：清掉三張表裡這位使用者的列。"""
    with conn.cursor() as cur:
        for tbl in ("feedback", "history", "playlist_feedback", "consent"):
            cur.execute(f"delete from {tbl} where user_key = %s", (uk,))
    conn.commit()


# ── 設定與連線（延遲載入，Supabase 沒設好也能 import 本模組）───
def _config() -> tuple[str | None, str | None]:
    """回 (連線字串, HMAC 祕密)。優先 env（本機 .env），缺了才問 st.secrets（雲端）。"""
    url = os.getenv("SUPABASE_DB_URL")
    secret = os.getenv("PERSIST_HMAC_SECRET")
    if not (url and secret):
        try:
            import streamlit as st  # 延遲：只有 env 缺值時才付這個 import 成本
            url = url or st.secrets.get("SUPABASE_DB_URL")
            secret = secret or st.secrets.get("PERSIST_HMAC_SECRET")
        except Exception:
            pass
    return url, secret


def hmac_secret() -> str | None:
    return _config()[1]


def is_enabled() -> bool:
    """兩個祕密都在＝持久化可用。app.py 據此決定走 DB 還是純 session。"""
    url, secret = _config()
    return bool(url and secret)


# ── 連線池 ──────────────────────────────────────────────
# ⚠️ 舊版是「一條 module-global 連線、全站共用」。psycopg3 的連線本身有內部鎖不會 crash，
# 但**交易邊界是連線層級的**，而 Streamlit 每位使用者的 session 是同一行程裡的不同執行緒：
#   · A 的 commit() 會順手提交 B 還沒寫完的語句；
#   · B 的語句一報錯讓交易進入 aborted 狀態，A 的寫入也會跟著失敗。
# ＝跨使用者的完整性耦合。更麻煩的是 reset_conn() 那個「死連線自癒」補丁會讓症狀看起來像
# 「偶發、重試就好」，很難從症狀追回根因。
# 連線池讓每個 with 區塊拿到自己的連線＝自己的交易，彼此不再互相影響。
POOL_MAX = 5           # Supabase 免費方案的 pooler 連線數有限，Streamlit Cloud 單行程也用不到更多
POOL_TIMEOUT = 3.0     # 借不到就放棄：DB 掛掉時要快速降級成 session 級，不能把頁面卡住
POOL_MAX_IDLE = 120.0  # 閒置超過就自己收掉（pooler 本來也會關，讓池子先手比較乾淨）

_pool = None
_POOL_LOCK = threading.Lock()


def get_pool():
    """快取的連線池；`SUPABASE_DB_URL` 沒設回 None（呼叫端據此降級成 session 級）。

    ⚠️ psycopg_pool 在此才 import（同 psycopg，雲端沒裝也要能 import 本模組）。
    ⚠️ 連線字串務必用 Supabase 的 pooler / Transaction mode。

    `min_size=0` ＝ 不預先開連線，所以 DB 沒設好或冷啟動時完全零成本。
    `check` 會在借出前驗一次連線——被 pooler 關掉的閒置連線由池子自動汰換，
    **這正是舊版 reset_conn() 想手動做的事**，而且不會把其他好的連線一起丟掉。
    """
    global _pool
    if _pool is not None:
        return _pool
    url, _ = _config()
    if not url:
        return None
    with _POOL_LOCK:
        if _pool is not None:          # double-check：兩條執行緒同時進來只能建出一個池
            return _pool
        from psycopg_pool import ConnectionPool   # 延遲載入
        _pool = ConnectionPool(
            url,
            min_size=0,
            max_size=POOL_MAX,
            timeout=POOL_TIMEOUT,
            max_idle=POOL_MAX_IDLE,
            check=ConnectionPool.check_connection,
            open=True,                 # 3.2+ 不明寫會有 deprecation warning
        )
    return _pool


@contextmanager
def connection():
    """借一條連線來用，離開區塊自動歸還（正常結束 commit、有例外 rollback）。

    DB 未啟用時 yield None，呼叫端據此降級成 session 級：

        with db.connection() as conn:
            if conn is None:
                return
            db.upsert_feedback(conn, uk, ...)

    ⚠️ 區塊內請維持現有 db.* 函式「自己 commit」的寫法（它們本來就有）——離開區塊時的
    commit 只是保險。區塊內提早 return 會被當成例外路徑而 rollback，但那時該寫的已經 commit 了。
    """
    pool = get_pool()
    if pool is None:
        yield None
        return
    with pool.connection() as conn:
        yield conn


def close_pool() -> None:
    """關閉並丟棄連線池。

    ⚠️ 正式流程**不需要**呼叫這個：死連線由 `check` 自動汰換，而在這裡整池關掉
    等於把其他使用者正在用的好連線一起丟掉——那正是舊版單一連線的失敗模式。
    存在的理由是測試與行程收尾。
    """
    global _pool
    try:
        if _pool is not None:
            _pool.close()
    except Exception:
        pass
    _pool = None
