"""spotify_api.py 的單元測試（用假 client，不碰網路）。

執行：python -m pytest test_spotify_api.py -v

⚠️ 本檔會 import streamlit（spotify_api 需要），比 test_recommend.py 慢一點。
純邏輯請放 recommend.py + test_recommend.py，這裡只測需要 Spotify 資料結構的部分。
"""

import hashlib
import hmac
import time

import pytest

import spotify_api
from recommend import _track_key


class _FakeSession:
    """_harden() 會在 client 上掛 HTTPAdapter。"""
    def mount(self, prefix, adapter):
        pass


def _track_payload(name="Song A", artist="Artist X", aid="aid1"):
    return {
        "name": name,
        "artists": [{"name": artist, "id": aid}],
        "album": {"name": "Album", "images": [{"url": "cover.jpg"}]},
        "external_urls": {"spotify": "https://open.spotify.com/track/1"},
        "uri": "spotify:track:1",
        "popularity": 42,
    }


class FakeSpotify:
    """記錄被呼叫幾次，讓測試能驗證「有沒有真的打 API」。"""

    def __init__(self, items=None):
        self._session = _FakeSession()
        self.calls = 0
        self._items = _track_payload() if items is None else items

    def search(self, q, type, limit):
        self.calls += 1
        items = [self._items] if self._items and "track:" in q else []
        return {"tracks": {"items": items}}


@pytest.fixture(autouse=True)
def _clear_cache():
    spotify_api._SEARCH_CACHE.clear()
    spotify_api._SEARCH_STATS.update(hits=0, misses=0)
    spotify_api._REPAIR_CACHE.clear()
    spotify_api._REPAIR_STATS.update(hits=0, misses=0)
    yield
    spotify_api._SEARCH_CACHE.clear()
    spotify_api._REPAIR_CACHE.clear()


# ── 搜尋快取 ──────────────────────────────────────────────
def test_search_result_is_cached_and_not_refetched():
    sp = FakeSpotify()
    first = spotify_api.search_track("Song A", "Artist X", sp=sp)
    second = spotify_api.search_track("Song A", "Artist X", sp=sp)
    assert first["name"] == second["name"] == "Song A"
    assert sp.calls == 1, "第二次應該走快取，不該再打 API"
    assert spotify_api.search_cache_info()["hits"] == 1


def test_cache_returns_a_copy_so_callers_cannot_poison_it():
    # 呼叫端會往回傳值塞 reason / fame / _discovery。若回傳的是快取裡那個物件本身，
    # 第一次生成就會把快取內容污染，之後所有人都拿到上一批的理由
    sp = FakeSpotify()
    first = spotify_api.search_track("Song A", "Artist X", sp=sp)
    first["reason"] = "第一批的理由"
    first["fame"] = 5
    second = spotify_api.search_track("Song A", "Artist X", sp=sp)
    assert "reason" not in second
    assert "fame" not in second
    assert first is not second


def test_cache_key_is_normalised_so_variants_share_one_entry():
    sp = FakeSpotify()
    spotify_api.search_track("Song A", "Artist X", sp=sp)
    spotify_api.search_track("Song A (Remastered 2011)", "Artist X", sp=sp)
    assert sp.calls == 1
    assert _track_key("Song A", "Artist X") in spotify_api._SEARCH_CACHE


def test_misses_are_cached_too():
    # 幻覺曲目會被不同使用者一再推薦，每次重搜要打兩個請求（嚴格 + 模糊），
    # 快取「找不到」省下來的其實最多
    sp = FakeSpotify(items=None)
    sp._items = None
    assert spotify_api.search_track("Ghost", "Nobody", sp=sp) is None
    assert spotify_api.search_track("Ghost", "Nobody", sp=sp) is None
    assert sp.calls == 2, "第一次要打嚴格 + 模糊兩次，第二次應該完全走快取"


def test_rate_limit_error_is_not_cached():
    """撞到 429 不能被當成「找不到」寫進快取，否則會毒化到限流結束為止。"""
    import spotipy

    class Boom(FakeSpotify):
        def search(self, q, type, limit):
            self.calls += 1
            raise spotipy.SpotifyException(429, -1, "rate limited")

    sp = Boom()
    with pytest.raises(spotipy.SpotifyException):
        spotify_api.search_track("Song A", "Artist X", sp=sp)
    assert _track_key("Song A", "Artist X") not in spotify_api._SEARCH_CACHE


def test_cache_is_bounded():
    spotify_api._SEARCH_CACHE.update(
        {(f"t{i}", f"a{i}"): None for i in range(spotify_api.SEARCH_CACHE_MAX)}
    )
    spotify_api.search_track("Song A", "Artist X", sp=FakeSpotify())
    assert len(spotify_api._SEARCH_CACHE) <= spotify_api.SEARCH_CACHE_MAX


# ── 重試設定（429 絕不能讓底層自己 sleep）────────────────
def test_client_never_retries_429():
    sp = spotify_api._sp("dummy-token")
    retry = sp._session.get_adapter("https://api.spotify.com").max_retries
    assert retry.respect_retry_after_header is False
    assert retry.is_retry("GET", 429, True) is False, "429 重試會遵守 Retry-After 睡好幾小時"
    assert retry.is_retry("GET", 503, True) is True, "5xx 仍要重試，否則會被誤判成限流"


# ── client-credentials token 不落地 ───────────────────────
def test_client_credentials_token_never_written_to_disk(monkeypatch):
    """spotipy 沒收到 cache_handler 時預設 CacheFileHandler()，會把 token 寫進 CWD 的
    `.cache`——與「token 只存記憶體」的設計相違。"""
    from spotipy.cache_handler import CacheFileHandler, MemoryCacheHandler

    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "cid_A")
    monkeypatch.setenv("SPOTIFY_CLIENT_SECRET", "secret")
    auth = spotify_api._client_credentials()
    assert isinstance(auth.cache_handler, MemoryCacheHandler)
    assert not isinstance(auth.cache_handler, CacheFileHandler)


def test_client_credentials_cache_is_shared_per_client_id(monkeypatch):
    # 同一個 Client ID 共用記憶體快取，才不會每次生成都重新換 token
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "cid_A")
    monkeypatch.setenv("SPOTIFY_CLIENT_SECRET", "secret")
    assert spotify_api._client_credentials().cache_handler is \
        spotify_api._client_credentials().cache_handler


def test_client_credentials_cache_is_isolated_between_client_ids(monkeypatch):
    # BYOK 使用者填的是自己的 Client ID，共用一份快取會讓不同 app 的 token 互相污染
    monkeypatch.setenv("SPOTIFY_CLIENT_SECRET", "secret")
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "cid_A")
    a = spotify_api._client_credentials().cache_handler
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "cid_B")
    b = spotify_api._client_credentials().cache_handler
    assert a is not b


# ── OAuth state：防授權碼注入 / login CSRF ────────────────
class _FakeContext:
    def __init__(self, cookies):
        self.cookies = cookies


def _xsrf_cookie(raw_token_hex: str, mask_hex: str) -> str:
    """組出 Tornado v2 格式的 XSRF cookie：2|<mask>|<masked token>|<ts>。

    同一個 raw token 每次送出的 mask 都不一樣（實測過），所以測試一定要用
    「兩組不同 mask、同一個 raw token」來驗證解遮罩後的值真的穩定。
    """
    mask = bytes.fromhex(mask_hex)
    raw = bytes.fromhex(raw_token_hex)
    masked = bytes(b ^ mask[i % len(mask)] for i, b in enumerate(raw))
    return f"2|{mask_hex}|{masked.hex()}|1787211642"


@pytest.fixture
def browser(monkeypatch):
    """把 st.context.cookies 換成假的，回傳一個「切換瀏覽器」的函式。"""
    def _use(cookies: dict | None):
        if cookies is None:
            class _Boom:
                @property
                def cookies(self):
                    raise RuntimeError("no script run context")
            monkeypatch.setattr(spotify_api.st, "context", _Boom())
        else:
            monkeypatch.setattr(spotify_api.st, "context", _FakeContext(cookies))
        # 兩個來源會互相影響，測 cookie 路徑時一定要清掉 localStorage 代號
        spotify_api.st.session_state.pop(spotify_api._BROWSER_ID_KEY, None)
    return _use


_TOKEN_A = "682ffabcee3c29d10e5eb7ded33bbf33"
_TOKEN_B = "0011223344556677889900aabbccddee"


def test_browser_secret_is_stable_across_remasked_cookies(browser):
    """Tornado 每次送 cookie 都換 mask——沒解遮罩的話 state 永遠驗不過，登入直接壞掉。"""
    browser({"_streamlit_xsrf": _xsrf_cookie(_TOKEN_A, "c7a369ce")})
    first = spotify_api._browser_secret()
    browser({"_streamlit_xsrf": _xsrf_cookie(_TOKEN_A, "61aae4da")})
    second = spotify_api._browser_secret()
    assert first == second == _TOKEN_A


def test_browser_secret_differs_between_browsers(browser):
    browser({"_streamlit_xsrf": _xsrf_cookie(_TOKEN_A, "c7a369ce")})
    a = spotify_api._browser_secret()
    browser({"_streamlit_xsrf": _xsrf_cookie(_TOKEN_B, "c7a369ce")})
    assert a != spotify_api._browser_secret()


def test_browser_secret_empty_when_context_unavailable(browser):
    browser(None)
    assert spotify_api._browser_secret() == ""
    browser({})
    assert spotify_api._browser_secret() == ""


def test_state_round_trips_for_the_same_browser(browser):
    """同一個瀏覽器發起、同一個瀏覽器導回——必須驗得過，否則正常登入會壞。"""
    browser({"_streamlit_xsrf": _xsrf_cookie(_TOKEN_A, "c7a369ce")})
    state = spotify_api._make_oauth_state()
    # 導回時 cookie 已經換了一組 mask，但 raw token 相同
    browser({"_streamlit_xsrf": _xsrf_cookie(_TOKEN_A, "61aae4da")})
    assert spotify_api._verify_oauth_state(state) is True


def test_state_from_another_browser_is_rejected(browser):
    """核心防護：攻擊者用自己的瀏覽器拿到 code+state，塞給受害者也驗不過。"""
    browser({"_streamlit_xsrf": _xsrf_cookie(_TOKEN_A, "c7a369ce")})
    attacker_state = spotify_api._make_oauth_state()
    browser({"_streamlit_xsrf": _xsrf_cookie(_TOKEN_B, "61aae4da")})
    assert spotify_api._verify_oauth_state(attacker_state) is False


def test_missing_or_malformed_state_is_rejected(browser):
    browser({"_streamlit_xsrf": _xsrf_cookie(_TOKEN_A, "c7a369ce")})
    for bad in (None, "", "nonsense", "a.b", "a.b.c.d", "notanint.nonce.sig"):
        assert spotify_api._verify_oauth_state(bad) is False


def test_tampered_signature_is_rejected(browser):
    browser({"_streamlit_xsrf": _xsrf_cookie(_TOKEN_A, "c7a369ce")})
    ts, nonce, sig = spotify_api._make_oauth_state().split(".")
    flipped = ("0" if sig[0] != "0" else "1") + sig[1:]
    assert spotify_api._verify_oauth_state(f"{ts}.{nonce}.{flipped}") is False
    assert spotify_api._verify_oauth_state(f"{ts}.{nonce}x.{sig}") is False


def test_expired_and_future_states_are_rejected(browser, monkeypatch):
    browser({"_streamlit_xsrf": _xsrf_cookie(_TOKEN_A, "c7a369ce")})
    state = spotify_api._make_oauth_state()
    real_time = spotify_api.time.time
    monkeypatch.setattr(
        spotify_api.time, "time",
        lambda: real_time() + spotify_api._OAUTH_STATE_TTL + 60,
    )
    assert spotify_api._verify_oauth_state(state) is False
    monkeypatch.setattr(spotify_api.time, "time", lambda: real_time() - 600)
    assert spotify_api._verify_oauth_state(state) is False


# ── ?error= 白名單（防釣魚內容注入）──────────────────────
def test_known_error_codes_pass_through():
    for code in ("access_denied", "invalid_client", "state_mismatch"):
        spotify_api._set_auth_error(code)
        assert spotify_api.st.session_state["spotify_auth_error"] == code


def test_markdown_payload_is_collapsed_to_unknown_error():
    """?error= 是攻擊者可控的網址參數，回顯到 st.warning() 會被當 Markdown 渲染——
    反引號跳脫 code span 之後就能在官方警告框裡插釣魚連結。"""
    payload = "x`\n\n[點此重新驗證你的 Spotify 帳號](https://evil.example)\n\n`"
    spotify_api._set_auth_error(payload)
    stored = spotify_api.st.session_state["spotify_auth_error"]
    assert stored == "unknown_error"
    assert "evil.example" not in stored
    assert "`" not in stored


def test_allowlisted_codes_contain_no_markdown_metacharacters():
    """白名單裡的代碼是「原樣留著」的，所以它們本身必須是安全的字面值。

    這條擋的是未來有人往白名單塞一個帶反引號/中括號的代碼——那等於自己開後門，
    讓回顯又變回可注入 Markdown。
    """
    import re
    for code in spotify_api._ALLOWED_OAUTH_ERRORS:
        assert re.fullmatch(r"[a-z_]+", code), f"{code!r} 不是純小寫識別字"


def test_unknown_error_is_itself_allowlisted():
    """_set_auth_error() 的 fallback 值若不在白名單裡，語意會自相矛盾。"""
    assert "unknown_error" in spotify_api._ALLOWED_OAUTH_ERRORS


# ── 幻覺補救（同歌手換一首真歌）──────────────────────────
class FakeCatalogSpotify:
    """支援 artist 搜尋 → artist_albums → album_tracks 的假 client。"""

    def __init__(self, artist_name="Bathe Alone", tracks=("T1", "T2", "T3", "T4")):
        self._session = _FakeSession()
        self.calls = 0
        self.artist_name = artist_name
        self.tracks = tracks

    def search(self, q, type, limit):
        self.calls += 1
        assert type == "artist"
        items = [] if self.artist_name is None else [{"name": self.artist_name, "id": "ar1"}]
        return {"artists": {"items": items}}

    def artist_albums(self, aid, include_groups, limit):
        self.calls += 1
        return {"items": [{
            "id": "al1", "name": "Album One", "album_type": "album",
            "images": [{"url": "big.jpg"}, {"url": "mid.jpg"}],
        }]}

    def album_tracks(self, aid, limit):
        self.calls += 1
        return {"items": [
            {"name": n,
             "artists": [{"name": self.artist_name, "id": "ar1"}],
             "external_urls": {"spotify": f"https://open.spotify.com/track/{i}"},
             "uri": f"spotify:track:{i}"}
            for i, n in enumerate(self.tracks)
        ]}


def test_repair_swaps_in_a_real_deep_cut_by_the_same_artist():
    sp = FakeCatalogSpotify()
    fixed = spotify_api.repair_hallucinated_track("編的歌名", "Bathe Alone", set(), sp=sp)
    assert fixed is not None and fixed["_repaired"] is True
    assert fixed["artist_names"] == ["Bathe Alone"]
    # 深軌啟發式：避開第 1 軌（通常是主打），從專輯中段排起——4 軌的中位是 T3
    assert fixed["name"] == "T3"
    assert fixed["cover"] == "mid.jpg"
    assert fixed["uri"] and fixed["url"]


def test_repair_respects_exclusion_keys():
    sp = FakeCatalogSpotify()
    excluded = {_track_key("T3", "Bathe Alone")}
    fixed = spotify_api.repair_hallucinated_track("編的歌名", "Bathe Alone", excluded, sp=sp)
    assert fixed["name"] == "T4"


def test_repair_catalog_is_cached_across_calls():
    sp = FakeCatalogSpotify()
    spotify_api.repair_hallucinated_track("編的 A", "Bathe Alone", set(), sp=sp)
    calls_after_first = sp.calls
    fixed2 = spotify_api.repair_hallucinated_track("編的 B", "Bathe Alone", set(), sp=sp)
    assert sp.calls == calls_after_first, "同歌手第二次補救應走快取，零請求"
    assert fixed2 is not None


def test_repair_unknown_artist_is_negative_cached():
    # 搜回來的歌手名對不上就不能亂補——補到別的歌手比不補救糟糕得多
    sp = FakeCatalogSpotify(artist_name="Totally Other Band")
    assert spotify_api.repair_hallucinated_track("X", "Nonexistent Guy", set(), sp=sp) is None
    calls_after_first = sp.calls
    assert spotify_api.repair_hallucinated_track("Y", "Nonexistent Guy", set(), sp=sp) is None
    assert sp.calls == calls_after_first, "找不到的歌手也要快取（幻覺歌手會被反覆提名）"


def test_repair_returns_copies_so_callers_cannot_poison_cache():
    sp = FakeCatalogSpotify()
    first = spotify_api.repair_hallucinated_track("編的 A", "Bathe Alone", set(), sp=sp)
    first["reason"] = "第一批的理由"
    second = spotify_api.repair_hallucinated_track("編的 B", "Bathe Alone", set(), sp=sp)
    assert "reason" not in second


# ── fav_artist_pool（指定歌手保底候選池）─────────────────────
def test_fav_artist_pool_tags_cards_and_caps_per_artist():
    sp = FakeCatalogSpotify(artist_name="陳綺貞", tracks=tuple(f"T{i}" for i in range(20)))
    pool = spotify_api.fav_artist_pool(["陳綺貞"], sp=sp)
    assert len(pool) == spotify_api.FAV_POOL_PER_ARTIST     # 每位歌手上限
    assert all(c["_fav_artist"] == "陳綺貞" for c in pool)   # 綁定標籤供跨文字系統辨識
    assert all(c.get("uri") and c.get("name") for c in pool)


def test_fav_artist_pool_respects_exclude_keys():
    sp = FakeCatalogSpotify(artist_name="陳綺貞", tracks=("T1", "T2", "T3", "T4"))
    # T3 是深軌啟發式的第一首（4 軌中位）——先排除它，確認不會被放進池子
    excluded = {_track_key("T3", "陳綺貞")}
    pool = spotify_api.fav_artist_pool(["陳綺貞"], excluded, sp=sp)
    assert all(_track_key(c["name"], "陳綺貞") not in excluded for c in pool)
    assert all(c["name"] != "T3" for c in pool)


def test_fav_artist_pool_uses_top_result_for_cjk_romanized_name():
    # 使用者親手打 CJK 藝名、Spotify 存的是羅馬拼音（陳綺貞 → Cheer Chen），
    # 嚴格比對對不上——指定歌手保底改採第一筆搜尋結果（本尊），池子不該是空的
    sp = FakeCatalogSpotify(artist_name="Cheer Chen")
    pool = spotify_api.fav_artist_pool(["陳綺貞"], sp=sp)
    assert pool and all(c["_fav_artist"] == "陳綺貞" for c in pool)


def test_fav_artist_pool_skips_artist_with_no_search_results():
    # 搜尋完全沒有結果才略過（top-result 也沒得取）
    sp = FakeCatalogSpotify(artist_name=None)
    pool = spotify_api.fav_artist_pool(["查無此人"], sp=sp)
    assert pool == []


def test_repair_still_strict_no_top_result_fallback():
    # 幻覺補救維持嚴格比對：LLM 給的歌手名不可信，退而取第一筆會補到別人
    sp = FakeCatalogSpotify(artist_name="Totally Other Band")
    assert spotify_api.repair_hallucinated_track("X", "LLM 亂編的歌手", set(), sp=sp) is None


# ── 拿不到瀏覽器祕密時要 fail closed（MED-6）──────────────
# 舊版的失效模式：_browser_secret() 回空字串 → 用**空金鑰**簽 HMAC。空金鑰的簽章
# 攻擊者也算得出來，於是 compare_digest 兩邊相符、state 看起來驗過了，實際上零綁定
# 效果（等同沒有 state），授權碼注入重新成立——而且整個過程完全無聲。

def test_sign_state_refuses_to_sign_without_a_browser_secret(browser):
    """做成例外，是為了讓「用空金鑰簽章」在任何程式路徑上都不可能發生。"""
    browser({})                                   # 有 context 但沒有 XSRF cookie
    with pytest.raises(spotify_api._NoBrowserSecret):
        spotify_api._sign_state("nonce", 1787211642)
    browser(None)                                 # 連 st.context 都取不到
    with pytest.raises(spotify_api._NoBrowserSecret):
        spotify_api._sign_state("nonce", 1787211642)


def test_state_forged_with_an_empty_secret_is_rejected(browser):
    """核心迴歸：舊版會接受這個 state（兩端都用空金鑰＝簽章必然相符）。"""
    issued_at = int(time.time())
    nonce = "attacker_nonce"
    forged = hmac.new(b"", f"{issued_at}.{nonce}".encode(), hashlib.sha256).hexdigest()
    browser({})                                   # 受害者這邊也拿不到 cookie
    assert spotify_api._verify_oauth_state(f"{issued_at}.{nonce}.{forged}") is False


def test_get_login_url_returns_none_when_state_cannot_be_bound(browser):
    """⚠️ 不能退而發一個沒帶 state 的網址——那等於把防護整個關掉，
    而且使用者完全看不出來。寧可少一種登入方式（訪客模式仍可用）。"""
    browser({})
    assert spotify_api.get_login_url() is None
    browser(None)
    assert spotify_api.get_login_url() is None


def test_get_login_url_still_carries_state_in_the_normal_case(browser, monkeypatch):
    """正常路徑不能被上面那道防線誤傷。"""
    monkeypatch.setattr(spotify_api, "_get_credential", lambda k: {
        "SPOTIFY_CLIENT_ID": "cid",
        "SPOTIFY_CLIENT_SECRET": "csec",
        "SPOTIFY_REDIRECT_URI": "https://example.test/",
    }[k])
    browser({"_streamlit_xsrf": _xsrf_cookie(_TOKEN_A, "c7a369ce")})
    url = spotify_api.get_login_url()
    assert url and "state=" in url


# ── 雲端路徑：沒有 Cookie，只有 localStorage 代號 ─────────
# ⚠️ Streamlit Cloud 的 websocket 握手標頭裡**沒有 Cookie**（實測，見 CLAUDE.md 的
# [GEO] 標頭清單），所以 _xsrf_secret() 在正式站永遠是空的。舊版只有 cookie 一條路，
# 於是雲端的 state 一直用空金鑰簽＝零綁定效果；MED-6 fail closed 之後就變成登入全掛。
# 以下這幾條測的就是正式站實際會跑的那條路。

_BID_A = "3f2504e0-4f89-41d3-9a0c-0305e82c3301"
_BID_B = "9c8e77a2-1b4d-4f60-8a3e-5d2c1b0a9f88"


@pytest.fixture
def cloud(monkeypatch):
    """模擬 Streamlit Cloud：context 有、但 cookies 是空的。"""
    monkeypatch.setattr(spotify_api.st, "context", _FakeContext({}))

    def _use(browser_id):
        if browser_id is None:
            spotify_api.st.session_state.pop(spotify_api._BROWSER_ID_KEY, None)
        else:
            spotify_api.st.session_state[spotify_api._BROWSER_ID_KEY] = browser_id

    _use(None)
    yield _use
    _use(None)


def test_state_round_trips_on_cloud_with_no_cookie_at_all(cloud):
    """正式站的主要路徑：綁定全靠 localStorage 代號。"""
    cloud(_BID_A)
    state = spotify_api._make_oauth_state()
    assert spotify_api._verify_oauth_state(state) is True


def test_state_from_another_browser_id_is_rejected(cloud):
    """核心防護在雲端一樣要成立：攻擊者的 state 到受害者瀏覽器要驗不過。"""
    cloud(_BID_A)
    attacker_state = spotify_api._make_oauth_state()
    cloud(_BID_B)
    assert spotify_api._verify_oauth_state(attacker_state) is False


def test_pending_browser_id_is_not_a_failure(cloud):
    """⚠️ 元件還沒回傳時**不能**當成失敗——那會把每個正常使用者在首輪誤判成攻擊。"""
    cloud(None)
    assert spotify_api.browser_id_pending() is True
    assert spotify_api._browser_secret() == ""


def test_unavailable_browser_id_is_terminal_not_pending(cloud):
    """localStorage 被擋是終局，該直接判失敗，不是無限等下去。"""
    cloud(spotify_api._BROWSER_ID_UNAVAILABLE)
    assert spotify_api.browser_id_pending() is False
    assert spotify_api._browser_secret() == ""
    assert spotify_api.get_login_url() is None


def test_cookie_short_circuits_the_pending_wait(browser):
    """本機直連有 cookie，就不必等元件。"""
    browser({"_streamlit_xsrf": _xsrf_cookie(_TOKEN_A, "c7a369ce")})
    assert spotify_api.browser_id_pending() is False
    assert spotify_api._browser_secret() != ""


def test_get_login_url_carries_state_on_cloud(cloud, monkeypatch):
    monkeypatch.setattr(spotify_api, "_get_credential", lambda k: {
        "SPOTIFY_CLIENT_ID": "cid",
        "SPOTIFY_CLIENT_SECRET": "csec",
        "SPOTIFY_REDIRECT_URI": "https://example.test/",
    }[k])
    cloud(_BID_A)
    url = spotify_api.get_login_url()
    assert url and "state=" in url


def test_browser_id_secret_is_not_the_raw_id_when_a_server_secret_exists(cloud, monkeypatch):
    """簽章金鑰不該等於訪客身分代號本身——兩者用途分開，其一外洩不波及另一個。"""
    monkeypatch.setattr(spotify_api, "_state_key", lambda: "server-side-secret")
    cloud(_BID_A)
    secret = spotify_api._browser_secret()
    assert secret and secret != _BID_A


def test_scopes_stay_minimal():
    """⚠️ 別加回 playlist-modify-public：歌單一律 public=False，那個 scope 從未使用，
    只會讓使用者在授權頁看到「修改你的公開歌單」。"""
    assert "playlist-modify-public" not in spotify_api.SCOPES
    assert "playlist-modify-private" in spotify_api.SCOPES
