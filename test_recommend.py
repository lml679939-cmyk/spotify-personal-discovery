"""
recommend.py 純邏輯單元測試。
執行：python -m pytest test_recommend.py -v
"""

import json

import pytest

from recommend import (
    HISTORY_KEEP,
    MAX_TRACKS_PER_ARTIST,
    _friendly_gemini_error,
    _norm,
    _parse_json_robust,
    _strip_code_fence,
    build_guest_prompt,
    build_prompt,
    dedupe_tracks,
)


# ── _norm ─────────────────────────────────────────────────
def test_norm_basic():
    assert _norm("  Hello World ") == "hello world"


def test_norm_none_and_empty():
    assert _norm(None) == ""
    assert _norm("") == ""


# ── _strip_code_fence ─────────────────────────────────────
def test_strip_fence_plain_json_unchanged():
    assert _strip_code_fence('{"a": 1}') == '{"a": 1}'


def test_strip_fence_json_fence():
    assert _strip_code_fence('```json\n{"a": 1}\n```') == '{"a": 1}'


def test_strip_fence_bare_fence():
    assert _strip_code_fence('```\n{"a": 1}\n```') == '{"a": 1}'


def test_strip_fence_none():
    assert _strip_code_fence(None) == ""


# ── _parse_json_robust ────────────────────────────────────
VALID = '{"context_interpretation":"晴天散步","recommendations":[{"title":"Song A","artist":"Artist X","reason":"清爽"}]}'


def test_parse_clean_json():
    result = _parse_json_robust(VALID)
    assert result["context_interpretation"] == "晴天散步"
    assert result["recommendations"][0]["title"] == "Song A"


def test_parse_fenced_json():
    result = _parse_json_robust(f"```json\n{VALID}\n```")
    assert len(result["recommendations"]) == 1


def test_parse_truncated_json_regex_fallback():
    # 尾端被截斷 → json.loads 失敗 → regex fallback 仍應撈出完整的曲目
    broken = (
        '{"context_interpretation":"雨夜","recommendations":['
        '{"title":"Song A","artist":"Artist X","reason":"r1"},'
        '{"title":"Song B","artist":"Artist Y","reason":"r2"},'
        '{"title":"Song C","artist":"Artist'  # 截斷
    )
    result = _parse_json_robust(broken)
    assert result["context_interpretation"] == "雨夜"
    assert [r["title"] for r in result["recommendations"]] == ["Song A", "Song B"]


def test_parse_garbage_raises():
    with pytest.raises(json.JSONDecodeError):
        _parse_json_robust("完全不是 JSON 的東西")


# ── _friendly_gemini_error ────────────────────────────────
def test_friendly_error_429():
    e = RuntimeError("429 RESOURCE_EXHAUSTED: quota exceeded")
    friendly = _friendly_gemini_error(e)
    assert friendly is not e
    assert "配額" in str(friendly)


def test_friendly_error_invalid_key():
    e = RuntimeError("400 API key not valid. Please pass a valid API key.")
    friendly = _friendly_gemini_error(e)
    assert "無效" in str(friendly)


def test_friendly_error_unknown_passthrough():
    e = RuntimeError("some other error")
    assert _friendly_gemini_error(e) is e


# ── dedupe_tracks ─────────────────────────────────────────
def _t(name, artist):
    return {"name": name, "artist": artist}


def test_dedupe_removes_duplicate_pairs_case_insensitive():
    tracks = [_t("Song A", "Artist X"), _t("song a", "artist x"), _t("Song B", "Artist X")]
    result = dedupe_tracks(tracks)
    assert [t["name"] for t in result] == ["Song A", "Song B"]


def test_dedupe_caps_tracks_per_artist():
    tracks = [_t(f"Song {i}", "Artist X") for i in range(5)]
    result = dedupe_tracks(tracks)
    assert len(result) == MAX_TRACKS_PER_ARTIST


def test_dedupe_collab_counts_primary_artist():
    # 合作曲以第一位藝人為計數主鍵
    tracks = [
        _t("S1", "Artist X"),
        _t("S2", "Artist X, Artist Y"),
        _t("S3", "Artist X, Artist Z"),  # X 已達 2 首上限 → 排除
        _t("S4", "Artist Y"),            # Y 只被算過 0 次（S2 主鍵是 X）→ 保留
    ]
    result = dedupe_tracks(tracks)
    assert [t["name"] for t in result] == ["S1", "S2", "S4"]


def test_dedupe_excludes_history():
    history = [{"title": "Old Song", "artist": "Artist X"}]
    tracks = [_t("Old Song", "Artist X"), _t("New Song", "Artist X")]
    result = dedupe_tracks(tracks, history=history)
    assert [t["name"] for t in result] == ["New Song"]


def test_dedupe_excludes_heard_titles_any_ratio():
    profile = {"heard_titles": ["Heard Song"], "heard_artists": []}
    tracks = [_t("Heard Song", "Whoever"), _t("Fresh Song", "Whoever")]
    result = dedupe_tracks(tracks, profile=profile, new_ratio=70)
    assert [t["name"] for t in result] == ["Fresh Song"]


def test_dedupe_ratio100_excludes_heard_artists_including_collab():
    profile = {"heard_titles": [], "heard_artists": ["Known Artist"]}
    tracks = [
        _t("S1", "Known Artist"),
        _t("S2", "New Artist, Known Artist"),  # 合作藝人在已接觸清單 → 排除
        _t("S3", "New Artist"),
    ]
    result = dedupe_tracks(tracks, profile=profile, new_ratio=100)
    assert [t["name"] for t in result] == ["S3"]


def test_dedupe_ratio_below_100_allows_heard_artists():
    profile = {"heard_titles": [], "heard_artists": ["Known Artist"]}
    tracks = [_t("S1", "Known Artist")]
    result = dedupe_tracks(tracks, profile=profile, new_ratio=70)
    assert len(result) == 1


def test_dedupe_accepts_title_key():
    # LLM 原始輸出用 "title"，Spotify 結果用 "name"，兩者都要能處理
    tracks = [{"title": "Song A", "artist": "X"}, {"title": "Song A", "artist": "X"}]
    assert len(dedupe_tracks(tracks)) == 1


# ── build_prompt ──────────────────────────────────────────
PROFILE = {
    "heard_titles": ["Heard One", "Heard Two"],
    "heard_artists": ["Artist One"],
    "top_artists": ["Artist One", "Artist Two"],
    "top_genres": ["pop", "indie"],
}


def test_build_prompt_basic_contents():
    p = build_prompt(PROFILE, "在咖啡廳讀書", num_songs=10)
    assert "10 首" in p
    assert "Artist One" in p
    assert "Heard One" in p
    assert "在咖啡廳讀書" in p


def test_build_prompt_fav_artists_block():
    p = build_prompt(PROFILE, "ctx", fav_artists=["周杰倫", "NewJeans"])
    assert "使用者指定歌手" in p
    assert "周杰倫, NewJeans" in p
    assert "使用者指定歌手" not in build_prompt(PROFILE, "ctx")


def test_build_prompt_language_and_genre_blocks():
    p = build_prompt(PROFILE, "ctx", languages=["華語", "日語"], genres=["Jazz"])
    assert "只推薦以下語言的歌：華語, 日語" in p
    assert "只推薦以下曲風的歌：Jazz" in p
    p_free = build_prompt(PROFILE, "ctx")
    assert "不限語言" in p_free
    assert "不限曲風" in p_free


def test_build_prompt_mode_blocks():
    assert "全部新藝人" in build_prompt(PROFILE, "ctx", new_ratio=100)
    assert "全部熟悉藝人" in build_prompt(PROFILE, "ctx", new_ratio=0)
    p70 = build_prompt(PROFILE, "ctx", num_songs=10, new_ratio=70)
    assert "**7 首**" in p70   # round(10*0.7)=7 首新藝人
    assert "**3 首**" in p70   # 其餘 3 首熟悉藝人


def test_build_prompt_history_trimmed_to_keep_limit():
    history = [{"title": f"H{i}", "artist": f"A{i}"} for i in range(HISTORY_KEEP + 50)]
    p = build_prompt(PROFILE, "ctx", history=history)
    assert f"H{HISTORY_KEEP + 49}" in p   # 最新的要在
    assert "- H0 - A0\n" not in p         # 最舊的要被裁掉


# ── build_guest_prompt ────────────────────────────────────
def test_guest_prompt_no_profile_wording():
    p = build_guest_prompt("深夜散步", num_songs=5)
    assert "沒有提供個人聆聽紀錄" in p
    assert "5 首" in p
    assert "深夜散步" in p


def test_guest_prompt_history_and_fav():
    p = build_guest_prompt(
        "ctx",
        history=[{"title": "Old", "artist": "X"}],
        fav_artists=["陳奕迅"],
    )
    assert "Old - X" in p
    assert "陳奕迅" in p
