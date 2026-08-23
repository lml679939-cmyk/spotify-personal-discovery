"""db.py 的純邏輯＋mock 測試（不需 psycopg、不需 Supabase）。

DB 函式收一個 psycopg 風格的假 conn（記錄 execute、供 canned fetch），驗的是「我送出什麼
SQL/參數、rows 怎麼映射」這一層——真正的 SQL 正確性等 Supabase 開好後手動整合測。
"""
import json
from datetime import datetime, timezone

import db
from recommend import _track_key_from

FIXED = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)


class _Cur:
    def __init__(self):
        self.calls = []
        self.fetchall_rows = []
        self.fetchone_row = None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.calls.append((sql, params))

    def fetchall(self):
        return self.fetchall_rows

    def fetchone(self):
        return self.fetchone_row


class _Conn:
    def __init__(self):
        self.cur = _Cur()
        self.commits = 0

    def cursor(self):
        return self.cur

    def commit(self):
        self.commits += 1


def _last(conn):
    return conn.cur.calls[-1]


# ── 純邏輯：身分與鍵 ─────────────────────────────────────────
def test_user_key_stable_and_secret_sensitive():
    a = db.user_key("spotify_abc", "secret1")
    assert a == db.user_key("spotify_abc", "secret1")       # 穩定
    assert a != db.user_key("spotify_abc", "secret2")       # 換祕密就變
    assert a != db.user_key("spotify_xyz", "secret1")       # 換使用者就變
    assert len(a) == 64 and all(c in "0123456789abcdef" for c in a)


def test_user_key_does_not_leak_plain_id():
    assert "spotify_abc" not in db.user_key("spotify_abc", "s")


def test_key_str_uses_track_key_from():
    nt, na = _track_key_from("Song (Remastered 2011)", "Artist X")
    assert db.key_str("Song (Remastered 2011)", "Artist X") == f"{nt}\x1f{na}"


# ── 純邏輯：params 與 row 映射 ───────────────────────────────
def test_feedback_params_shape_and_ctx_json():
    p = db.feedback_params("uk", "旅行的意義", "Cheer Chen", "like",
                           fame=2, is_discovery=True, reason="橋接",
                           ctx={"lang": "華語"}, now=FIXED)
    assert p[0] == "uk"
    assert p[1] == db.key_str("旅行的意義", "Cheer Chen")
    assert (p[2], p[3], p[4]) == ("旅行的意義", "Cheer Chen", "like")
    assert (p[5], p[6], p[7]) == (2, True, "橋接")
    assert json.loads(p[8]) == {"lang": "華語"}      # ctx 存 JSON 字串
    assert p[9] == FIXED


def test_feedback_params_defaults():
    p = db.feedback_params("uk", "T", "A", "heard", now=FIXED)
    assert (p[5], p[6], p[7]) == (None, None, None)
    assert json.loads(p[8]) == {}


def test_row_to_feedback_entry_roundtrip():
    row = ("uk", "k", "旅行的意義", "Cheer Chen", "like", 2, True, "橋接",
           '{"lang":"華語"}', FIXED)
    assert db.row_to_feedback_entry(row) == {
        "track_key": "k", "title": "旅行的意義", "artist": "Cheer Chen",
        "state": "like", "fame": 2, "is_discovery": True, "reason": "橋接",
        "ctx": {"lang": "華語"},
    }


def test_row_to_feedback_entry_accepts_dict_ctx():
    # psycopg3 可能已把 jsonb 直接解成 dict
    row = ("uk", "k", "t", "a", "heard", None, None, None, {"x": 1}, FIXED)
    assert db.row_to_feedback_entry(row)["ctx"] == {"x": 1}


def test_row_to_history_entry():
    assert db.row_to_history_entry(("uk", "k", "Song", "Artist", FIXED)) == \
        {"title": "Song", "artist": "Artist"}


# ── DB 函式（假 conn）────────────────────────────────────────
def test_upsert_feedback_insert_on_conflict_and_commit():
    conn = _Conn()
    db.upsert_feedback(conn, "uk", "T", "A", "like", fame=3, now=FIXED)
    sql, params = _last(conn)
    assert "insert into feedback" in sql.lower()
    assert "on conflict (user_key, track_key)" in sql.lower()
    assert params == db.feedback_params("uk", "T", "A", "like", fame=3, now=FIXED)
    assert conn.commits == 1


def test_delete_feedback_targets_user_and_key():
    conn = _Conn()
    db.delete_feedback(conn, "uk", "T", "A")
    sql, params = _last(conn)
    assert "delete from feedback" in sql.lower()
    assert params == ("uk", db.key_str("T", "A"))
    assert conn.commits == 1


def test_load_feedback_maps_rows():
    conn = _Conn()
    conn.cur.fetchall_rows = [
        ("uk", "k1", "T1", "A1", "like", 2, True, "r1", "{}", FIXED),
        ("uk", "k2", "T2", "A2", "heard", None, None, None, '{"g":"jazz"}', FIXED),
    ]
    out = db.load_feedback(conn, "uk")
    assert [e["state"] for e in out] == ["like", "heard"]
    assert out[1]["ctx"] == {"g": "jazz"}


def test_upsert_history_one_execute_per_track():
    conn = _Conn()
    db.upsert_history(conn, "uk",
                      [{"title": "T1", "artist": "A1"}, {"title": "T2", "artist": "A2"}],
                      now=FIXED)
    inserts = [c for c in conn.cur.calls if "insert into history" in c[0].lower()]
    assert len(inserts) == 2
    assert inserts[0][1] == db.history_params("uk", "T1", "A1", FIXED)
    assert conn.commits == 1


def test_load_history_returns_old_to_new():
    conn = _Conn()
    conn.cur.fetchall_rows = [   # DB 回 newest-first
        ("uk", "k2", "New", "A", FIXED), ("uk", "k1", "Old", "A", FIXED)]
    assert [h["title"] for h in db.load_history(conn, "uk")] == ["Old", "New"]


def test_trim_history_passes_keep():
    conn = _Conn()
    db.trim_history(conn, "uk", keep=100)
    sql, params = _last(conn)
    assert "delete from history" in sql.lower()
    assert params == ("uk", "uk", 100)


def test_has_consent_true_when_version_ge():
    conn = _Conn()
    conn.cur.fetchone_row = (db.CONSENT_VERSION,)
    assert db.has_consent(conn, "uk") is True


def test_has_consent_false_when_absent_or_stale():
    conn = _Conn()
    conn.cur.fetchone_row = None
    assert db.has_consent(conn, "uk") is False
    conn.cur.fetchone_row = (0,)                 # 舊版本 < 目前
    assert db.has_consent(conn, "uk", version=1) is False


def test_set_consent_upsert():
    conn = _Conn()
    db.set_consent(conn, "uk", now=FIXED)
    sql, params = _last(conn)
    assert "insert into consent" in sql.lower()
    assert "on conflict (user_key)" in sql.lower()
    assert params == ("uk", FIXED, db.CONSENT_VERSION)
    assert conn.commits == 1


def test_delete_all_clears_three_tables():
    conn = _Conn()
    db.delete_all(conn, "uk")
    tables = {c[0].lower().split("from ")[1].split(" ")[0] for c in conn.cur.calls}
    assert tables == {"feedback", "history", "consent"}
    assert all(c[1] == ("uk",) for c in conn.cur.calls)
    assert conn.commits == 1


# ── 設定／連線（不碰 streamlit，monkeypatch _config）─────────
def test_is_enabled_reflects_config(monkeypatch):
    monkeypatch.setattr(db, "_config", lambda: ("postgres://x", "sek"))
    assert db.is_enabled() is True
    monkeypatch.setattr(db, "_config", lambda: (None, None))
    assert db.is_enabled() is False


def test_hmac_secret_from_config(monkeypatch):
    monkeypatch.setattr(db, "_config", lambda: ("url", "sek"))
    assert db.hmac_secret() == "sek"


def test_get_conn_none_without_url(monkeypatch):
    monkeypatch.setattr(db, "_config", lambda: (None, None))
    db._conn = None
    assert db.get_conn() is None
