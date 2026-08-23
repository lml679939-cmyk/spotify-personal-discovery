"""跨 session 持久化（Supabase Postgres）——回饋＋歷史＋同意。見 FEEDBACK_PERSISTENCE.md。

分層原則（為了可單元測試、且 Supabase 沒設好時 import 本模組也不會炸）：
  - **純邏輯**（user_key 雜湊、key_str、params 組裝、row→entry 映射）不碰網路/DB，直接 pytest。
  - **DB 函式**都收一個 psycopg 風格的 `conn`（可注入假物件測試）；真正的連線在 `get_conn()`
    **延遲載入 psycopg**——本模組頂層不 import psycopg，所以雲端還沒裝 psycopg 也能 import。
  - 設定（連線字串、HMAC 祕密）從 env 讀，缺了才退而問 `st.secrets`（延遲 import streamlit）。

呼叫端（app.py，Phase 2）務必把每個 DB 函式包在 try/except 裡：**DB 壞掉一律降級成 session 級，
絕不讓生成失敗**（比照 spotify_api.append_to_persistent_history 的態度）。

⚠️ Phase 2 接上 app.py 之前，要把 `psycopg[binary]==<版本>` 加進 requirements.txt（照 == 釘版紀律），
並在 Streamlit Secrets 設 `SUPABASE_DB_URL`（Supabase 的 **pooler / Transaction mode** 連線字串，
serverless 別用直連 5432）與 `PERSIST_HMAC_SECRET`。
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
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
        for tbl in ("feedback", "history", "consent"):
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


_conn = None


def get_conn():
    """快取的 psycopg 連線；`SUPABASE_DB_URL` 沒設回 None（呼叫端據此降級成 session 級）。

    ⚠️ psycopg 在此才 import。⚠️ 連線務必用 Supabase 的 pooler 字串（見檔頭）；Streamlit 多執行緒
    重跑下若出現連線衝突，Phase 2 再換成 psycopg_pool 連線池。
    """
    global _conn
    if _conn is not None:
        return _conn
    url, _ = _config()
    if not url:
        return None
    import psycopg  # 延遲載入
    _conn = psycopg.connect(url)
    return _conn
