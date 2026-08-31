"""
Spotify API 層：OAuth、client、搜尋、歌單、跨 session 歷史。
只在函式被呼叫時才碰 session_state——import 本模組不會執行任何 UI 程式碼。
"""

import binascii
import hashlib
import hmac
import os
import secrets
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import streamlit as st
import spotipy
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from spotipy.oauth2 import SpotifyOAuth, SpotifyClientCredentials
from spotipy.cache_handler import MemoryCacheHandler

from recommend import (
    _loose_match,
    _norm_artist,
    _track_key,
    _track_key_from,
    resolution_matches,
)

PERSISTENT_HISTORY_MAX = 500  # 跨 session 歷史歌單保留上限，超過會修剪最舊的

# ── 聆聽資料抓取範圍 ──────────────────────────────────────
# 以前只抓 top 30 + 最近 50 + 收藏 100 ≈ 180 首，兩年前天天聽、最近沒播的歌手
# 會被判成「全新藝人」——「選了全新卻推熟歌」有一半是這裡漏掉的。
TOP_FETCH_LIMIT = 50        # top tracks/artists 每個時間範圍各抓幾筆（API 上限 50）
SAVED_FETCH_MAX = 500       # 收藏曲目抓到第幾首（分頁並行）
PROFILE_WORKERS = 10        # profile 抓取的並行度
TIME_RANGES = ("short_term", "medium_term", "long_term")
PROMPT_HEARD_TITLES_MAX = 60   # 放進 prompt 的曲目樣本上限（完整清單只在程式端比對）
PROMPT_EXCLUDE_ARTISTS_MAX = 50  # 放進 prompt 的排除歌手上限（清單太長 LLM 反而不遵守）

_PROFILE_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="profile")

# ── 搜尋結果快取 ─────────────────────────────────────────
# 單次推薦要打上百個搜尋請求，而所有使用者共用同一組 Client ID 的配額。
# LLM 的推薦重複性很高（同一個情境不同人跑，常出現同一批歌），跨使用者共用快取
# 是降低請求量最省事的一招。
# client-credentials token 的記憶體快取，依 client id 分開（見 _client_credentials()）。
# 用 module 層級是為了讓 token 在 process 內共用，不必每次生成都重新換一次。
_CC_CACHES: dict[str, MemoryCacheHandler] = {}
_CC_CACHE_LOCK = threading.Lock()

SEARCH_CACHE_MAX = 2000
_SEARCH_CACHE: dict[tuple[str, str], dict | None] = {}
_SEARCH_CACHE_LOCK = threading.Lock()
_SEARCH_STATS = {"hits": 0, "misses": 0}


def _cache_search(key: tuple[str, str], value: dict | None) -> dict | None:
    """寫入快取並回傳原值。

    ⚠️ 只有「真的搜過而且有結論」才會走到這裡——撞到 429 時 spotipy 會拋例外，
    不會回到這一行，所以限流造成的「找不到」不會被寫進快取毒化後續查詢。
    """
    with _SEARCH_CACHE_LOCK:
        if len(_SEARCH_CACHE) >= SEARCH_CACHE_MAX:
            _SEARCH_CACHE.clear()      # 夠用的淘汰策略：滿了就整批丟掉重建
        # 存複本、回原件——呼叫端會往回傳值裡塞 reason / fame / _discovery，
        # 存同一個物件的話第一次生成就把快取內容污染了
        _SEARCH_CACHE[key] = dict(value) if value is not None else None
    return value


def search_cache_info() -> dict:
    with _SEARCH_CACHE_LOCK:
        return {"size": len(_SEARCH_CACHE), **_SEARCH_STATS}

# ⚠️ 429 絕對不能讓底層自己重試。實測撞到限制時 Retry-After 是 21315 秒（約 6 小時），
# urllib3 會遵守它並真的 sleep 下去，整個頁面凍在「搜尋歌曲中」不動。
#
# 兩個直覺的做法都不對：
#   1. `retries=0` —— 確實不會睡，但 urllib3 第一次 increment() 就丟 MaxRetryError，
#      spotipy 的 handler 寫死轉成 SpotifyException(429)，**所有 5xx 與連線中斷都會被
#      誤判成速率限制**，一顆暫時性 503 就讓整批搜尋短路。
#   2. 只把 429 移出 `status_forcelist` —— 沒用。urllib3 的 Retry.is_retry() 有一條
#      獨立路徑：只要 total>0、respect_retry_after_header=True 且回應帶 Retry-After，
#      429 就算不在 forcelist 也照樣重試（429 在 Retry.RETRY_AFTER_STATUS_CODES 裡）。
# 正解是自己掛一個 respect_retry_after_header=False 的 adapter：
# 429 立刻拋出、5xx 與連線問題仍照常重試。
SPOTIFY_RETRIES = 3
SPOTIFY_RETRY_CODES = (500, 502, 503, 504)


def _harden(sp: spotipy.Spotify) -> spotipy.Spotify:
    retry = Retry(
        total=SPOTIFY_RETRIES,
        connect=SPOTIFY_RETRIES,
        read=SPOTIFY_RETRIES,
        status=SPOTIFY_RETRIES,
        backoff_factor=0.3,
        status_forcelist=SPOTIFY_RETRY_CODES,
        respect_retry_after_header=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    sp._session.mount("http://", adapter)
    sp._session.mount("https://", adapter)
    return sp


def _sp(auth: str) -> spotipy.Spotify:
    return _harden(spotipy.Spotify(auth=auth))


def _local_now() -> datetime:
    """使用者當地時間；時區偏移由 app.py 的 IP 定位寫進 session_state（伺服器時鐘是 UTC）。"""
    offset = st.session_state.get("geo_tz_offset", 8 * 3600)
    return datetime.now(timezone.utc).astimezone(timezone(timedelta(seconds=offset)))


def _get_env(key: str, default: str | None = None) -> str | None:
    """Read config from os.environ first, then Streamlit secrets (cloud)."""
    val = os.getenv(key)
    if val:
        return val
    try:
        return st.secrets.get(key, default)
    except Exception:
        return default


def _get_credential(key: str) -> str | None:
    """User-provided key (session_state) → env/secrets fallback."""
    custom = st.session_state.get(f"custom_{key}")
    if custom and custom.strip():
        return custom.strip()
    return _get_env(key)

SCOPES = (
    "user-top-read user-read-recently-played user-library-read user-follow-read "
    "playlist-read-private playlist-modify-public playlist-modify-private"
)

# 跨 session 歷史（存在 Spotify 私人歌單裡）
HISTORY_PLAYLIST_NAME = "🤖 AI Discovery History (請勿手動刪除)"

# ── OAuth state（防授權碼注入 / login CSRF）──────────────
# 沒有 state 的話，攻擊者可以用自己的帳號授權、拿到 ?code= 之後不讓自己的分頁載入，
# 再把 https://本站/?code=攻擊者的code 傳給受害者——受害者一點開就被靜默綁到攻擊者的
# Spotify 帳號，之後生成的歌單與推薦歷史全部寫進攻擊者的帳號（攻擊者可回頭讀取）。
#
# ⚠️ 教科書寫法「nonce 存 session_state、回來再比對」在 Streamlit 上行不通：
# 使用者跳去 Spotify 再導回來是**整頁重新載入**，session_state 會整個重生
# （實測 nonce e2b32d96 → 909f0aa6），比對永遠失敗＝登入直接壞掉。
#
# 解法是做成無狀態的簽章：state = 時間戳.nonce.HMAC(瀏覽器祕密, 時間戳.nonce)。
# 「瀏覽器祕密」取自 Streamlit 的 _streamlit_xsrf cookie——它撐得過整頁導向，
# 而且是逐瀏覽器獨立的。攻擊者拿到的 state 是用**攻擊者的**瀏覽器祕密簽的，
# 到了受害者的瀏覽器就驗不過，攻擊即失效。伺服器端不需要存任何東西。
_OAUTH_STATE_TTL = 600   # 授權來回的有效秒數（Spotify 的 code 本身也只有 ~10 分鐘）
_OAUTH_WAIT_MAX = 3      # 等 localStorage 元件回傳的最多輪數（正常一輪就好）


# app.py 把 localStorage 代號放進 session_state 的這個鍵（見 app._resolve_browser_id）
_BROWSER_ID_KEY = "browser_id"
_BROWSER_ID_UNAVAILABLE = "unavailable"
_STATE_KEY: str | None = None


def _state_key() -> str:
    """推導簽章金鑰用的站方祕密；沒設定回空字串。

    有 `PERSIST_HMAC_SECRET` 時用它推導，好處是**簽章金鑰永遠不等於訪客身分代號本身**
    ——兩者用途分開，其一外洩不會直接波及另一個。
    ⚠️ 不能改用「每個行程隨機產生」的金鑰：那樣重啟後所有還在 TTL 內的 state 會全部驗不過。
    """
    global _STATE_KEY
    if _STATE_KEY is None:
        try:
            import db          # 延遲載入；db 只 import recommend，無循環相依
            _STATE_KEY = db.hmac_secret() or ""
        except Exception:
            _STATE_KEY = ""
    return _STATE_KEY


def _browser_id_secret() -> str:
    """由 localStorage 代號推導的瀏覽器祕密；代號還沒回傳／拿不到時回空字串。"""
    try:
        bid = st.session_state.get(_BROWSER_ID_KEY)
    except Exception:
        return ""
    if not bid or bid == _BROWSER_ID_UNAVAILABLE:
        return ""
    key = _state_key()
    if not key:
        # 沒設站方祕密時直接用代號本身：v4 UUID 有 122 bits 亂度，當 HMAC 金鑰夠用
        return str(bid)
    return hmac.new(key.encode(), f"oauth:{bid}".encode(), hashlib.sha256).hexdigest()


def browser_id_pending() -> bool:
    """「現在拿不到祕密，但可能只是元件還沒回傳」＝呼叫端該再等一輪，別急著判失敗。

    ⚠️ 這跟「這個瀏覽器根本給不了」(`_BROWSER_ID_UNAVAILABLE`) 是兩回事：後者是終局，
    直接失敗才對；前者若也當成失敗，正常使用者會在首輪就被誤判成攻擊。
    """
    if _xsrf_secret():
        return False
    try:
        return st.session_state.get(_BROWSER_ID_KEY) is None
    except Exception:
        return False


def _browser_secret() -> str:
    """逐瀏覽器獨立、且能撐過整頁導向的祕密值。取不到時回空字串。

    **兩個來源，順序固定**（不能反過來，否則同一次流程中值會跳動、state 必然驗不過）：
      ① `_streamlit_xsrf` cookie——本機直連拿得到，同步、零額外往返。
      ② localStorage 代號——⚠️ **Streamlit Cloud 的 websocket 握手標頭裡沒有 `Cookie`**
         （實測；`[GEO]` 日誌印出的標頭清單可佐證），所以雲端只剩這條。
         舊版只有 ①，於是**雲端一直回空字串**＝state 完全沒有綁定效果，而且無聲。

    同一個部署環境裡兩者的有無是固定的（雲端永遠沒 cookie、本機直連永遠有），所以不會跳動。
    """
    xsrf = _xsrf_secret()
    if xsrf:
        return xsrf
    return _browser_id_secret()


def _xsrf_secret() -> str:
    """從 Tornado 的 XSRF cookie 解出穩定的 raw token；拿不到回空字串。

    ⚠️ 那個 cookie 是 `2|<mask>|<masked token>|<timestamp>`，**每次送出都會換一組 mask**，
    所以不能直接拿 cookie 字串當祕密（值會變、比對必失敗）。要先解遮罩還原成底層
    raw token，那個才是穩定的（實測兩次載入都是 682ffabc…）。
    """
    try:
        raw = st.context.cookies.get("_streamlit_xsrf", "") or ""
    except Exception:
        return ""
    parts = raw.split("|")
    if len(parts) == 4 and parts[0] == "2":
        try:
            mask = binascii.a2b_hex(parts[1].encode())
            masked = binascii.a2b_hex(parts[2].encode())
            if mask:
                return bytes(b ^ mask[i % len(mask)] for i, b in enumerate(masked)).hex()
        except (binascii.Error, ValueError):
            pass
    return raw   # 格式變了就退回原字串——保護力較弱，但不會把登入弄壞


class _NoBrowserSecret(RuntimeError):
    """拿不到 _streamlit_xsrf cookie ＝ 無法把 state 綁到「這個瀏覽器」。"""


def _sign_state(nonce: str, issued_at: int) -> str:
    """⚠️ **空祕密一律拋錯，不要照樣簽下去。**

    這是本段最容易忽略的失效模式：`_browser_secret()` 取不到 cookie 時回空字串，
    而用空金鑰簽出來的 HMAC——攻擊者也簽得出一模一樣的。兩端都空時 `compare_digest`
    會回 True，於是 state 看起來驗過了，實際上完全沒有綁定效果＝等同沒有 state，
    授權碼注入（login CSRF）重新成立。而且整個過程**沒有任何錯誤訊息**。
    把它做成例外，是為了讓「用空金鑰簽章」在任何程式路徑上都不可能發生。
    """
    secret = _browser_secret()
    if not secret:
        raise _NoBrowserSecret()
    return hmac.new(
        secret.encode(), f"{issued_at}.{nonce}".encode(), hashlib.sha256
    ).hexdigest()


def _make_oauth_state() -> str:
    # token_urlsafe 只會產生 [A-Za-z0-9_-]，不含 "."，所以下面用 "." 切三段是安全的
    nonce = secrets.token_urlsafe(16)
    issued_at = int(time.time())
    return f"{issued_at}.{nonce}.{_sign_state(nonce, issued_at)}"


def _verify_oauth_state(state: str | None) -> bool:
    if not state:
        return False
    parts = state.split(".")
    if len(parts) != 3:
        return False
    ts_str, nonce, sig = parts
    try:
        issued_at = int(ts_str)
    except ValueError:
        return False
    # 未來時間也擋掉（時鐘漂移留 60 秒寬容）
    age = time.time() - issued_at
    if not -60 <= age <= _OAUTH_STATE_TTL:
        return False
    try:
        expected = _sign_state(nonce, issued_at)
    except _NoBrowserSecret:
        return False        # 驗不了就拒絕——fail closed，寧可讓使用者重登一次
    return hmac.compare_digest(sig, expected)


# ── Spotify 多用戶 OAuth ────────────────────────────────
def _get_auth_manager(state: str | None = None) -> SpotifyOAuth:
    """每次 call 都新建一個 OAuth manager，搭配 MemoryCacheHandler 確保多用戶獨立。

    state 只有「產生授權網址」時需要；換 token / refresh 時不必帶。
    """
    return SpotifyOAuth(
        client_id=_get_credential("SPOTIFY_CLIENT_ID"),
        client_secret=_get_credential("SPOTIFY_CLIENT_SECRET"),
        redirect_uri=_get_credential("SPOTIFY_REDIRECT_URI"),
        scope=SCOPES,
        state=state,
        cache_handler=MemoryCacheHandler(),  # 不寫 .cache 檔，避免多用戶污染
        open_browser=False,
        show_dialog=False,
    )


def get_login_url() -> str | None:
    """Spotify 授權網址（已帶上綁定本瀏覽器的 state）；**綁不了就回 None**。

    ⚠️ 回 None 時呼叫端要顯示錯誤、**不要**退而發一個沒帶 state 的網址——
    那正是這道防線要擋的攻擊（見 _sign_state 的說明）。寧可少一種登入方式
    （訪客模式仍可用），也不要提供一個沒有防護的登入。
    """
    try:
        state = _make_oauth_state()
    except _NoBrowserSecret:
        # 以前這裡是靜默降級：照樣發網址，但 state 沒有任何綁定效果。
        print("[AUTH] 拿不到 _streamlit_xsrf cookie；拒絕發出未綁定的授權網址",
              file=sys.stderr, flush=True)
        return None
    return _get_auth_manager(state=state).get_authorize_url()


# ⚠️ ?error= 是網址參數＝完全由攻擊者控制，**絕對不能原樣存起來再回顯**。
# 登入頁是用 st.warning(f"…（`{auth_err}`）…") 呈現的，Streamlit 的 alert 會渲染
# Markdown（雖然不允許 HTML）——payload 裡放一個反引號就跳出 code span，之後可以插入
# 任意 Markdown。在官方網域、官方樣式的警告框裡放一句「點此重新驗證你的 Spotify 帳號」
# 連到釣魚站，可信度極高；`![](https://evil/x.png)` 也能靜默外洩受害者 IP。
# 所以這裡改成白名單：認得的照原樣留（對排錯有用），不認得的一律收斂成 unknown_error。
_ALLOWED_OAUTH_ERRORS = frozenset({
    # Spotify / RFC 6749 會回的
    "access_denied", "invalid_client", "invalid_request", "invalid_scope",
    "unauthorized_client", "unsupported_response_type", "server_error",
    "temporarily_unavailable",
    # 本站自己產生的
    "state_mismatch", "token_exchange_failed", "browser_unverified", "unknown_error",
})


def _set_auth_error(code: str) -> None:
    st.session_state["spotify_auth_error"] = (
        code if code in _ALLOWED_OAUTH_ERRORS else "unknown_error"
    )


def consume_oauth_callback() -> None:
    """頁面載入時呼叫：處理 Spotify 導回的 ?code=xxx（交換 token）或 ?error=xxx（授權失敗）。

    失敗訊息寫入 st.session_state["spotify_auth_error"]，由登入頁決定呈現方式——
    不在這裡 st.error()，否則錯誤會出現在 hero 之前。
    ⚠️ 寫進去的一律是白名單內的錯誤代碼，不是使用者可控的原始字串（見上）。
    """
    if "spotify_token" in st.session_state:
        return

    def _clear_qp() -> None:
        try:
            st.query_params.clear()
        except Exception:
            pass

    err = st.query_params.get("error")
    if err:
        _set_auth_error(err)
        _clear_qp()
        return

    code = st.query_params.get("code")
    if not code:
        return

    # ⚠️ 綁定用的瀏覽器代號來自 localStorage 元件，**首輪 render 還沒回傳**。
    # 這時既不能驗（會把正常使用者誤判成攻擊），也**不能清掉 ?code=**——要原封不動
    # 留到元件 postback 觸發的下一輪。等太多輪還是沒有就放棄，避免無限等待。
    if browser_id_pending():
        n = st.session_state.get("oauth_wait_n", 0) + 1
        st.session_state["oauth_wait_n"] = n
        if n <= _OAUTH_WAIT_MAX:
            st.session_state["oauth_waiting"] = True
            return
        _set_auth_error("browser_unverified")
        _clear_qp()
        return
    st.session_state.pop("oauth_wait_n", None)

    # ⚠️ 一定要在換 token「之前」驗 state：驗不過就代表這個 code 不是這個瀏覽器
    # 自己發起的授權（多半是別人塞過來的），照換就等於把 session 綁到對方的帳號。
    if not _verify_oauth_state(st.query_params.get("state")):
        _set_auth_error("state_mismatch")
        _clear_qp()
        return

    try:
        token_info = _get_auth_manager().get_access_token(
            code, as_dict=True, check_cache=False
        )
        st.session_state["spotify_token"] = token_info
        st.session_state.pop("spotify_auth_error", None)
    except Exception:
        # ⚠️ 別把 str(e) 存進去——例外訊息含 Spotify 回傳的內容，同樣會被回顯到警告框
        _set_auth_error("token_exchange_failed")
    finally:
        # 清掉 URL 上的 code，避免重新整理時重複交換
        _clear_qp()


def is_authenticated() -> bool:
    return "spotify_token" in st.session_state

def _client_credentials() -> SpotifyClientCredentials | None:
    """App 層級（client-credentials）的 auth manager。

    ⚠️ 一定要自己帶 cache_handler：spotipy 沒收到時預設是 `CacheFileHandler()`，
    會把 token 寫進 CWD 的 `.cache` 檔——與「token 只存記憶體」的設計相違。
    ⚠️ 而且快取要**依 client id 分開**：BYOK 使用者填的是自己的 Client ID，
    共用一份快取（不論檔案或記憶體）會讓不同 app 的 token 互相污染。
    """
    cid = _get_credential("SPOTIFY_CLIENT_ID")
    csec = _get_credential("SPOTIFY_CLIENT_SECRET")
    if not cid or not csec:
        return None
    with _CC_CACHE_LOCK:
        handler = _CC_CACHES.setdefault(cid, MemoryCacheHandler())
    return SpotifyClientCredentials(
        client_id=cid, client_secret=csec, cache_handler=handler,
    )


def _get_guest_spotify_client() -> spotipy.Spotify | None:
    """Client-credentials flow for search without user login."""
    auth = _client_credentials()
    if auth is None:
        return None
    try:
        return _harden(spotipy.Spotify(auth_manager=auth))
    except Exception:
        return None

def get_spotify_client() -> spotipy.Spotify:
    """取得 Spotify client。呼叫前必須 is_authenticated() == True。Token 過期時自動 refresh。"""
    auth_manager = _get_auth_manager()
    token_info = st.session_state["spotify_token"]
    if auth_manager.is_token_expired(token_info):
        token_info = auth_manager.refresh_access_token(token_info["refresh_token"])
        st.session_state["spotify_token"] = token_info
    return _sp(token_info["access_token"])


def _fetch_profile_blocking(token: str) -> dict:
    """實際去 Spotify 抓聆聽資料。純函式——不碰 session_state，所以可以丟背景執行緒。

    抓 18 個 endpoint（3 個時間範圍 × top tracks/artists、最近播放、收藏 10 頁、
    追蹤中的歌手），彼此獨立所以全部並行。單一 endpoint 失敗（例如舊 token 沒有
    user-follow-read scope）只讓那一項變空，不影響其他資料。
    """
    # ⚠️ requests.Session 不是 thread-safe，每個 worker 用自己的 client（同 _search_tracks_parallel）
    tls = threading.local()
    failures: list[str] = []   # list.append 在 CPython 下是 thread-safe

    def _call(fn):
        client = getattr(tls, "sp", None)
        if client is None:
            client = _sp(token)
            tls.sp = client
        try:
            return fn(client) or []
        except Exception as e:
            failures.append(type(e).__name__)
            return []

    def _saved_page(c, off):
        return [i["track"] for i in c.current_user_saved_tracks(limit=50, offset=off)["items"]
                if i.get("track")]

    jobs = {}
    for tr in TIME_RANGES:
        jobs[f"tt_{tr}"] = lambda c, tr=tr: c.current_user_top_tracks(
            limit=TOP_FETCH_LIMIT, time_range=tr)["items"]
        jobs[f"ta_{tr}"] = lambda c, tr=tr: c.current_user_top_artists(
            limit=TOP_FETCH_LIMIT, time_range=tr)["items"]
    jobs["recent"] = lambda c: [
        i["track"] for i in c.current_user_recently_played(limit=50)["items"] if i.get("track")
    ]
    # 收藏先只抓第一頁——順便拿到 total，才知道真的需要幾頁。
    # 以前無條件送 10 個分頁請求，只收藏 20 首的人有 9 個請求是白打的（共用同一組
    # Client ID 的 rate limit，撞到 429 會讓整個 profile 變空）。
    jobs["saved_head"] = lambda c: c.current_user_saved_tracks(limit=50, offset=0)
    jobs["followed"] = lambda c: c.current_user_followed_artists(limit=50)["artists"]["items"]

    with ThreadPoolExecutor(max_workers=PROFILE_WORKERS) as ex:
        futures = {k: ex.submit(_call, fn) for k, fn in jobs.items()}
        res = {k: f.result() for k, f in futures.items()}

    head = res["saved_head"] if isinstance(res["saved_head"], dict) else {}
    saved = [i["track"] for i in (head.get("items") or []) if i.get("track")]
    offsets = list(range(50, min(head.get("total") or 0, SAVED_FETCH_MAX), 50))
    if offsets:
        with ThreadPoolExecutor(max_workers=PROFILE_WORKERS) as ex:
            for page in ex.map(lambda off: _call(lambda c, off=off: _saved_page(c, off)), offsets):
                saved.extend(page)

    top_tracks = {tr: res[f"tt_{tr}"] for tr in TIME_RANGES}
    top_artists = {tr: res[f"ta_{tr}"] for tr in TIME_RANGES}
    all_tracks = [t for v in top_tracks.values() for t in v] + res["recent"] + saved
    all_artists = [a for v in top_artists.values() for a in v] + res["followed"]

    def track_str(t):
        return f"{t['name']} - {', '.join(a['name'] for a in t.get('artists', []))}"

    def uniq(seq):
        return list(dict.fromkeys(x for x in seq if x))

    # 「已知宇宙」：程式端比對用的完整集合。歌手用 ID 為主鍵——名稱有太多變體
    #（IU / 아이유、五月天 / Mayday），ID 比對不會漏。
    known_artist_ids = {a["id"] for a in all_artists if a.get("id")}
    known_artist_names = {a["name"] for a in all_artists if a.get("name")}
    for t in all_tracks:
        for a in t.get("artists", []):
            if a.get("id"):
                known_artist_ids.add(a["id"])
            if a.get("name"):
                known_artist_names.add(a["name"])

    known_track_keys = {
        _track_key_from(t["name"], t["artists"][0]["name"])
        for t in all_tracks if t.get("name") and t.get("artists")
    }

    # prompt 用的樣本：清單太長 LLM 反而不遵守（文獻：50 條內較穩、200+ 明顯衰退），
    # 而且長 context 中段的資訊利用率最低。真正的排除保證在程式端，這裡只求少浪費候選。
    prompt_artists = uniq(
        [a["name"] for tr in ("medium_term", "short_term", "long_term") for a in top_artists[tr]]
    )
    prompt_titles = uniq([t["name"] for t in top_tracks["short_term"] + top_tracks["medium_term"]]
                         + [t["name"] for t in res["recent"]])

    return {
        "top_tracks_recent":  [track_str(t) for t in top_tracks["short_term"][:10]],
        "top_tracks_overall": [track_str(t) for t in top_tracks["medium_term"][:20]],
        "top_artists":  prompt_artists[:20],
        "top_genres":   list({g for a in all_artists for g in a.get("genres", [])}),
        "heard_titles":  prompt_titles[:PROMPT_HEARD_TITLES_MAX],
        "heard_artists": prompt_artists[:PROMPT_EXCLUDE_ARTISTS_MAX],
        "known_artist_ids":   known_artist_ids,
        "known_artist_names": known_artist_names,
        "known_track_keys":   known_track_keys,
        "known_stats": {
            "tracks": len(known_track_keys),
            "artists": len(known_artist_ids),
            "saved": len(saved),
            "followed": len(res["followed"]),
            # Spotify 已從 artist 物件拿掉 genres（client credentials 實測）。若用登入
            # token 也拿不到，這裡會是 0，prompt 的「風格」就退回寫死的 "pop, indie pop"——
            # 推薦會變得很泛而且看不出原因，所以要能一眼從 log 看到。
            "genres": len({g for a in all_artists for g in a.get("genres", [])}),
            # 全部 endpoint 都失敗時 profile 會是空的，出圈過濾等於整條失效——
            # 這個數字要一路帶到 [NOVELTY] log 與 UI 警告，不能默默降級
            "failed_calls": len(failures),
        },
    }


def start_profile_prefetch() -> None:
    """登入後頁面一載入就在背景抓聆聽資料（18 個 endpoint，並行後約 1–1.5 秒）。

    比照 start_geo_prefetch()：token 必須在主執行緒讀（worker 不能碰 session_state），
    使用者填完情境按下生成時通常已經好了。
    """
    if not is_authenticated():
        return
    if "user_profile_future" in st.session_state:
        return
    if any(k.startswith("user_profile::") for k in st.session_state):
        return
    token = _get_search_token()   # 會順便觸發必要的 token refresh
    if not token:
        return
    st.session_state["user_profile_future"] = _PROFILE_POOL.submit(_fetch_profile_blocking, token)


def fetch_user_profile() -> dict:
    """讀使用者聆聽資料；以 user_id 為 key 快取在 session_state（per-user safe）。"""
    sp = get_spotify_client()
    user = sp.current_user()
    # v2：改版後多了 known_* 三個集合，舊快取沒有這些鍵，換 key 強制重抓
    cache_key = f"user_profile::v2::{user['id']}"
    if cache_key in st.session_state:
        return st.session_state[cache_key]

    token = st.session_state["spotify_token"]["access_token"]
    future = st.session_state.pop("user_profile_future", None)
    try:
        profile = future.result(timeout=30) if future is not None else _fetch_profile_blocking(token)
    except Exception:
        profile = _fetch_profile_blocking(token)

    st.session_state[cache_key] = profile
    return profile


def create_playlist_with_tracks(
    playlist_name: str, track_uris: list[str], description: str | None = None,
) -> dict:
    """建立新歌單並加入曲目，回傳歌單資訊。

    description 給了就用（例如 Gemini 生成的情境詩意敘述，讓歌單少一點 AI 味）；
    沒給才退回「自動生成・時間戳」的預設。
    """
    sp = get_spotify_client()
    _desc = (description or "").strip() or \
        f"由 SoundCurator 自動生成・{_local_now().strftime('%Y-%m-%d %H:%M')}"
    _desc = _desc[:300]  # Spotify 歌單敘述上限約 300 字，超過會被拒/截斷
    # 新 endpoint：POST /me/playlists（舊的 /users/{id}/playlists 已被移除）
    playlist = sp._post(
        "me/playlists",
        payload={
            "name": playlist_name,
            "public": False,
            "description": _desc,
        },
    )
    # 新 endpoint：POST /playlists/{id}/items（舊的 /tracks 已被改名）
    for i in range(0, len(track_uris), 100):
        sp._post(
            f"playlists/{playlist['id']}/items",
            payload={"uris": track_uris[i:i + 100]},
        )
    return playlist


def search_track(title: str, artist: str, sp: spotipy.Spotify | None = None) -> dict | None:
    """在 Spotify 找出 LLM 推薦的那首歌。找不到、或找到的明顯是別首歌，一律回 None。

    結果會快取（跨使用者共用）——LLM 的推薦高度重複，同一首歌會被不同使用者、
    不同批次一再搜尋，而**所有人共用同一組 Client ID 的配額**，重複搜尋是最沒必要的浪費。
    """
    key = _track_key(title, artist)
    with _SEARCH_CACHE_LOCK:
        if key in _SEARCH_CACHE:
            _SEARCH_STATS["hits"] += 1
            hit = _SEARCH_CACHE[key]
            # ⚠️ 一定要回複本：呼叫端會往裡面塞 reason / fame / _discovery，
            # 直接回同一個 dict 的話快取內容會被前一次生成的資料污染
            return dict(hit) if hit is not None else None
        _SEARCH_STATS["misses"] += 1

    if sp is None:
        sp = get_spotify_client() if is_authenticated() else _get_guest_spotify_client()
    if sp is None:
        return None
    results = sp.search(q=f"track:{title} artist:{artist}", type="track", limit=1)
    items = results["tracks"]["items"]
    if not items:
        # 模糊搜尋常撈到「同一位藝人的另一首熱門歌」，照收就等於推了一首八成聽過的歌。
        # 多取幾筆並逐一驗證，挑第一個真的對得上的。
        # ⚠️ Spotify 的搜尋結果偶爾夾帶 null，沒擋的話一顆 TypeError 會讓整首降級成搜尋卡
        loose = sp.search(q=f"{title} {artist}", type="track", limit=5)["tracks"]["items"]
        items = [
            it for it in loose
            if it and it.get("name") and it.get("artists")
            and resolution_matches(title, artist, it["name"], [a["name"] for a in it["artists"]])
        ]
    if not items:
        return _cache_search(key, None)
    t = items[0]
    images = t["album"].get("images") or []
    return _cache_search(key, {
        "name": t["name"],
        "artist": ", ".join(a["name"] for a in t["artists"]),
        "album": t["album"]["name"],
        "url": t["external_urls"]["spotify"],
        "uri": t["uri"],
        "cover": images[1]["url"] if len(images) > 1 else (images[0]["url"] if images else ""),
        # 以下三個給 recommend.curate_tracks() 的驗證鏈用
        "popularity": t.get("popularity"),
        "artist_ids": [a["id"] for a in t["artists"] if a.get("id")],
        "artist_names": [a["name"] for a in t["artists"]],
    })


def _get_search_token() -> str | None:
    """取得可供搜尋用的 access token。必須在主執行緒呼叫（會碰 session_state）。"""
    if is_authenticated():
        get_spotify_client()  # 觸發必要的 token refresh
        return st.session_state["spotify_token"]["access_token"]
    auth = _client_credentials()
    if auth is None:
        return None
    try:
        return auth.get_access_token(as_dict=False)
    except Exception:
        return None


def _search_tracks_parallel(
    recs: list[dict], token: str, max_workers: int = 8
) -> tuple[list[dict | None], bool]:
    """並行搜尋 Spotify，保持輸入順序。單首失敗視為找不到（回 None），不中斷整批。
    每個 worker thread 用自己的 Spotify client（requests.Session 非 thread-safe）。

    回傳 (結果, 是否撞到速率限制)。撞到 429 時每首都會「找不到」，整份清單會變成
    一堆搜尋連結卡——那要明確告訴使用者，而不是讓它看起來像 AI 推了一堆不存在的歌。
    """
    tls = threading.local()
    rate_limited = threading.Event()

    def _worker(rec: dict) -> dict | None:
        sp = getattr(tls, "sp", None)
        if sp is None:
            sp = _sp(token)
            tls.sp = sp
        if rate_limited.is_set():
            return None      # 已經撞牆就別再打，免得罰得更久
        try:
            return search_track(rec["title"], rec["artist"], sp=sp)
        except spotipy.SpotifyException as e:
            if e.http_status == 429:
                rate_limited.set()
            return None
        except Exception:
            return None

    with ThreadPoolExecutor(max_workers=min(max_workers, max(1, len(recs)))) as ex:
        return list(ex.map(_worker, recs)), rate_limited.is_set()


# ── 幻覺補救：同歌手換一首真歌 ─────────────────────────────
# 實測的幻覺模式是「歌手真實存在、歌名是編的」（Bathe Alone《Your Dog》其實是
# Soccer Mommy 的歌）——LLM 選的**方向**是對的，錯的只有曲名。所以搜不到時不必
# 放棄整張卡：找到那位歌手，從他的專輯目錄挑一首真實存在的深軌替換，
# 推薦意圖（相鄰探索的橋接理由）大多仍然成立。
# 成本：每位歌手 3–4 個請求（搜歌手 → 專輯清單 → 至多兩張專輯的曲目），
# 每批上限 REPAIR_MAX_PER_BATCH；目錄跨使用者快取（歌手目錄變動很慢，不設 TTL，
# 幻覺歌手會被反覆提名——同歌手第二次補救零請求）。
REPAIR_MAX_PER_BATCH = 5    # 每批最多補救幾首：成本上限 5 × 4 = 20 個請求
REPAIR_ALBUM_FETCHES = 2    # 每位歌手最多抓幾張專輯的曲目
FAV_POOL_PER_ARTIST = 8     # 指定歌手保底：每位點名歌手最多預抓幾首真實深軌當候選
                            # （夠填「至少一半」的保底、又不狂打共用配額；重用同一份目錄快取）
_REPAIR_CACHE: dict[str, list[dict] | None] = {}  # _norm_artist(名) → 候選卡（None=找不到）
_REPAIR_CACHE_LOCK = threading.Lock()
_REPAIR_STATS = {"hits": 0, "misses": 0}


def repair_cache_info() -> dict:
    with _REPAIR_CACHE_LOCK:
        return {"size": len(_REPAIR_CACHE), **_REPAIR_STATS}


def _artist_catalog(
    artist: str, sp: spotipy.Spotify | None = None, allow_top_result: bool = False
) -> list[dict] | None:
    """這位歌手的候選曲目卡清單（取自至多 REPAIR_ALBUM_FETCHES 張非合輯專輯）。

    跨使用者快取；「歌手找不到」也快取成 None。429 會往上拋（呼叫端要停止
    整批補救），跟搜尋快取同一條原則：限流造成的失敗不寫進快取。

    `allow_top_result`：嚴格名稱比對失敗時，退而採用搜尋結果第一筆（最相關）。
    只給「指定歌手保底」用——搜尋字串就是使用者親手打的藝名，第一筆幾乎必然是本尊；
    最常見的情境是 CJK 藝名在 Spotify 存成羅馬拼音（「陳綺貞」→"Cheer Chen"），
    嚴格比對跨文字系統對不上。⚠️ 幻覺補救**不能**開這個——LLM 給的歌手名不可信，
    退而取第一筆會補到別的歌手，比不補更糟。兩種模式的結果分開快取避免互相污染。
    """
    key = _norm_artist(artist)
    if not key:
        return None
    cache_key = key + "\x00top" if allow_top_result else key
    with _REPAIR_CACHE_LOCK:
        if cache_key in _REPAIR_CACHE:
            _REPAIR_STATS["hits"] += 1
            hit = _REPAIR_CACHE[cache_key]
            # 回複本：呼叫端會塞 reason / fame / _repaired，不能污染快取
            return [dict(t) for t in hit] if hit is not None else None
        _REPAIR_STATS["misses"] += 1

    if sp is None:
        sp = get_spotify_client() if is_authenticated() else _get_guest_spotify_client()
    if sp is None:
        return None

    # 找歌手實體。驗證名稱對得上才收——補救到「別的歌手」比不補救糟糕得多
    found = sp.search(q=artist, type="artist", limit=5)["artists"]["items"]
    match = None
    for a in found:
        if a and a.get("name") and (
            _norm_artist(a["name"]) == key or _loose_match(artist, a["name"])
        ):
            match = a
            break
    if match is None and allow_top_result:
        match = next((a for a in found if a and a.get("id")), None)
    if match is None:
        with _REPAIR_CACHE_LOCK:
            _REPAIR_CACHE[cache_key] = None
        return None

    # ⚠️ artist_albums 的 limit 上限實測只剩 10（2026-08：20 與 50 都回 400
    # 「Invalid limit」，10 通過——Spotify 又把上限調低了，文件沒跟上）
    albums = [
        al for al in sp.artist_albums(match["id"], include_groups="album", limit=10)["items"]
        if al and al.get("album_type") != "compilation"
    ]
    if not albums:  # 只發過單曲的獨立音樂人不少，退一步收單曲
        albums = [al for al in
                  sp.artist_albums(match["id"], include_groups="single", limit=10)["items"] if al]
    # 專輯清單是最新在前；從中段開始試——太新的可能剛發還沒沉澱，最舊的資料常不齊
    order = albums[len(albums) // 2:] + albums[:len(albums) // 2]
    cards: list[dict] = []
    for al in order[:REPAIR_ALBUM_FETCHES]:
        images = al.get("images") or []
        cover = images[1]["url"] if len(images) > 1 else (images[0]["url"] if images else "")
        tracks = [t for t in sp.album_tracks(al["id"], limit=20)["items"]
                  if t and t.get("name") and t.get("artists")]
        # 避開第 1 軌（通常是主打單曲），從中段排起——「非合輯專輯的中段曲目」深軌啟發式
        mid = len(tracks) // 2
        for t in tracks[mid:] + tracks[1:mid]:
            cards.append({
                "name": t["name"],
                "artist": ", ".join(a["name"] for a in t["artists"]),
                "album": al.get("name", ""),
                "url": (t.get("external_urls") or {}).get("spotify", ""),
                "uri": t.get("uri"),
                "cover": cover,
                "popularity": None,
                "artist_ids": [a["id"] for a in t["artists"] if a.get("id")],
                "artist_names": [a["name"] for a in t["artists"]],
            })
    with _REPAIR_CACHE_LOCK:
        _REPAIR_CACHE[cache_key] = [dict(t) for t in cards]
    return cards


def repair_hallucinated_track(
    title: str,
    artist: str,
    exclude_keys: set[tuple[str, str]],
    sp: spotipy.Spotify | None = None,
) -> dict | None:
    """搜不到的候選（幻覺）→ 同一位歌手真實存在的深軌，挑不到回 None（維持搜尋卡）。

    exclude_keys 是呼叫端「已經出現過」的 (正規化歌名, 歌手) 集合——歷史、
    已聽過的曲目、本批其他卡都要在內，否則補救會補出重複。
    title 目前只用於語意（幻覺的曲名沒有比對價值），保留參數是為了未來
    想做「挑最像原意圖的曲目」時不用改簽名。
    """
    catalog = _artist_catalog(artist, sp)
    if not catalog:
        return None
    for t in catalog:
        key = _track_key_from(t["name"], (t.get("artist_names") or [""])[0])
        if key in exclude_keys:
            continue
        return dict(t, _repaired=True)
    return None


def fav_artist_pool(
    fav_artists: list[str],
    exclude_keys: set[tuple[str, str]] | None = None,
    sp: spotipy.Spotify | None = None,
) -> list[dict]:
    """指定歌手保底用的候選池：每位點名歌手在 Spotify 上真實存在的深軌卡清單。

    重用 `_artist_catalog`（跨使用者快取、零幻覺），每首卡標上 `_fav_artist=<名>`
    讓 curate 的保底邏輯能跨文字系統辨識（「落日飛車」抓回來主藝名可能是
    "Sunset Rollercoaster"）。每位歌手至多取 FAV_POOL_PER_ARTIST 首。

    `exclude_keys`：已在歷史／已聽過／本批出現的 (正規化歌名, 歌手)，先濾掉避免補出重複。
    ⚠️ 撞 429 時 `_artist_catalog` 會往上拋 SpotifyException——呼叫端要接住並停止
    整批保底（跟幻覺補救同一態度：限流時別再打）。
    """
    exclude_keys = exclude_keys or set()
    out: list[dict] = []
    for name in fav_artists or []:
        # allow_top_result：使用者親手打的藝名，CJK 藝名常在 Spotify 存成羅馬拼音
        catalog = _artist_catalog(name, sp, allow_top_result=True)   # 撞 429 會往上拋
        if not catalog:
            continue
        taken = 0
        for t in catalog:
            key = _track_key_from(t["name"], (t.get("artist_names") or [""])[0])
            if key in exclude_keys:
                continue
            out.append(dict(t, _fav_artist=name))
            taken += 1
            if taken >= FAV_POOL_PER_ARTIST:
                break
    return out


# ── 跨 session 歷史（持久化在 Spotify 私人歌單） ────────────
def _has_scope(scope_name: str) -> bool:
    """檢查目前 token 是否含某個 scope。"""
    token = st.session_state.get("spotify_token") or {}
    return scope_name in (token.get("scope") or "")


def _playlist_replace_items(sp: spotipy.Spotify, pid: str, uris: list[str]) -> None:
    """整批取代歌單內容（一次最多 100 首）。新 endpoint PUT /items，失敗 fallback 舊 /tracks。"""
    try:
        sp._put(f"playlists/{pid}/items", payload={"uris": uris})
    except Exception:
        sp._put(f"playlists/{pid}/tracks", payload={"uris": uris})


def _trim_persistent_history(sp: spotipy.Spotify, pid: str) -> None:
    """歌單超過 PERSISTENT_HISTORY_MAX 首時只保留最新的部分，避免無限成長拖慢載入。"""
    uris: list[str] = []
    results = sp.playlist_items(pid, fields="items(track(uri)),next", limit=100)
    while results:
        for it in results["items"]:
            uri = (it.get("track") or {}).get("uri")
            if uri:
                uris.append(uri)
        if results.get("next"):
            results = sp.next(results)
        else:
            break
    if len(uris) <= PERSISTENT_HISTORY_MAX:
        return
    keep = uris[-PERSISTENT_HISTORY_MAX:]
    _playlist_replace_items(sp, pid, keep[:100])
    for i in range(100, len(keep), 100):
        sp._post(f"playlists/{pid}/items", payload={"uris": keep[i:i + 100]})


def _get_history_playlist_id() -> str | None:
    """找出（或建立）這位使用者的自動管理歷史歌單，回傳 playlist id。
    若使用者尚未授權 playlist-read-private，回傳 None（避免重複建立歌單）。
    """
    if not _has_scope("playlist-read-private"):
        return None
    sp = get_spotify_client()
    cache_key = "history_playlist_id"
    if cache_key in st.session_state:
        return st.session_state[cache_key]

    user_id = sp.current_user()["id"]
    results = sp.current_user_playlists(limit=50)
    while results:
        for pl in results["items"]:
            if pl and pl.get("name") == HISTORY_PLAYLIST_NAME and pl["owner"]["id"] == user_id:
                st.session_state[cache_key] = pl["id"]
                return pl["id"]
        if results.get("next"):
            results = sp.next(results)
        else:
            break

    new_pl = sp._post(
        "me/playlists",
        payload={
            "name": HISTORY_PLAYLIST_NAME,
            "public": False,
            "description": "SoundCurator 自動管理：記錄推薦過的歌曲以避免重複。可以在 App 內按「清除歷史」清空。",
        },
    )
    st.session_state[cache_key] = new_pl["id"]
    return new_pl["id"]


def load_persistent_history() -> list[dict]:
    """讀取持久化歷史，回傳 [{title, artist}, ...]；失敗回空 list。"""
    try:
        pid = _get_history_playlist_id()
    except Exception:
        return []
    if not pid:
        return []

    cache_key = f"persistent_history::{pid}"
    if cache_key in st.session_state:
        return st.session_state[cache_key]

    sp = get_spotify_client()
    items: list[dict] = []
    try:
        results = sp.playlist_items(pid, fields="items(track(name,artists(name))),next", limit=100)
        while results:
            for it in results["items"]:
                track = it.get("track") or {}
                name = track.get("name")
                if not name:
                    continue
                items.append({
                    "title": name,
                    "artist": ", ".join(a["name"] for a in track.get("artists", []) if a.get("name")),
                })
            if results.get("next"):
                results = sp.next(results)
            else:
                break
    except Exception:
        return []

    st.session_state[cache_key] = items
    return items


def append_to_persistent_history(tracks: list[dict]) -> None:
    """把新推薦的曲目 append 到歷史歌單。失敗時靜默忽略。"""
    try:
        pid = _get_history_playlist_id()
    except Exception:
        return
    if not pid:
        return
    sp = get_spotify_client()
    uris = [t["uri"] for t in tracks if t.get("uri")]
    if not uris:
        return
    try:
        for i in range(0, len(uris), 100):
            sp._post(f"playlists/{pid}/items", payload={"uris": uris[i:i+100]})
    except Exception:
        return
    cache_key = f"persistent_history::{pid}"
    if cache_key in st.session_state:
        for t in tracks:
            st.session_state[cache_key].append({
                "title": t.get("name", ""),
                "artist": t.get("artist", ""),
            })
        # 超過上限時修剪歌單，只保留最新 PERSISTENT_HISTORY_MAX 首（best-effort）
        if len(st.session_state[cache_key]) > PERSISTENT_HISTORY_MAX:
            try:
                _trim_persistent_history(sp, pid)
                st.session_state[cache_key] = st.session_state[cache_key][-PERSISTENT_HISTORY_MAX:]
            except Exception:
                pass


def clear_persistent_history() -> int:
    """清空歷史歌單裡的所有曲目，回傳清掉的數量。"""
    try:
        pid = _get_history_playlist_id()
    except Exception:
        return 0
    if not pid:
        return 0
    sp = get_spotify_client()
    all_uris: list[str] = []
    try:
        results = sp.playlist_items(pid, fields="items(track(uri)),next", limit=100)
        while results:
            for it in results["items"]:
                uri = (it.get("track") or {}).get("uri")
                if uri:
                    all_uris.append(uri)
            if results.get("next"):
                results = sp.next(results)
            else:
                break
    except Exception:
        return 0
    if not all_uris:
        return 0
    # 用「整批取代為空」清空歌單
    _playlist_replace_items(sp, pid, [])
    cache_key = f"persistent_history::{pid}"
    if cache_key in st.session_state:
        st.session_state[cache_key] = []
    return len(all_uris)


