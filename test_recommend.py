"""
recommend.py 純邏輯單元測試。
執行：python -m pytest test_recommend.py -v
"""

import json

import pytest

from recommend import (
    FEEDBACK_PROMPT_MAX,
    HISTORY_KEEP,
    MAX_TRACKS_PER_ARTIST,
    PLAY_PLATFORMS,
    PROMPT_HISTORY_MAX,
    _feedback_block,
    _flatten_channels,
    apple_music_search_url,
    POP_CEILING_DISCOVERY,
    POP_CEILING_MAX_RELAX,
    POP_CEILING_STRICT,
    _friendly_gemini_error,
    _loose_match,
    _norm,
    _norm_artist,
    _norm_title,
    _track_key_from,
    _track_matches_fav,
    _parse_json_robust,
    _strip_code_fence,
    _track_key,
    build_guest_prompt,
    build_prompt,
    curate_tracks,
    play_link,
    resolution_matches,
    youtube_search_url,
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


def test_parse_truncated_dual_channel_with_fame():
    # Phase 2 在 artist 和 reason 之間插了 fame。備援若寫死鍵順序，這裡會整個失效——
    # 而舊格式的測試照樣會過，完全看不出來壞了
    broken = (
        '{"taste_profile":"迷幻獨立","context_interpretation":"深夜整理",'
        '"discovery":[{"title":"A","artist":"X","fame":2,"reason":"r1"},'
        '{"title":"B","artist":"Y","fame":1,"reason":"r2"},'
        '{"title":"C","artist":"Z","fame'          # 截斷
    )
    result = _parse_json_robust(broken)
    assert result["taste_profile"] == "迷幻獨立"
    assert result["context_interpretation"] == "深夜整理"
    assert [r["title"] for r in result["recommendations"]] == ["A", "B"]
    assert [r["fame"] for r in result["recommendations"]] == [2, 1]


def test_parse_truncated_tolerates_any_key_order():
    broken = ('{"discovery":[{"artist":"X","reason":"r1","title":"A"},'
              '{"fame":4,"title":"B","artist":"Y"},{"title":"C"')
    recs = _parse_json_robust(broken)["recommendations"]
    assert [r["title"] for r in recs] == ["A", "B"]
    assert recs[0]["reason"] == "r1" and recs[1]["fame"] == 4


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


# ── 播放連結 ──────────────────────────────────────────────
def test_play_link_spotify_uses_resolved_url():
    t = {"name": "Song A", "artist": "Artist X", "url": "https://open.spotify.com/track/1"}
    assert play_link(t, "Spotify") == ("▶ Spotify", "https://open.spotify.com/track/1")


def test_spotify_miss_falls_back_to_youtube_even_in_spotify_mode():
    # 那首歌本來就不在 Spotify 上，給站內搜尋連結點過去必然落空；YouTube 幾乎都找得到
    t = {"name": "Drive My Car", "artist": "Peach Pit",
         "url": "https://open.spotify.com/search/x", "_no_spotify": True}
    label, url = play_link(t, "Spotify")
    assert label == "▶ YouTube"
    assert url.startswith("https://www.youtube.com/results?search_query=")
    assert "open.spotify.com" not in url


def test_play_link_youtube_ignores_spotify_miss():
    # Spotify 搜不到的歌，換成 YouTube 通常反而播得到——不該還是「🔍 搜尋」
    t = {"name": "Ghost", "artist": "Nobody", "url": "https://open.spotify.com/search/x",
         "_no_spotify": True}
    label, url = play_link(t, "YouTube")
    assert label == "▶ YouTube"
    assert url.startswith("https://www.youtube.com/results?search_query=")


def test_youtube_url_escapes_query():
    url = youtube_search_url("雨とカプチーノ", "ヨルシカ")
    assert " " not in url and "&" not in url.split("?", 1)[1].replace("search_query=", "")
    assert url.startswith("https://www.youtube.com/results?search_query=")


# ── _norm_title / _track_key ──────────────────────────────
def test_norm_title_strips_version_suffixes():
    assert _norm_title("Song A (Remastered 2011)") == "song a"
    assert _norm_title("Song A - Live") == "song a"
    assert _norm_title("Song A feat. Someone") == "song a"
    assert _norm_title("First Love (The Original & the Very First Recording)") == "first love"


def test_norm_title_keeps_meaningful_dash_suffix():
    # 只有版本關鍵字才砍，否則 'Song - Part 2' 會被誤當成 'Song'
    assert _norm_title("Song A - Part 2") == "song a part 2"


def test_norm_title_qualifier_needs_word_boundary():
    # 沒有 \b 的話：Delivery 含 live、Demons 含 demo、Credits 含 edit → 歌名被砍成半截
    assert _norm_title("Song - Special Delivery") == "song special delivery"
    assert _norm_title("Intro - Demons") == "intro demons"
    assert _norm_title("Song - Credits") == "song credits"
    # 真的版本後綴仍要砍掉
    assert _norm_title("Song - Live at Wembley") == "song"
    assert _norm_title("Song - 2011 Remaster") == "song"


def test_norm_title_folds_accents():
    assert _norm_title("Café") == _norm_title("Cafe")


def test_track_key_uses_primary_artist():
    assert _track_key("S", "Artist X, Artist Y") == _track_key("S", "Artist X")


def test_track_key_same_title_different_artist_differs():
    # 舊版只比歌名，害得「別人的同名歌」被誤殺——現在要能區分
    assert _track_key("Yesterday", "The Beatles") != _track_key("Yesterday", "Other Guy")


# ── resolution_matches（模糊搜尋的幻覺檢查） ───────────────
def test_resolution_accepts_exact():
    assert resolution_matches("Song A", "Artist X", "Song A", ["Artist X"])


def test_resolution_accepts_collab_superset():
    assert resolution_matches("Song A", "Tom Misch", "Song A", ["Tom Misch", "Yussef Dayes"])


def test_resolution_rejects_other_song_by_same_artist():
    # 模糊搜尋最常見的失敗：撈到同一位藝人的另一首熱門歌
    assert not resolution_matches("Obscure Deep Cut", "Adele", "Hello", ["Adele"])


def test_resolution_rejects_wrong_artist():
    assert not resolution_matches("Song A", "Artist X", "Song A", ["Someone Else"])


def test_resolution_rejects_title_superset_and_subset():
    # 「包含」比對沒有長度限制的話，這兩個都會被誤收——正好是要擋的「同歌手的另一首歌」
    assert not resolution_matches("Skyfall Reprise", "Adele", "Skyfall", ["Adele"])
    assert not resolution_matches("Hello", "Adele", "Hello Goodbye", ["Adele"])


def test_resolution_still_accepts_near_identical_title():
    assert resolution_matches("Song A", "Artist X", "Song A ", ["Artist X"])


def test_loose_match_rejects_substring_artists():
    # 子字串比對會讓 Sia 命中 Cassia、Rain 命中 Train；改成以「詞」為單位後不會
    assert not _loose_match("Sia", "Cassia")
    assert not _loose_match("Rain", "Train")


def test_loose_match_accepts_token_subset():
    assert _loose_match("Tom Misch", "Tom Misch & Yussef Dayes")
    assert _loose_match("竹内まりや", "竹内まりや Mariya Takeuchi")


def test_norm_artist_keeps_word_separation():
    # 空白全刪的話 Yellowcard 會等於 Yellow Card，害得陌生藝人被當成聽過
    assert _norm_artist("Yellowcard") != _norm_artist("Yellow Card")


# ── curate_tracks：訪客模式（profile is None）───────────────
def _t(name, artist):
    return {"name": name, "artist": artist}


def test_guest_removes_duplicate_pairs_case_insensitive():
    tracks = [_t("Song A", "Artist X"), _t("song a", "artist x"), _t("Song B", "Artist X")]
    result, _ = curate_tracks(tracks)
    assert [t["name"] for t in result] == ["Song A", "Song B"]


def test_guest_caps_tracks_per_artist():
    tracks = [_t(f"Song {i}", "Artist X") for i in range(5)]
    result, _ = curate_tracks(tracks)
    assert len(result) == MAX_TRACKS_PER_ARTIST


def test_guest_collab_counts_primary_artist():
    tracks = [
        _t("S1", "Artist X"),
        _t("S2", "Artist X, Artist Y"),
        _t("S3", "Artist X, Artist Z"),  # X 已達 2 首上限 → 排除
        _t("S4", "Artist Y"),            # Y 只被算過 0 次（S2 主鍵是 X）→ 保留
    ]
    result, _ = curate_tracks(tracks)
    assert [t["name"] for t in result] == ["S1", "S2", "S4"]


def test_guest_excludes_history():
    history = [{"title": "Old Song", "artist": "Artist X"}]
    tracks = [_t("Old Song", "Artist X"), _t("New Song", "Artist X")]
    result, _ = curate_tracks(tracks, history=history)
    assert [t["name"] for t in result] == ["New Song"]


def test_guest_accepts_title_key():
    # LLM 原始輸出用 "title"，Spotify 結果用 "name"，兩者都要能處理
    tracks = [{"title": "Song A", "artist": "X"}, {"title": "Song A", "artist": "X"}]
    result, _ = curate_tracks(tracks)
    assert len(result) == 1


def test_guest_no_spotify_cards_sort_to_the_end():
    # 搜尋連結卡沒封面又不能播，排在開頭看起來像整個功能壞掉（登入版早有此排序）
    tracks = [
        {"name": "Dead", "artist": "A", "_no_spotify": True},
        _t("Live 1", "B"),
        _t("Live 2", "C"),
    ]
    result, _ = curate_tracks(tracks)
    assert [t["name"] for t in result] == ["Live 1", "Live 2", "Dead"]


def test_guest_truncation_drops_no_spotify_cards_first():
    # 排序在截斷之前：超額生成的餘裕要優先留給可播放的曲目
    tracks = [
        {"name": "Dead", "artist": "A", "_no_spotify": True},
        _t("Live 1", "B"),
        _t("Live 2", "C"),
    ]
    result, _ = curate_tracks(tracks, num_songs=2)
    assert [t["name"] for t in result] == ["Live 1", "Live 2"]


def test_guest_trims_overgenerated_candidates_to_target():
    tracks = [_t(f"S{i}", f"Artist {i}") for i in range(10)]
    result, _ = curate_tracks(tracks, num_songs=4)
    assert [t["name"] for t in result] == ["S0", "S1", "S2", "S3"]


def test_guest_prompt_requests_fame_rating():
    p = build_guest_prompt("ctx")
    assert "每首都要標 fame" in p
    assert '"fame":3' in p          # JSON 範本要有這個鍵，LLM 才會照填


def test_guest_ceiling_cuts_mega_hits_first_on_overflow():
    # 超額時：太紅的（fame 5 → 95 > 80）優先被裁，餘裕留給驚喜選曲
    tracks = [
        {**_t("國民金曲", "A"), "fame": 5},
        {**_t("驚喜 1", "B"), "fame": 2},
        {**_t("驚喜 2", "C"), "fame": 3},
    ]
    result, stats = curate_tracks(tracks, num_songs=2)
    assert [t["name"] for t in result] == ["驚喜 1", "驚喜 2"]
    assert stats["pop_blocked"] == 1


def test_guest_ceiling_backfills_when_short():
    # 整批都太紅（使用者可能就是要經典金曲）→ 照樣回補，數量永不縮水
    tracks = [{**_t("金曲 1", "A"), "fame": 5}, {**_t("金曲 2", "B"), "fame": 5}]
    result, stats = curate_tracks(tracks, num_songs=2)
    assert len(result) == 2
    assert stats["pop_blocked"] == 0


def test_guest_ceiling_still_ranks_dead_cards_last():
    # 優先序：不超標 → 太紅 → 搜不到；太紅的仍排在死連結卡前面
    tracks = [
        {"name": "Dead", "artist": "X", "_no_spotify": True},
        {**_t("金曲", "A"), "fame": 5},
        {**_t("普通", "B"), "fame": 3},
    ]
    result, _ = curate_tracks(tracks)
    assert [t["name"] for t in result] == ["普通", "金曲", "Dead"]


def test_guest_fame_4_passes_the_looser_ceiling():
    # fame 4 換算 80 剛好貼線（> 80 才算超標）——訪客版只壓 fame 5 的國民金曲層級
    tracks = [{**_t("熱門但沒到國民", "A"), "fame": 4}, {**_t("普通", "B"), "fame": 3}]
    result, stats = curate_tracks(tracks, num_songs=1)
    assert result[0]["name"] == "熱門但沒到國民"   # 沒被降權，維持 LLM 順位
    assert stats["pop_blocked"] == 0


def test_guest_stats_count_each_drop_reason():
    # app.py 拿這些計數組「為什麼湊不滿」的說明，少列任何一個原因訊息就會自相矛盾
    history = [{"title": "Old", "artist": "X"}]
    tracks = [
        _t("Old", "X"),           # dup_history
        _t("New", "Y"),
        _t("new", "y"),           # dup_batch
        _t("S1", "Z"),
        _t("S2", "Z"),
        _t("S3", "Z"),            # 同藝人第 3 首 → artist_capped
    ]
    result, stats = curate_tracks(tracks, history=history)
    assert stats["dup_history"] == 1
    assert stats["dup_batch"] == 1
    assert stats["artist_capped"] == 1
    assert stats["picked_familiar"] == len(result) == 3


# ── 訪客探索度（fame_mode：熟悉/均衡/探索）──────────────────
def test_guest_prompt_discovery_mode_adds_low_fame_quota():
    # 探索：帶登入版那種「至少一半 fame1-2」的配額（疑點1：只給錨點 LLM 仍不自產 fame≤2）
    p = build_guest_prompt("ctx", fame_mode="discovery")
    assert "至少一半必須是 fame 1 或 2" in p


def test_guest_prompt_familiar_mode_has_no_quota():
    p = build_guest_prompt("ctx", fame_mode="familiar")
    assert "至少一半必須是 fame" not in p
    assert "fame 3-4" in p                      # 熟悉框架：熟悉曲目為主體


def test_guest_prompt_balanced_is_default_and_unchanged():
    # 均衡＝改版前行為：預設值就是 balanced，且沒有配額（避免破壞跨輪可比性）
    default = build_guest_prompt("ctx")
    balanced = build_guest_prompt("ctx", fame_mode="balanced")
    assert default == balanced
    assert "至少一半必須是 fame" not in default
    assert "混入一部分 2-3 分" in default


def test_guest_discovery_ceiling_blocks_fame_4():
    # 探索天花板 65：fame 4（換算 80）超標被降權；均衡（80）剛好貼線不擋
    tracks = [{**_t("大牌", "A"), "fame": 4}, {**_t("驚喜", "B"), "fame": 2}]
    disc, s_disc = curate_tracks(tracks, num_songs=1, fame_mode="discovery")
    assert disc[0]["name"] == "驚喜" and s_disc["pop_blocked"] == 1
    bal, s_bal = curate_tracks(tracks, num_songs=1, fame_mode="balanced")
    assert bal[0]["name"] == "大牌" and s_bal["pop_blocked"] == 0


def test_guest_familiar_ceiling_blocks_nothing():
    # 熟悉不擋：連 fame 5 國民金曲都保留（使用者要「聽得出來」的歌）
    tracks = [{**_t("國民金曲", "A"), "fame": 5}, {**_t("冷門", "B"), "fame": 1}]
    result, stats = curate_tracks(tracks, num_songs=1, fame_mode="familiar")
    assert result[0]["name"] == "國民金曲" and stats["pop_blocked"] == 0


def test_guest_default_fame_mode_matches_balanced():
    # 不傳 fame_mode 必須完全等於 balanced（其他情境零行為變動）
    tracks = [{**_t("金曲", "A"), "fame": 5}, {**_t("驚喜", "B"), "fame": 2},
              {**_t("普通", "C"), "fame": 3}]
    default, _ = curate_tracks(tracks, num_songs=2)
    balanced, _ = curate_tracks(tracks, num_songs=2, fame_mode="balanced")
    assert [t["name"] for t in default] == [t["name"] for t in balanced]


def test_guest_unknown_fame_mode_falls_back_to_balanced():
    tracks = [{**_t("金曲", "A"), "fame": 5}, {**_t("驚喜", "B"), "fame": 2}]
    weird, _ = curate_tracks(tracks, num_songs=1, fame_mode="???")
    balanced, _ = curate_tracks(tracks, num_songs=1, fame_mode="balanced")
    assert [t["name"] for t in weird] == [t["name"] for t in balanced]


def test_guest_stats_records_ceiling_per_mode():
    tracks = [_t("A", "X")]
    assert curate_tracks(tracks, fame_mode="familiar")[1]["ceiling"] is None
    assert curate_tracks(tracks, fame_mode="balanced")[1]["ceiling"] == 80
    assert curate_tracks(tracks, fame_mode="discovery")[1]["ceiling"] == 65


# ── curate_tracks：指定歌手保底（fav floor，兩種模式共用）──────
def _pool(name, fav_name, artist=None):
    """fav_artist_pool 回來的候選卡：帶 _fav_artist 標籤（fetch 時綁定，跨文字系統可靠）。"""
    a = artist or fav_name
    return {"name": name, "artist": a, "artist_names": [a], "_fav_artist": fav_name}


def test_fav_floor_backfills_from_pool_when_llm_short():
    # S4 的病：使用者點名兩位歌手，LLM 只給 1 首、同藝人上限又卡死。
    # 保底用真實深軌補到 round(6*0.5)=3 首，並平均分配。
    tracks = [_t("fav1", "陳綺貞")] + [_t(f"ctx{i}", f"N{i}") for i in range(6)]
    pool = [_pool("旅行的意義", "陳綺貞"), _pool("My Jinji", "落日飛車"),
            _pool("太陽", "陳綺貞"), _pool("Slow", "落日飛車")]
    result, stats = curate_tracks(
        tracks, num_songs=6, fav_artists=["陳綺貞", "落日飛車"], fav_pool=pool,
    )
    assert stats["fav_floor"] == 3
    assert stats["fav_have"] == 1        # LLM 只給了 1 首可播的指定歌手曲目
    assert stats["fav_added"] == 2       # 程式端補 2 首補到保底線
    assert len(result) == 6              # 長度不變（置換掉 2 首非指定歌手曲目）
    fav = [t for t in result if _track_matches_fav(t, ["陳綺貞", "落日飛車"],
                                                   {"陳綺貞", "落日飛車"})]
    assert len(fav) == 3


def test_fav_floor_noop_without_fav_artists():
    # 沒有指定歌手＝其他情境零行為變動：結果與統計都跟不帶 fav 參數時一致
    tracks = [_t("fav1", "陳綺貞")] + [_t(f"ctx{i}", f"N{i}") for i in range(6)]
    plain, _ = curate_tracks(tracks, num_songs=6)
    result, stats = curate_tracks(tracks, num_songs=6, fav_artists=None,
                                  fav_pool=[_pool("x", "陳綺貞")])
    assert [t["name"] for t in result] == [t["name"] for t in plain]
    assert stats["fav_floor"] == 0 and stats["fav_added"] == 0


def test_fav_floor_distributes_evenly_across_named_artists():
    # 不讓其中一位吃掉整個保底額：兩位各補一半
    tracks = [_t(f"ctx{i}", f"N{i}") for i in range(10)]
    pool = [_pool(f"A{i}", "陳綺貞") for i in range(5)] + \
           [_pool(f"B{i}", "落日飛車") for i in range(5)]
    result, stats = curate_tracks(
        tracks, num_songs=8, fav_artists=["陳綺貞", "落日飛車"], fav_pool=pool,
    )
    assert stats["fav_floor"] == 4 and stats["fav_added"] == 4
    from_a = sum(1 for t in result if t.get("_fav_artist") == "陳綺貞")
    from_b = sum(1 for t in result if t.get("_fav_artist") == "落日飛車")
    assert from_a == 2 and from_b == 2


def test_fav_floor_relaxes_per_artist_cap_for_named_artist():
    # 單一指定歌手：保底可以超過 MAX_TRACKS_PER_ARTIST（使用者明確點名＝想多聽幾首）
    tracks = [_t(f"ctx{i}", f"N{i}") for i in range(10)]
    pool = [_pool(f"deep{i}", "陳綺貞") for i in range(6)]
    result, stats = curate_tracks(
        tracks, num_songs=8, fav_artists=["陳綺貞"], fav_pool=pool,
    )
    assert stats["fav_floor"] == 4 and stats["fav_added"] == 4
    from_a = sum(1 for t in result if t.get("_fav_artist") == "陳綺貞")
    assert from_a == 4 > MAX_TRACKS_PER_ARTIST


def test_fav_floor_replaces_hallucinated_fav_card():
    # 搜不到的指定歌手卡（幻覺，_no_spotify）不算「已達成」，會被真實深軌替換掉
    tracks = [
        {"name": "編的歌名", "artist": "陳綺貞", "_no_spotify": True},
        _t("ctx1", "N1"), _t("ctx2", "N2"),
    ]
    pool = [_pool("旅行的意義", "陳綺貞")]
    result, stats = curate_tracks(
        tracks, num_songs=3, fav_artists=["陳綺貞"], fav_pool=pool,
    )
    assert stats["fav_have"] == 0        # 幻覺卡不算可播的指定歌手曲目
    assert stats["fav_added"] == 1
    names = [t["name"] for t in result]
    assert "旅行的意義" in names and "編的歌名" not in names


def test_fav_floor_matches_pool_by_tag_across_scripts():
    # pool 卡主藝名可能是羅馬拼音（落日飛車 → Sunset Rollercoaster），靠 _fav_artist 標籤辨識
    tracks = [_t(f"ctx{i}", f"N{i}") for i in range(4)]
    pool = [_pool("My Jinji", "落日飛車", artist="Sunset Rollercoaster")]
    result, stats = curate_tracks(
        tracks, num_songs=4, fav_artists=["落日飛車"], fav_pool=pool,
    )
    assert stats["fav_added"] == 1
    assert any(t["name"] == "My Jinji" for t in result)


def test_fav_floor_without_pool_only_reports_stats():
    # 第一輪 curate（fav_pool=None）只算 fav_floor/fav_have 供 app.py 決定要不要去抓 pool
    tracks = [_t("fav1", "陳綺貞")] + [_t(f"ctx{i}", f"N{i}") for i in range(6)]
    result, stats = curate_tracks(tracks, num_songs=6, fav_artists=["陳綺貞"])
    assert stats["fav_floor"] == 3 and stats["fav_have"] == 1
    assert stats["fav_added"] == 0
    assert len(result) == 6              # 沒 pool 就不動清單


def test_fav_floor_dedupes_pool_against_existing():
    # pool 裡與清單既有曲目同鍵的不重複補
    tracks = [_t("旅行的意義", "陳綺貞")] + [_t(f"ctx{i}", f"N{i}") for i in range(6)]
    pool = [_pool("旅行的意義", "陳綺貞"), _pool("太陽", "陳綺貞")]
    result, stats = curate_tracks(
        tracks, num_songs=6, fav_artists=["陳綺貞"], fav_pool=pool,
    )
    names = [t["name"] for t in result]
    assert names.count("旅行的意義") == 1   # 沒有被補成兩首
    assert "太陽" in names


def test_fav_floor_grows_short_list_toward_target():
    # 有空位時保底用真實深軌把短少的清單補長（順便解一部分「湊不滿」），不只是置換
    tracks = [_t("ctx1", "N1"), _t("ctx2", "N2")]   # 只有 2 首，num_songs=6
    pool = [_pool(f"deep{i}", "陳綺貞") for i in range(4)]
    result, stats = curate_tracks(
        tracks, num_songs=6, fav_artists=["陳綺貞"], fav_pool=pool,
    )
    # floor=3，但有空位 → 補到 per_cap=max(2, ceil(3/1)=3)=3，清單從 2 長到 5
    assert stats["fav_added"] == 3
    assert len(result) == 5


def test_fav_floor_login_injects_real_tracks_not_marked_discovery():
    # 登入模式：指定歌手不在聆聽紀錄、new_ratio=100、LLM 全給出圈曲。
    # 保底補進的指定歌手曲目是「明確點名」不是「出圈」，_discovery 要 False。
    profile = _profile(ids=["id::Known"])
    tracks = [_st(f"D{i}", f"Fresh{i}", pop=10) for i in range(4)]
    pool = [_pool("f1", "落日飛車"), _pool("f2", "落日飛車"),
            _pool("f3", "陳綺貞"), _pool("f4", "陳綺貞")]
    result, stats = curate_tracks(
        tracks, profile=profile, new_ratio=100, num_songs=4,
        fav_artists=["陳綺貞", "落日飛車"], fav_pool=pool,
    )
    assert stats["fav_floor"] == 2 and stats["fav_added"] == 2
    fav_in = [t for t in result if t.get("_fav_pick")]
    assert len(fav_in) == 2
    assert all(not t.get("_discovery") for t in fav_in)     # 點名 ≠ 出圈
    assert stats["picked_new"] == len(result) - 2           # 出圈只算真正沒接觸過的


# ── curate_tracks：登入模式驗證鏈 ──────────────────────────
def _st(name, artist, pop=20, **kw):
    """Spotify 搜尋回來的曲目（帶 popularity 與歌手 ID）。"""
    return {
        "name": name, "artist": artist, "popularity": pop,
        "artist_ids": [f"id::{artist}"], "artist_names": [artist], **kw,
    }


def _profile(ids=(), names=(), keys=()):
    return {
        "known_artist_ids": set(ids),
        "known_artist_names": set(names),
        "known_track_keys": set(keys),
    }


def test_known_artist_excluded_from_discovery_at_any_ratio():
    # 這是這次改版的核心：以前只有 new_ratio == 100 才擋熟悉藝人，
    # 70% 時「那 7 首新藝人」根本沒人檢查
    profile = _profile(ids=["id::Known"])
    tracks = [_st("S1", "Known"), _st("S2", "Fresh")]
    result, stats = curate_tracks(tracks, profile=profile, new_ratio=100, num_songs=1)
    assert [t["name"] for t in result] == ["S2"]
    assert stats["picked_new"] == 1


def test_known_artist_matched_by_name_when_id_missing():
    profile = _profile(names=["Known Artist"])
    tracks = [{"name": "S1", "artist": "Known Artist", "popularity": 10},
              {"name": "S2", "artist": "Fresh One", "popularity": 10}]
    result, _ = curate_tracks(tracks, profile=profile, new_ratio=100, num_songs=1)
    assert [t["name"] for t in result] == ["S2"]


def test_familiar_slots_still_allow_known_artists():
    # 70% 模式：熟悉額度本來就該給熟悉藝人（只是不能給聽過的那幾首）
    profile = _profile(ids=["id::Known"])
    tracks = [_st("S1", "Known"), _st("S2", "Fresh")]
    result, stats = curate_tracks(tracks, profile=profile, new_ratio=50, num_songs=2)
    assert len(result) == 2
    assert stats["picked_new"] == 1 and stats["picked_familiar"] == 1


def test_heard_track_excluded_even_for_familiar_artist():
    profile = _profile(ids=["id::Known"], keys=[_track_key("Heard One", "Known")])
    tracks = [_st("Heard One", "Known"), _st("Deep Cut", "Known")]
    result, stats = curate_tracks(tracks, profile=profile, new_ratio=0, num_songs=2)
    assert [t["name"] for t in result] == ["Deep Cut"]
    assert stats["known_track"] == 1


def test_band_name_with_comma_is_not_split():
    # 'Earth, Wind & Fire' 是一個團名不是三位合作藝人。切逗號的話比對鍵只剩 'earth'，
    # 已經聽過的歌就認不出來了——有 artist_names 時要直接用第一個元素
    profile = _profile(keys=[_track_key_from("September", "Earth, Wind & Fire")])
    tracks = [{
        "name": "September", "artist": "Earth, Wind & Fire", "popularity": 30,
        "artist_ids": ["id::ewf"], "artist_names": ["Earth, Wind & Fire"],
    }]
    result, stats = curate_tracks(tracks, profile=profile, new_ratio=100, num_songs=1)
    assert result == []
    assert stats["known_track"] == 1


def test_heard_track_matches_remaster_variant():
    profile = _profile(keys=[_track_key("Song A", "Artist X")])
    tracks = [_st("Song A (Remastered 2011)", "Artist X"), _st("Song B", "Artist X")]
    result, _ = curate_tracks(tracks, profile=profile, new_ratio=0, num_songs=2)
    assert [t["name"] for t in result] == ["Song B"]


def test_same_title_by_other_artist_not_killed():
    # 舊版 title-only 比對會把別人的同名歌一起殺掉
    profile = _profile(keys=[_track_key("Yesterday", "The Beatles")])
    tracks = [_st("Yesterday", "Other Guy")]
    result, _ = curate_tracks(tracks, profile=profile, new_ratio=100, num_songs=1)
    assert len(result) == 1


def test_llm_fame_substitutes_for_missing_popularity():
    # Spotify 已停止提供 popularity（2026-08 實測連 artist 的 followers/genres 都沒了），
    # 天花板必須靠 LLM 自評的 fame 才不會空轉
    profile = _profile()
    tracks = [
        {"name": "國民金曲", "artist": "A", "fame": 5, "artist_ids": ["id::A"], "artist_names": ["A"]},
        {"name": "冷門專輯曲", "artist": "B", "fame": 1, "artist_ids": ["id::B"], "artist_names": ["B"]},
    ]
    result, stats = curate_tracks(tracks, profile=profile, new_ratio=100, num_songs=1)
    assert [t["name"] for t in result] == ["冷門專輯曲"]
    assert stats["pop_from_fame"] == 2 and stats["pop_from_spotify"] == 0


def test_spotify_popularity_wins_over_fame_when_present():
    profile = _profile()
    tracks = [{"name": "S", "artist": "A", "popularity": 10, "fame": 5,
               "artist_ids": ["id::A"], "artist_names": ["A"]}]
    result, stats = curate_tracks(tracks, profile=profile, new_ratio=100, num_songs=1)
    assert len(result) == 1                      # popularity 10 → 過得了天花板
    assert stats["pop_from_spotify"] == 1 and stats["pop_from_fame"] == 0


def test_fame_tolerates_string_and_rejects_bool():
    # 模型偶爾把數字寫成字串。不容錯的話 "fame":"5" 會退回 UNKNOWN_POP(50)，
    # 最紅的歌反而直接穿過天花板
    profile = _profile()
    tracks = [{"name": "紅到爆", "artist": "A", "fame": "5",
               "artist_ids": ["id::A"], "artist_names": ["A"]},
              {"name": "冷門", "artist": "B", "fame": "1",
               "artist_ids": ["id::B"], "artist_names": ["B"]}]
    result, stats = curate_tracks(tracks, profile=profile, new_ratio=100, num_songs=1)
    assert [t["name"] for t in result] == ["冷門"]
    assert stats["pop_from_fame"] == 2

    # True 會被 int() 當成 1（最冷門那級），要當成「沒填」處理
    _, s = curate_tracks(
        [{"name": "S", "artist": "A", "fame": True, "artist_ids": ["x"], "artist_names": ["A"]}],
        profile=profile, new_ratio=100, num_songs=1,
    )
    assert s["pop_unknown"] == 1 and s["pop_from_fame"] == 0


def test_history_dedupe_handles_comma_band_names():
    # 歷史存的是逗號串接的字串，切逗號會把 'Tyler, The Creator' 切成 'tyler'，
    # 而候選那邊有 artist_names 陣列、算出來是 'tyler the creator'——兩邊對不上
    profile = _profile()
    history = [{"title": "EARFQUAKE", "artist": "Tyler, The Creator"}]
    tracks = [{"name": "EARFQUAKE", "artist": "Tyler, The Creator", "fame": 2,
               "artist_ids": ["id::t"], "artist_names": ["Tyler, The Creator"]}]
    result, stats = curate_tracks(tracks, history=history, profile=profile,
                                  new_ratio=100, num_songs=1)
    assert result == []
    assert stats["dup_history"] == 1


def test_dup_counts_split_history_from_batch():
    profile = _profile()
    history = [{"title": "Old", "artist": "A"}]
    tracks = [_st("Old", "A"), _st("New", "B"), _st("New", "B")]
    _, stats = curate_tracks(tracks, history=history, profile=profile,
                             new_ratio=100, num_songs=3)
    assert stats["dup_history"] == 1 and stats["dup_batch"] == 1


def test_flatten_channels_ignores_empty_recommendations_key():
    # 模型同時吐 "recommendations":[] 與 discovery 時，空清單不該勝出
    data = {"recommendations": [], "discovery": [{"title": "A", "artist": "X", "reason": "r"}]}
    assert len(_flatten_channels(data)["recommendations"]) == 1


def test_stats_show_when_no_popularity_signal_at_all():
    # 三個計數都要報出來，否則「天花板其實沒在跑」會完全看不出來
    profile = _profile()
    tracks = [{"name": "S", "artist": "A", "artist_ids": ["id::A"], "artist_names": ["A"]}]
    _, stats = curate_tracks(tracks, profile=profile, new_ratio=100, num_songs=1)
    assert stats["pop_unknown"] == 1
    assert stats["pop_from_spotify"] == 0 and stats["pop_from_fame"] == 0


def test_popularity_ceiling_prefers_obscure_candidate():
    profile = _profile()
    tracks = [_st("Mega Hit", "A", pop=95), _st("Obscure", "B", pop=20)]
    result, stats = curate_tracks(tracks, profile=profile, new_ratio=100, num_songs=1)
    assert [t["name"] for t in result] == ["Obscure"]
    assert stats["ceiling"] == POP_CEILING_STRICT


def test_popularity_ceiling_is_looser_below_ratio_100():
    profile = _profile()
    tracks = [_st("Mid", "A", pop=60)]
    result, stats = curate_tracks(tracks, profile=profile, new_ratio=70, num_songs=1)
    assert stats["ceiling"] == POP_CEILING_DISCOVERY
    assert len(result) == 1        # 60 < 65 → 過得了 70% 模式的天花板


def test_ceiling_relaxes_within_cap_when_short():
    # 湊不滿時可以放寬，但 100% 模式最多放寬到一般模式的水準（65）
    profile = _profile()
    tracks = [_st("Only Option", "A", pop=62)]
    result, stats = curate_tracks(tracks, profile=profile, new_ratio=100, num_songs=1)
    assert [t["name"] for t in result] == ["Only Option"]
    assert POP_CEILING_STRICT < stats["ceiling"] <= POP_CEILING_DISCOVERY


def test_ceiling_never_relaxes_into_mega_hits():
    # 放寬如果沒有上限，就會把天花板剛擋掉的大熱門整批放回來——等於沒有天花板。
    # 湊不滿寧可少幾首，這正是使用者選 100% 時要的。
    profile = _profile()
    tracks = [_st("Mega Hit", "A", pop=90)]
    result, stats = curate_tracks(tracks, profile=profile, new_ratio=100, num_songs=1)
    assert result == []
    assert stats["pop_blocked"] == 1


def test_pop_blocked_counts_candidates_left_behind_by_relaxation():
    # 放寬時會把一批候選從 blocked 取出，只用掉需要的幾首——沒用到的必須放回去，
    # 否則結果頁「擋掉了 N 首熱門歌」會少報
    profile = _profile()
    # pop=60 落在硬核天花板(55)與放寬上限(65)之間，才會走到「取出一批、只用一首」那條路
    tracks = [_st("Cheap", "A", pop=20)] + [_st(f"Warm{i}", f"W{i}", pop=60) for i in range(3)]
    result, stats = curate_tracks(tracks, profile=profile, new_ratio=100, num_songs=2)
    assert len(result) == 2                      # 1 首冷門 + 放寬後補 1 首
    assert stats["pop_blocked"] == 2             # 另外 2 首沒用到，仍要算在被擋的數量裡


def test_normal_mode_relaxes_further_than_strict_mode():
    profile = _profile()
    tracks = [_st("Popular", "A", pop=78)]
    result, stats = curate_tracks(tracks, profile=profile, new_ratio=70, num_songs=1)
    assert len(result) == 1
    assert stats["ceiling"] <= POP_CEILING_MAX_RELAX


def test_ratio_100_never_borrows_from_familiar():
    # 使用者明確要「完全沒聽過的藝人」，寧可少幾首也不塞熟悉藝人
    profile = _profile(ids=["id::K1", "id::K2", "id::K3"])
    tracks = [_st("New", "Fresh"), _st("A", "K1"), _st("B", "K2"), _st("C", "K3")]
    result, _ = curate_tracks(tracks, profile=profile, new_ratio=100, num_songs=3)
    assert [t["name"] for t in result] == ["New"]


def test_ratio_below_100_borrows_to_fill():
    profile = _profile(ids=["id::K1", "id::K2", "id::K3"])
    tracks = [_st("New", "Fresh"), _st("A", "K1"), _st("B", "K2"), _st("C", "K3")]
    result, _ = curate_tracks(tracks, profile=profile, new_ratio=70, num_songs=3)
    assert len(result) == 3


def test_unfound_tracks_used_only_as_filler():
    profile = _profile()
    tracks = [_st("Real", "A", pop=20),
              {"name": "Ghost", "artist": "B", "_no_spotify": True}]
    one, stats_one = curate_tracks(tracks, profile=profile, new_ratio=100, num_songs=1)
    assert [t["name"] for t in one] == ["Real"]
    assert stats_one["spare_used"] == 0
    two, stats_two = curate_tracks(tracks, profile=profile, new_ratio=100, num_songs=2)
    assert len(two) == 2 and stats_two["spare_used"] == 1


def test_spare_filling_is_capped():
    # 推向冷門後幻覺曲目大增。補位卡沒有上限的話，清單會被「只有搜尋連結」的卡塞滿——
    # 看起來湊滿了，其實幾乎都不能播，補生成也就永遠不會被觸發
    profile = _profile()
    tracks = [_st("Real", "A", pop=20)] + [
        {"name": f"Ghost{i}", "artist": f"G{i}", "_no_spotify": True} for i in range(20)
    ]
    result, stats = curate_tracks(tracks, profile=profile, new_ratio=100, num_songs=10)
    assert stats["spare_used"] <= 2               # 10 * SPARE_MAX_RATIO
    assert len(result) - stats["spare_used"] == 1  # 真正能播的只有 1 首，不該被掩蓋


def test_spare_cap_lifted_when_nothing_resolved_at_all():
    # 一首都沒解析成功＝搜尋本身出事（限流／斷線），不是 AI 推了一堆假歌。
    # 這時還套上限只會把 10 首的清單縮成 2 首，等於把東西藏起來
    profile = _profile()
    tracks = [{"name": f"Ghost{i}", "artist": f"G{i}", "_no_spotify": True} for i in range(12)]
    result, stats = curate_tracks(tracks, profile=profile, new_ratio=100, num_songs=10)
    assert len(result) == 10 and stats["spare_used"] == 10


def test_spare_cap_lifted_when_search_degraded():
    # 部分解析成功、但呼叫端知道搜尋有問題（撞到 429）時也要放行
    profile = _profile()
    tracks = [_st("Real", "A", pop=20)] + [
        {"name": f"Ghost{i}", "artist": f"G{i}", "_no_spotify": True} for i in range(12)
    ]
    _, capped = curate_tracks(tracks, profile=profile, new_ratio=100, num_songs=10)
    _, lifted = curate_tracks(tracks, profile=profile, new_ratio=100, num_songs=10,
                              spare_capped=False)
    assert capped["spare_used"] == 2 and lifted["spare_used"] == 9


def test_curate_caps_tracks_per_artist_in_login_mode():
    profile = _profile()
    tracks = [_st(f"S{i}", "Artist X", pop=10) for i in range(5)]
    result, _ = curate_tracks(tracks, profile=profile, new_ratio=100, num_songs=5)
    assert len(result) == MAX_TRACKS_PER_ARTIST


def test_curate_reports_average_popularity_of_new_slots():
    profile = _profile()
    tracks = [_st("A", "X", pop=10), _st("B", "Y", pop=30)]
    _, stats = curate_tracks(tracks, profile=profile, new_ratio=100, num_songs=2)
    assert stats["avg_pop_new"] == 20.0
    assert stats["picked_new"] == 2


def test_curate_trims_overgenerated_candidates_to_target():
    profile = _profile()
    tracks = [_st(f"S{i}", f"Artist{i}", pop=10) for i in range(24)]
    result, _ = curate_tracks(tracks, profile=profile, new_ratio=100, num_songs=15)
    assert len(result) == 15


def test_curate_marks_discovery_tracks_for_the_ui():
    # UI 靠這個旗標畫「🧭 出圈」標籤
    profile = _profile(ids=["id::Known"])
    tracks = [_st("New", "Fresh"), _st("Old", "Known"),
              {"name": "Ghost", "artist": "G", "_no_spotify": True}]
    result, _ = curate_tracks(tracks, profile=profile, new_ratio=50, num_songs=3)
    flags = {t["name"]: t["_discovery"] for t in result}
    assert flags["New"] is True
    assert flags["Old"] is False
    assert flags["Ghost"] is False      # 搜不到＝無從判斷，不能標成出圈


def test_guest_tracks_have_no_discovery_flag():
    # 訪客沒有已知清單，「出圈」對他們沒有意義，不該畫標籤
    result, _ = curate_tracks([_t("S", "A")])
    assert "_discovery" not in result[0]


def test_unfound_cards_are_sorted_to_the_end():
    # 搜不到的卡片沒封面、只有搜尋按鈕，排在最前面會讓清單看起來像壞掉的
    profile = _profile()
    tracks = [
        {"name": "Ghost1", "artist": "G1", "_no_spotify": True},
        _st("Real1", "A", pop=20),
        {"name": "Ghost2", "artist": "G2", "_no_spotify": True},
        _st("Real2", "B", pop=20),
    ]
    result, _ = curate_tracks(tracks, profile=profile, new_ratio=100, num_songs=4)
    names = [t["name"] for t in result]
    assert names[:2] == ["Real1", "Real2"], "能播的要排前面且維持原順序"
    # 補位卡有比例上限，實際用幾張不固定；要驗的是「一律墊底」這個性質
    flags = [bool(t.get("_no_spotify")) for t in result]
    assert flags == sorted(flags), "搜不到的卡片不能夾在能播的中間"
    assert any(flags), "這個情境本來就該用到補位卡"


def test_curate_preserves_llm_order_in_output():
    profile = _profile()
    tracks = [_st("First", "A", pop=40), _st("Second", "B", pop=10)]
    result, _ = curate_tracks(tracks, profile=profile, new_ratio=100, num_songs=2)
    assert [t["name"] for t in result] == ["First", "Second"]


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
    assert "在咖啡廳讀書" in p


def test_build_prompt_drops_full_heard_titles_list():
    # 完整曲目清單改由程式端比對。prompt 裡塞上百行既拖慢又不被遵守
    #（清單愈長遵守率愈差，長 context 中段還最容易被忽略）
    p = build_prompt(PROFILE, "ctx")
    assert "Heard One" not in p
    assert "Heard Two" not in p


def test_build_prompt_taste_profile_step_comes_first():
    # 去錨定：先歸納品味特徵再推薦，而不是從喜愛藝人直接聯想同溫層大牌
    p = build_prompt(PROFILE, "ctx")
    assert "taste_profile" in p
    assert "從這些特徵出發" in p
    assert p.index("第一步") < p.index("## 使用者口味")


def test_build_prompt_exclusion_list_sits_at_the_end():
    # 排除清單要緊鄰輸出格式——放中段最容易被忽略
    p = build_prompt(PROFILE, "ctx", new_ratio=100)
    assert p.index("這次要產出的清單") < p.index("輸出前的最後檢查") < p.index("只輸出 JSON")


def test_build_prompt_refill_block():
    p = build_prompt(PROFILE, "ctx", refill_exclude=[("Old Song", "Old Artist")])
    assert "補充生成" in p
    assert "Old Song - Old Artist" in p
    assert "補充生成" not in build_prompt(PROFILE, "ctx")


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


def test_build_prompt_dual_channels_and_counts():
    p70 = build_prompt(PROFILE, "ctx", num_songs=10, new_ratio=70)
    assert "discovery（7 首）" in p70   # round(10*0.7)=7
    assert "familiar（3 首）" in p70
    assert "相鄰但不同" in p70          # 探索通道的指令
    assert "避開他們的熱門主打歌" in p70  # 熟悉通道的指令


def test_build_prompt_omits_empty_channel():
    # 沒有配額的通道整段不要出現，免得 LLM 還是硬生一些出來
    p100 = build_prompt(PROFILE, "ctx", new_ratio=100)
    assert "discovery（" in p100 and "familiar（" not in p100
    p0 = build_prompt(PROFILE, "ctx", new_ratio=0)
    assert "familiar（" in p0 and "discovery（" not in p0


def test_build_prompt_history_trimmed_to_prompt_limit():
    n = HISTORY_KEEP + 50
    history = [{"title": f"H{i}", "artist": f"A{i}"} for i in range(n)]
    p = build_prompt(PROFILE, "ctx", history=history)
    assert f"- H{n - 1} - A{n - 1}" in p                  # 最新的要在
    assert f"- H{n - PROMPT_HISTORY_MAX} - " in p         # 剛好在上限內的也要在
    assert f"- H{n - PROMPT_HISTORY_MAX - 1} - " not in p  # 超出上限的要被裁掉
    assert "- H0 - A0\n" not in p


# ── _flatten_channels（雙通道 → 單一清單）─────────────────
def test_flatten_channels_merges_two_lists():
    data = {
        "taste_profile": "偏好 city pop 與 lo-fi",
        "context_interpretation": "深夜整理房間",
        "discovery": [{"title": "A", "artist": "X", "reason": "r"}],
        "familiar": [{"title": "B", "artist": "Y", "reason": "r"}],
    }
    out = _flatten_channels(data)
    assert [r["title"] for r in out["recommendations"]] == ["A", "B"]
    assert out["taste_profile"].startswith("偏好")
    assert out["context_interpretation"] == "深夜整理房間"


def test_flatten_channels_accepts_legacy_schema():
    # 訪客模式與 regex fallback 產出的仍是舊格式，要照樣能用
    data = {"context_interpretation": "c", "recommendations": [
        {"title": "A", "artist": "X", "reason": "r"}]}
    assert len(_flatten_channels(data)["recommendations"]) == 1


def test_flatten_channels_drops_incomplete_entries():
    data = {"discovery": [{"title": "A"}, {"title": "B", "artist": "Y"}, "垃圾"]}
    assert [r["title"] for r in _flatten_channels(data)["recommendations"]] == ["B"]


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


def test_guest_prompt_history_trimmed_to_prompt_limit():
    # 與登入版同一條原則：prompt 只放最近 PROMPT_HISTORY_MAX 筆做機率優化，
    # 完整排除靠程式端 _basic_dedupe 拿整份歷史比對
    n = HISTORY_KEEP + 50
    history = [{"title": f"H{i}", "artist": f"A{i}"} for i in range(n)]
    p = build_guest_prompt("ctx", history=history)
    assert f"- H{n - 1} - A{n - 1}" in p                   # 最新的要在
    assert f"- H{n - PROMPT_HISTORY_MAX} - " in p          # 剛好在上限內的也要在
    assert f"- H{n - PROMPT_HISTORY_MAX - 1} - " not in p  # 超出上限的要被裁掉


def test_guest_prompt_refill_block_only_when_excluding():
    p = build_guest_prompt("ctx", refill_exclude=[("Song A", "X")])
    assert "補充生成" in p
    assert "- Song A - X" in p
    assert "補充生成" not in build_guest_prompt("ctx")


# ── Apple Music 播放平台 ──────────────────────────────────
def test_play_platforms_include_apple_music():
    assert PLAY_PLATFORMS == ("Spotify", "YouTube", "Apple Music")


def test_play_link_apple_music_uses_search_url():
    t = {"name": "花火", "artist": "宇多田ヒカル", "url": "https://open.spotify.com/track/x"}
    label, url = play_link(t, "Apple Music")
    assert label == "▶ Apple Music"
    assert url.startswith("https://music.apple.com/tw/search?term=")
    assert "%E8%8A%B1%E7%81%AB" in url  # 「花火」要有 URL encode


def test_play_link_apple_music_ignores_no_spotify_flag():
    # Apple Music 走搜尋頁，跟 Spotify 搜不搜得到無關——不必退回 YouTube
    label, _ = play_link({"name": "S", "artist": "X", "_no_spotify": True}, "Apple Music")
    assert label == "▶ Apple Music"


# ── 使用者回饋 → prompt 區塊 ──────────────────────────────
def test_feedback_block_empty_cases():
    assert _feedback_block(None) == ""
    assert _feedback_block({"liked": [], "disliked": [], "heard": []}) == ""


def test_feedback_block_lists_three_sections():
    fb = {
        "liked": [{"title": "L", "artist": "A"}],
        "disliked": [{"title": "D", "artist": "B"}],
        "heard": [{"title": "H", "artist": "C"}],
    }
    block = _feedback_block(fb)
    assert "- L - A" in block and "- D - B" in block and "- H - C" in block
    assert "相鄰" in block      # 喜歡＝往相鄰方向探索
    assert "避開" in block      # 不喜歡＝避開方向
    assert "更大膽" in block    # 聽過了＝出圈校準


def test_feedback_block_caps_each_list():
    liked = [{"title": f"L{i}", "artist": "A"} for i in range(FEEDBACK_PROMPT_MAX + 5)]
    block = _feedback_block({"liked": liked})
    assert f"- L{FEEDBACK_PROMPT_MAX + 4} - A" in block  # 最新的要在
    assert "- L4 - A" not in block                       # 超出上限的最舊筆要被裁掉


def test_both_prompts_include_feedback_block():
    fb = {"liked": [{"title": "Fav", "artist": "Z"}]}
    assert "Fav - Z" in build_guest_prompt("ctx", feedback=fb)
    assert "Fav - Z" in build_prompt(PROFILE, "ctx", feedback=fb)
    assert "對過往推薦的回饋" not in build_guest_prompt("ctx")
