"""
SoundCurator - Web UI
"""

import ipaddress
import os
import random
import re
import secrets
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote

import requests
import streamlit as st
import streamlit.components.v1 as components
from dotenv import load_dotenv
import spotipy
import ratelimit
import styles
import db
import share_card

from recommend import (
    GUEST_OVERGEN_FACTOR,
    HISTORY_KEEP,
    OVERGEN_FACTOR,
    PLAY_PLATFORMS,
    REFILL_MAX,
    _history_keys,
    _track_key,
    _track_key_from,
    analyze_image,
    curate_tracks,
    get_recommendations,
    play_link,
)
from spotify_api import (
    REPAIR_MAX_PER_BATCH,
    _browser_secret,
    _get_credential,
    _get_env,
    _get_search_token,
    _has_scope,
    _local_now,
    _search_tracks_parallel,
    _sp,
    repair_cache_info,
    repair_hallucinated_track,
    append_to_persistent_history,
    clear_persistent_history,
    browser_id_pending,
    consume_oauth_callback,
    create_playlist_with_tracks,
    fav_artist_pool,
    fetch_user_profile,
    get_login_url,
    get_spotify_client,
    is_authenticated,
    load_persistent_history,
    search_cache_info,
    start_profile_prefetch,
)

load_dotenv()


# ── 訪客 per-browser 身分（Phase 5）──────────────────────────
# 自建 localStorage 元件：讀/生成瀏覽器端匿名 UUID 並回傳。見 FEEDBACK_PERSISTENCE.md「Phase 5」。
_GUEST_ID_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "guest_id_component")
_guest_id_component = components.declare_component("sc_guest_id", path=_GUEST_ID_DIR)


# 合法的訪客匿名代號＝ crypto.randomUUID() 的正規形式（小寫 v4）。
# ⚠️ 這個值**完全由瀏覽器端控制**（localStorage 可以任意改），是本站少數幾個
#    跨越信任邊界的輸入之一，所以進到伺服器一定要驗：
#    ① 形式不對就當作沒有 id——不要拿去 HMAC，那等於讓人自訂身分命名空間；
#    ② 正規形式順帶把長度鎖死在 36 字元，擋掉「塞超長字串、每次 render 都往伺服器送」；
#    ③ 只收小寫：大小寫都收的話，同一個邏輯 id 會算出兩把不同的 user_key。
# 元件端（guest_id_component/index.html）也用同一條規則做自我修復，但那只是體驗，
# **這裡才是真正的信任邊界**——攻擊者可以完全繞過我們的 JS。
_GUEST_ID_RE = re.compile(
    r"\A[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z"
)


# 元件說「這個瀏覽器給不了代號」的哨符（無痕／localStorage 被擋／沒有 CSPRNG）。
# ⚠️ 一定要跟「首輪還沒回傳」（None）分開：前者是終局、可以直接判失敗，
#    後者只是還沒好、必須再等一輪。OAuth 綁定就靠這個差別決定要等還是要放棄。
_BROWSER_ID_UNAVAILABLE = "unavailable"


def _resolve_browser_id() -> None:
    """渲染隱形元件、把瀏覽器代號寫進 `st.session_state["browser_id"]`。

    ⚠️ **一次 script run 只能呼叫一次**——同一個 widget key 渲染兩次會 DuplicateWidgetID。
    所以只在頁面最上方呼叫，其他地方一律讀 `_browser_id()`。
    ⚠️ 必須在 `consume_oauth_callback()` **之前**：OAuth state 的綁定要靠這個代號
    （Streamlit Cloud 的 websocket 標頭沒有 Cookie，拿不到 XSRF token，見 spotify_api._browser_secret）。
    ⚠️ 回傳是非同步的：首輪 render 回 None，元件 postback 觸發 rerun 後才有值。
    """
    try:
        # key＝讓 styles 用 .st-key-guest_id_probe 把它移出版面流（隱形、零 footprint）
        raw = _guest_id_component(default=None, key="guest_id_probe")
    except Exception:
        st.session_state["browser_id"] = _BROWSER_ID_UNAVAILABLE
        return
    if raw is None:
        return                                   # 首輪還沒回傳，保留既有值（若有）
    if not isinstance(raw, str) or (
        raw != _BROWSER_ID_UNAVAILABLE and not _GUEST_ID_RE.match(raw)
    ):
        raw = _BROWSER_ID_UNAVAILABLE            # 形式不對＝被竄改，當作拿不到
    st.session_state["browser_id"] = raw


def _browser_id() -> str | None:
    """已解析的瀏覽器代號：合格 UUID ／ `_BROWSER_ID_UNAVAILABLE` ／ None（還沒好）。"""
    return st.session_state.get("browser_id")


def _guest_local_id() -> str | None:
    """訪客身分用的匿名 UUID；還沒好／拿不到／形式不合法 → None。"""
    bid = _browser_id()
    if not isinstance(bid, str) or not _GUEST_ID_RE.match(bid):
        return None      # 含 None、_BROWSER_ID_UNAVAILABLE 與任何被竄改過的值
    return bid


def _ensure_guest_uk() -> None:
    """訪客模式下解析 per-browser 假名鍵、快取進 `st.session_state["guest_uk"]`。

    非訪客／DB 未啟用 → no-op。讀不到 id（無痕／尚未回傳）→ **不設 guest_uk**，
    呼叫端據此降級成 session 級——**絕不退回固定字串**（否則全體訪客共用一個 key、互相污染）。
    """
    if not is_guest_mode() or not db.is_enabled():
        return
    if st.session_state.get("guest_uk"):
        return
    lid = _guest_local_id()
    if not lid:
        return
    try:
        uk = db.guest_user_key(lid, db.hmac_secret())
    except Exception:
        return
    st.session_state["guest_uk"] = uk
    print(f"[GUEST] per-browser key resolved: {uk[:8]}…", file=sys.stderr)  # 驗收用，非可逆雜湊前綴


def _rate_key() -> str:
    """生成節流的桶子鍵：盡量對應「這個瀏覽器」。

    優先用 _browser_secret()（取自 Streamlit 的 XSRF cookie）——它撐得過整頁重新載入，
    所以重新整理不會把額度洗掉。
    ⚠️ 取不到 cookie 時**不能**退回固定字串，那會把所有這類使用者算成同一個人、
    互相把對方鎖死。改用 per-session 隨機 id：撐不過重載（節流會被繞過），
    但至少不會誤傷別人。
    """
    secret = _browser_secret()
    if secret:
        return f"b:{secret}"
    if "rl_session_id" not in st.session_state:
        st.session_state["rl_session_id"] = secrets.token_hex(8)
    return f"s:{st.session_state['rl_session_id']}"


def _human_wait(sec: int) -> str:
    """秒數 → 人看得懂的粗略時間。全站閘門的等待可能長達數小時，
    照秒印會變成「請等 41231 秒」這種讓人以為壞掉的訊息。"""
    if sec < 90:
        return f"{sec} 秒"
    if sec < 3600:
        return f"約 {round(sec / 60)} 分鐘"
    return f"約 {round(sec / 3600)} 小時"


def _rate_limit_warning(why: str, wait: int) -> str:
    """被節流擋下時給使用者的說明。四種原因要講不同的話——「今天用完了」和
    「現在人多」對使用者的下一步完全不同（一個是明天再來，一個是等幾分鐘）。"""
    if why == "global_day":
        return "今天全站的 AI 額度已經用完了（所有使用者共用同一份免費配額），明天會逐步恢復。"
    if why == "global_hour":
        return f"現在同時使用的人比較多，{_human_wait(wait)}後會有名額釋出，請稍後再試。"
    if why == "daily":
        return "今日的生成次數已用完，額度會在 24 小時內逐步恢復。"
    return f"生成太頻繁了，請等 {wait} 秒再試。"


def _gemini_key() -> str | None:
    """本站自備的 Gemini API Key。

    只讀 .env / Streamlit Secrets——使用者不需要（也無法）自行填入，
    所以刻意用 _get_env() 而非 _get_credential()。
    """
    return _get_env("GEMINI_API_KEY")


MBTI_TYPES = [
    "不指定",
    "INTJ", "INTP", "ENTJ", "ENTP",
    "INFJ", "INFP", "ENFJ", "ENFP",
    "ISTJ", "ISFJ", "ESTJ", "ESFJ",
    "ISTP", "ISFP", "ESTP", "ESFP",
]

BLOOD_TYPE_OPTIONS = ["不指定", "A 型", "B 型", "AB 型", "O 型"]

ZODIAC_OPTIONS = [
    "不指定",
    "牡羊座", "金牛座", "雙子座", "巨蟹座",
    "獅子座", "處女座", "天秤座", "天蠍座",
    "射手座", "摩羯座", "水瓶座", "雙魚座",
]

LANGUAGE_OPTIONS = [
    "華語", "英語", "日語", "韓語", "粵語",
    "西語", "法語", "其他語言",
]

GENRE_OPTIONS = [
    "Pop", "Rock", "Indie", "Folk", "R&B / Soul",
    "Hip-Hop / Rap", "Jazz", "Classical", "Electronic / EDM",
    "Country", "Metal", "Punk", "Alternative", "Blues",
    "K-Pop", "J-Pop", "C-Pop", "Lo-Fi", "Ambient", "OST / 配樂",
]

# MAX_TRACKS_PER_ARTIST / HISTORY_KEEP 在 recommend.py；PERSISTENT_HISTORY_MAX 在 spotify_api.py
AUTO_CONTEXT_TTL = 600      # 位置/天氣快取秒數（10 分鐘）

# 題目不再帶 emoji——圖示統一用 styles.SVG_QUESTION 題目氣泡（2026-08-21 圖示系統定案）
PROJECTIVE_QUESTIONS = [
    "你手機現在的桌布是什麼？",
    "你相簿中最新一張照片裡有什麼？",
    "你剛剛 LINE / 訊息最後傳了什麼？",
    "最近一次 Google 搜尋了什麼？",
    "最近讓你印象最深的一個畫面（電影/影集/現實）是？",
    "你現在桌上有什麼東西？",
    "上次讓你笑出聲的東西是？",
    "最近腦中一直循環的一句話或歌詞？",
    "昨晚的夢（如果記得）是什麼？",
    "最近在看的書/影集/YouTube 是？",
    "你今天穿什麼顏色的衣服？",
    "你窗外現在看到什麼？",
    "你今天最想吃什麼？",
    "你最近一次發呆是在想什麼？",
    "如果現在出門你會帶什麼？",
    # ── 2026-08 擴充 15 → 30：跨 session 的第一題是隨機抽的，15 題的池子
    #    生日效應很兇（開 5 次頁面約五成機率撞題），加倍直接砍半 ──
    "通勤或移動時你通常在做什麼？",
    "最近買的一樣東西是什麼？",
    "你今天是被什麼叫醒的？",
    "上一次散步是在哪裡？",
    "睡前最後滑的是什麼？",
    "用一種天氣形容今天的自己？",
    "你房間最亂的角落現在堆著什麼？",
    "最近一次吃到「就是這個！」的東西是？",
    "這週你最期待的一件事是？",
    "如果現在收到一個禮物，你希望是什麼？",
    "你最近重看／重玩／重聽了什麼？",
    "你最喜歡的氣味是什麼？（雨後/咖啡/香水…）",
    "理想的週末下午你會怎麼過？",
    "如果現在拍一張照，你會拍什麼？",
    "現在最想逃去哪裡？",
]


def _rotate_projective(order: list[str], current: str | None) -> tuple[str, list[str]]:
    """投射問題的洗牌輪替：回傳 (下一題, 剩餘順序)。

    「換一題」不能用 random.choice——它只排除當前題，session 內連按幾次
    就會看到舊題回鍋。改成整輪洗牌：30 題全部出完才重洗；重洗後的第一題
    有 1/N 機率剛好是上一輪的最後一題，把它移到隊尾避免連兩題相同。
    """
    if not order:
        order = random.sample(PROJECTIVE_QUESTIONS, len(PROJECTIVE_QUESTIONS))
        if len(order) > 1 and order[0] == current:
            order.append(order.pop(0))
    return order[0], order[1:]


# Spotify 授權失敗的說明文字。
# ⚠️ 一律用「代碼 → 寫死的句子」查表，**不要把代碼本身插進訊息裡**——
# 代碼源自 ?error= 網址參數，而 st.warning() 會渲染 Markdown，回顯就等於讓攻擊者
# 在本站登入頁的官方警告框內插入釣魚連結或追蹤圖片（見 spotify_api._set_auth_error）。
# 查不到的 key 一律落到 unknown_error。
_AUTH_ERR_ALLOWLIST_HINT = (
    "先用上面的「直接開始推薦」即可，或展開下方進階設定用自己的 Spotify 登入。"
)
AUTH_ERROR_MESSAGES = {
    "access_denied":
        "⚠️ 你在 Spotify 頁面取消了授權。想改用個人化推薦的話再點一次登入即可。",
    # ⚠️ 這則是「登入被安全機制擋下」的說明，不能拿掉——沒有它使用者會遇到
    # 「點了登入卻回到原頁、毫無反應」而不知道要重試。
    # 但也不要寫得太嚇人：最常見的原因只是停留超過 10 分鐘（state 過期），
    # 講成疑似攻擊反而讓正常使用者困惑。一句話 + 一個動作就夠。
    "state_mismatch":
        "登入連結已過期（超過 10 分鐘），請再點一次「用 Spotify 登入」。",
    "invalid_client":
        "⚠️ Spotify 授權失敗：這個 App 的設定有誤（invalid_client）。"
        + _AUTH_ERR_ALLOWLIST_HINT,
    "invalid_scope":
        "⚠️ Spotify 授權失敗：要求的權限範圍無效。" + _AUTH_ERR_ALLOWLIST_HINT,
    "server_error":
        "⚠️ Spotify 伺服器暫時出錯，請稍後再試一次。",
    "temporarily_unavailable":
        "⚠️ Spotify 服務暫時無法使用，請稍後再試一次。",
    "token_exchange_failed":
        "⚠️ 與 Spotify 交換憑證時失敗。本站的 Spotify 登入有人數上限，"
        "你的帳號可能還沒被加入授權名單——" + _AUTH_ERR_ALLOWLIST_HINT,
    # localStorage 被擋（無痕／封鎖網站資料）＝沒有可綁定的瀏覽器識別，state 驗不了。
    # 講「無痕模式」比講「localStorage」有用得多——使用者知道怎麼處理前者。
    "browser_unverified":
        "無法完成登入：這個瀏覽器不讓本站保存識別資料，因此無法確認這次授權是你發起的。"
        "請改用一般視窗（非無痕）、或允許本站的網站資料後再試一次，"
        "也可以直接使用不需登入的訪客模式。",
    "unknown_error":
        "⚠️ Spotify 授權失敗。本站的 Spotify 登入有人數上限，"
        "你的帳號可能還沒被加入授權名單——" + _AUTH_ERR_ALLOWLIST_HINT,
}


WMO_CODES = {
    0: "晴朗", 1: "大致晴朗", 2: "局部多雲", 3: "陰天",
    45: "霧", 48: "結霜霧",
    51: "輕微毛毛雨", 53: "中度毛毛雨", 55: "大毛毛雨",
    61: "小雨", 63: "中雨", 65: "大雨",
    71: "小雪", 73: "中雪", 75: "大雪",
    80: "陣雨", 81: "中陣雨", 82: "強陣雨",
    95: "雷雨", 96: "雷雨夾冰雹", 99: "強雷雨夾冰雹",
}



def logout() -> None:
    for k in (
        "spotify_token",
        "user_profile",
        "user_display_name",
        "found", "context_interp", "playlist_title", "playlist_blurb", "novelty_notice", "novelty_stats",
        "recommend_history",
        "user_profile_future",
        "guest_mode",
    ):
        st.session_state.pop(k, None)
    # 聆聽資料快取的 key 帶了 user id（user_profile::v2::xxx），不清掉的話重新登入會
    # 拿到舊資料——而新增 scope 後正是要靠重新授權才讀得到追蹤歌手；
    # 殘留的 key 還會擋住 start_profile_prefetch() 的 guard，讓之後整個 session 都改走同步抓取
    for k in [k for k in st.session_state if k.startswith("user_profile::")]:
        st.session_state.pop(k, None)
    st.rerun()


def is_guest_mode() -> bool:
    return st.session_state.get("guest_mode", False)


def enter_guest_mode() -> None:
    st.session_state["guest_mode"] = True
    st.rerun()



def show_login_required() -> None:
    """未登入時顯示的歡迎/登入頁：訪客模式（主要）+ Spotify 登入 + 進階 Spotify BYOK。"""

    # ── Hero ──
    st.markdown(styles.login_hero_html(), unsafe_allow_html=True)

    has_gemini = bool(_gemini_key())
    if not has_gemini:
        # 只有網站管理者會看到：Secrets 沒設好
        st.error(
            "⚠️ 本站的 Gemini API Key 尚未設定，暫時無法產生推薦。"
            "（管理者：請在 Streamlit Cloud → Settings → Secrets 加入 `GEMINI_API_KEY`）"
        )

    # ── 方式一：訪客模式（零設定，人數不限）──
    st.markdown(styles.login_guest_card(), unsafe_allow_html=True)

    if st.button(
        "直接開始推薦",
        icon=":material/play_arrow:",
        type="primary",
        width="stretch",
        disabled=not has_gemini,
    ):
        enter_guest_mode()

    # ── 方式二：Spotify 登入（需被加入授權名單）──
    st.markdown(styles.divider_html(), unsafe_allow_html=True)
    st.markdown(styles.login_spotify_card(), unsafe_allow_html=True)

    has_spotify_creds = bool(
        _get_credential("SPOTIFY_CLIENT_ID")
        and _get_credential("SPOTIFY_CLIENT_SECRET")
        and _get_credential("SPOTIFY_REDIRECT_URI")
    )

    if has_spotify_creds:
        # 已帶上綁定本瀏覽器的 state，見 spotify_api._make_oauth_state()。
        # ⚠️ 綁不了（拿不到 XSRF cookie）時回 None——**絕對不要退而發一個沒有 state 的網址**，
        #    那等於把授權碼注入（login CSRF）的防護整個關掉，而且使用者完全看不出來。
        #    寧可少一種登入方式（訪客模式仍可用），也不要提供一個沒有防護的登入。
        _login_url = get_login_url()
        if _login_url:
            st.link_button(
                "用 Spotify 登入",
                _login_url,
                icon=":material/headphones:",
                type="secondary",
                width="stretch",
            )
            st.caption(":material/lock: Token 只存在瀏覽器分頁記憶體，關掉就消失。")
        elif browser_id_pending():
            # 綁定用的瀏覽器代號來自 localStorage 元件，首輪 render 還沒回傳。
            # ⚠️ 這一瞬間**不要**顯示錯誤——正常使用者每次載入都會經過這裡。
            st.caption(":material/lock: 正在準備安全的登入連線…")
        else:
            st.warning(
                "無法建立安全的登入連線——這個瀏覽器不讓本站保存識別資料"
                "（無痕模式或封鎖網站資料時會這樣），因此無法把登入請求綁定到你的瀏覽器。"
                "請改用一般視窗、或允許本站的網站資料後重新整理，"
                "也可以直接使用上方的訪客模式。",
                icon=":material/lock:",
            )

        # 授權名單的說明只在真的登入失敗時才出現，平常不佔首頁版面
        auth_err = st.session_state.get("spotify_auth_error")
        if auth_err:
            st.warning(AUTH_ERROR_MESSAGES.get(auth_err, AUTH_ERROR_MESSAGES["unknown_error"]))
    else:
        st.warning("本站尚未設定 Spotify 登入，請用上方的訪客模式，或在下方進階設定填入自己的 Spotify App。")

    # ── 進階：自備 Spotify App ──
    st.markdown(styles.divider_html(), unsafe_allow_html=True)
    _render_api_key_settings()


def _render_api_key_settings(expanded: bool = False) -> None:
    """渲染進階 Spotify 設定區（登入頁 + sidebar 共用）。
    Gemini 由本站自備，使用者不需要也不能填。"""
    default_redirect = _get_env("SPOTIFY_REDIRECT_URI") or "http://127.0.0.1:8501/"

    with st.expander("進階（選填）：用自己的 Spotify 登入", expanded=expanded,
                     icon=":material/build:"):

        # ── 說明標語 ──
        st.markdown(
            "<div style=\"font-family:'Nunito','Noto Sans TC',sans-serif;font-size:0.92rem;"
            "color:#2D1B4E;line-height:1.7;padding:4px 0 8px 0\">"
            "<strong>大部分人不需要這一區</strong>——直接用訪客模式就能推薦，AI 由本站提供。<br>"
            "只有當你想讀取<strong>自己的 Spotify 聆聽紀錄</strong>做個人化推薦、"
            "但帳號不在本站的 Spotify 授權名單內時，才需要自己建一個 Spotify App（約 5 分鐘）。"
            "</div>",
            unsafe_allow_html=True,
        )

        # ── Spotify 步驟卡 ──
        # 卡片刻意拆成上下兩半，中間夾一個原生的 st.code()：它自帶可用的複製圖示
        # （自製 <button onclick> 是死的，Streamlit 會把事件處理器整個濾掉），
        # 而且 redirect_uri 因此完全不經過 unsafe_allow_html。
        # 接縫靠 styles.py 的 .st-key-byok_steps / .st-key-byok_uri 規則畫成一張卡。
        with st.container(key="byok_steps"):
            st.markdown(styles.byok_spotify_steps_head_html(), unsafe_allow_html=True)
            with st.container(key="byok_uri"):
                st.code(default_redirect, language=None)
            st.markdown(styles.byok_spotify_steps_tail_html(), unsafe_allow_html=True)

        # ── Spotify 輸入欄 ──
        c1, c2 = st.columns(2)
        with c1:
            st.text_input(
                "Spotify Client ID",
                key="custom_SPOTIFY_CLIENT_ID",
                type="password",
                placeholder="貼上你的 Client ID",
            )
        with c2:
            st.text_input(
                "Spotify Client Secret",
                key="custom_SPOTIFY_CLIENT_SECRET",
                type="password",
                placeholder="貼上你的 Client Secret",
            )

        # Redirect URI：自動帶入正確值，不再需要使用者手動填寫
        # 若 session 中沒有自訂值，就用環境變數預設值
        if not st.session_state.get("custom_SPOTIFY_REDIRECT_URI"):
            st.session_state["custom_SPOTIFY_REDIRECT_URI"] = default_redirect

        # 網址本身已經在上面步驟 3 的 st.code 裡（附複製圖示），這裡不再重複一次
        st.caption(":material/check_circle: Redirect URI 已自動帶入上方步驟 3 的網址　（如需修改請展開進階設定）")
        with st.expander("進階：手動修改 Redirect URI", expanded=False,
                         icon=":material/build:"):
            st.text_input(
                "Redirect URI（需與 Spotify Dashboard 設定一致）",
                key="custom_SPOTIFY_REDIRECT_URI",
                placeholder=default_redirect,
                help=f"通常不需要改動，預設值：{default_redirect}",
            )

        # ── 隱私說明 ──
        st.markdown(styles.byok_privacy_badge_html(), unsafe_allow_html=True)


# ── Context helpers ───────────────────────────────────────
DEFAULT_TZ_OFFSET = 8 * 3600  # 查不到 IP 時區時的預設（台北 UTC+8）
_GEO_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="geo")


def get_time_of_day(hour: int) -> str:
    if 5 <= hour < 9:  return "清晨"
    if 9 <= hour < 12: return "上午"
    if 12 <= hour < 14: return "中午"
    if 14 <= hour < 18: return "下午"
    if 18 <= hour < 21: return "傍晚"
    if 21 <= hour < 24: return "晚上"
    return "深夜"


# 反向代理放使用者真實 IP 的標頭，依可信度排序。X-Forwarded-For 是標準做法，
# 其餘是各家 CDN/代理的慣例——Streamlit Cloud 實際送哪一個沒有文件，所以全試一輪。
_CLIENT_IP_HEADERS = (
    "X-Forwarded-For",      # 標準：client, proxy1, proxy2 …
    "X-Real-Ip",
    "Cf-Connecting-Ip",     # Cloudflare
    "True-Client-Ip",
    "X-Client-Ip",
)


def _first_global_ip(raw: str) -> str:
    """從 `a, b, c` 這種標頭值裡挑出第一個「公開」IP。

    ⚠️ 不能只取最左邊那一段：代理鏈最左邊有可能是內網位址（實測 Streamlit Cloud
    定位會落在伺服器所在地 The Dalles，就是因為整條鏈都沒挑出可用的公開 IP）。
    is_global 一個判斷就涵蓋 private / loopback / link-local / reserved / multicast，
    連 RFC 文件保留範圍（203.0.113.x、2001:db8::）也算在內。
    """
    for part in raw.split(","):
        try:
            ip = ipaddress.ip_address(part.strip())
        except ValueError:
            continue
        if ip.is_global:
            return str(ip)
    return ""


def _browser_tz_offset() -> int | None:
    """瀏覽器回報的 UTC 偏移（秒）。拿不到回 None。

    這是**最可靠的時區來源**：由瀏覽器的 JS 直接回報，不需要網路請求、不受代理鏈影響，
    使用者掛 VPN 時也仍然是他當地的時間。
    實測 Streamlit Cloud 的代理鏈只剩內網位址（見 `_client_ip` 的說明），IP 定位在雲端
    根本拿不到位置，所以時區絕對不能依賴它。

    ⚠️ `st.context.timezone_offset` 與 JS 的 `getTimezoneOffset()` 同慣例——
    是「**落後** UTC 幾分鐘」，台北（UTC+8）回傳 **-480**。
    本專案 `geo_tz_offset` 的慣例是「領先 UTC 幾秒」，所以要乘 -60。
    """
    try:
        mins = st.context.timezone_offset
    except Exception:
        return None
    if not isinstance(mins, int) or isinstance(mins, bool):
        return None
    return -mins * 60


def sync_browser_timezone() -> None:
    """頁面載入時就把瀏覽器時區寫進 session_state，讓 `_local_now()` 立刻正確。

    不能只在「自動偵測位置」開啟時才做——關掉自動偵測的使用者一樣需要正確的時刻，
    歌單名稱、推薦情境的「深夜/清晨」判斷都靠它。
    """
    off = _browser_tz_offset()
    if off is not None:
        st.session_state["geo_tz_offset"] = off


def _is_local_dev() -> bool:
    """瀏覽器是否直連本機的 streamlit（沒有任何反向代理）。

    這種情況下「伺服器」就是開發者自己的機器，讓 ipwho.is 定位「自己」反而是對的；
    雲端則相反——那會定位到機房（The Dalles）。用 Host 區分：
    本機是 `127.0.0.1:8501` 之類，雲端是 `soundcurator.streamlit.app`。
    """
    try:
        host = (st.context.headers.get("Host") or "").strip().lower()
    except Exception:
        return False
    # ⚠️ 去 port 不能無腦 split(":")——IPv6 位址本身就有冒號（`::1` 會被切成空字串）。
    # 三種形式：`[::1]:8501`（IPv6 帶 port）、`127.0.0.1:8501`、`::1`（裸 IPv6）
    if host.startswith("["):
        host = host[1:].split("]")[0]
    elif host.count(":") == 1:
        host = host.split(":")[0]
    return host in ("localhost", "127.0.0.1", "::1", "0.0.0.0")


def _client_ip() -> str:
    """使用者真實 IP（雲端部署時伺服器自己的 IP 會是美國）。必須在主執行緒讀。

    ⚠️ 這些標頭是**使用者自己送的**、可任意偽造，而值會被拼進 `https://ipwho.is/{ip}`
    的路徑。host 改不掉（不是 SSRF），但沒驗證的話任意字串都會被送進網址——所以一律
    用 ipaddress 解析並確認是公開位址才採用。偽造的後果僅止於「使用者謊報自己的
    地點/時區」，只影響推薦情境，不是安全決策。
    """
    try:
        headers = st.context.headers
    except Exception:
        return ""
    if not headers:
        return ""
    for name in _CLIENT_IP_HEADERS:
        ip = _first_global_ip(headers.get(name, "") or "")
        if ip:
            return ip
    # 一個都沒挑到——ipwho.is 會改成定位「伺服器自己」，使用者就會看到 The Dalles
    # 之類的機房所在地。把實際收到的標頭名稱印出來，下次部署就知道該加哪一個。
    # ⚠️ 只印名稱不印值：標頭內容含 cookie / token，不能進 log。
    # 本機直連本來就不會有 proxy 標頭，不必每次都吵。
    if not _is_local_dev():
        try:
            print(f"[GEO] 找不到 client IP；可用標頭：{sorted(headers.keys())}",
                  file=sys.stderr, flush=True)
        except Exception:
            pass
    return ""


def _geo_weather_blocking(client_ip: str, allow_self_lookup: bool = False) -> tuple[str, int]:
    """IP 定位 + 天氣的純網路查詢，回傳 (顯示字串, 時區偏移秒數)。

    ⚠️ 不碰 st.session_state——這個函式會在背景執行緒跑（worker thread 不能碰 session_state）。
    """
    # ⚠️ 查不到使用者 IP 時**直接放棄**，不要打沒帶 IP 的 ipwho.is——那會定位到
    # 「發出請求的機器」，也就是雲端伺服器自己。實測使用者在台北卻顯示
    # 「The Dalles, United States｜08:27（清晨）」（Google 機房所在地 + 當地時間），
    # 比不顯示位置更糟：時刻判斷全錯，推薦情境跟著錯。
    # 回退到 DEFAULT_TZ_OFFSET（+8）至少時間是對的。
    # 例外：本機開發時「伺服器」就是開發者自己的機器，定位自己才是對的
    # （allow_self_lookup 由主執行緒的 _is_local_dev() 決定後傳進來）。
    if not client_ip and not allow_self_lookup:
        return "", DEFAULT_TZ_OFFSET

    ip_segment = f"/{client_ip}" if client_ip else ""

    # ipwho.is：免費、HTTPS、無需 API key。
    # 它在被限流或 IP 無效時會回非 JSON（或 success=false），直接 .json() 會炸成
    # 「Expecting value: line 1 column 1」這種對使用者無意義的訊息——一律當作查無位置。
    geo = {}
    try:
        resp = requests.get(f"https://ipwho.is{ip_segment}", timeout=10)
        if resp.ok and resp.headers.get("content-type", "").startswith("application/json"):
            data = resp.json()
            if data.get("success", True):
                geo = data
    except Exception:
        pass

    lat, lon = geo.get("latitude"), geo.get("longitude")
    tz_offset = (geo.get("timezone") or {}).get("offset")
    if not isinstance(tz_offset, int):
        tz_offset = DEFAULT_TZ_OFFSET

    place = ", ".join(p for p in (geo.get("city"), geo.get("country")) if p)

    weather = ""
    if lat is not None and lon is not None:
        try:
            w = requests.get("https://api.open-meteo.com/v1/forecast", params={
                "latitude": lat, "longitude": lon,
                "current": "temperature_2m,weather_code,wind_speed_10m,is_day",
                "timezone": "auto",
            }, timeout=10).json()["current"]
            weather = f"{WMO_CODES.get(w['weather_code'], '')} {w['temperature_2m']}°C".strip()
        except Exception:
            weather = ""

    return "｜".join(p for p in (place, weather) if p), tz_offset


def start_geo_prefetch() -> None:
    """頁面一載入就在背景查 IP/天氣。

    這兩個 API 是串接的（天氣要先有經緯度），實測 ipwho.is 1.8s + open-meteo 1.5s ≈ 3.3s，
    以前整段卡在按下生成之後才開始，等於白等 3 秒。提前開跑，按下去時通常已經好了。
    """
    if "geo_weather_cache" in st.session_state or "geo_future" in st.session_state:
        return
    # ⚠️ _client_ip() / _is_local_dev() 都碰 st.context，必須在主執行緒先算好再傳進去
    st.session_state["geo_future"] = _GEO_POOL.submit(
        _geo_weather_blocking, _client_ip(), _is_local_dev()
    )


def _fetch_geo_weather() -> str:
    """IP 定位 + 天氣，session 內快取 AUTO_CONTEXT_TTL 秒。查不到時回空字串，不拋例外。"""
    cached = st.session_state.get("geo_weather_cache")
    if cached and time.time() - cached["ts"] < AUTO_CONTEXT_TTL:
        _browser_off = _browser_tz_offset()
        st.session_state["geo_tz_offset"] = (
            _browser_off if _browser_off is not None else cached.get("tz", DEFAULT_TZ_OFFSET)
        )
        return cached["value"]

    future = st.session_state.pop("geo_future", None)
    try:
        if future is not None:
            value, tz_offset = future.result(timeout=12)   # 背景已經在跑，通常直接拿到
        else:
            value, tz_offset = _geo_weather_blocking(_client_ip(), _is_local_dev())
    except Exception:
        value, tz_offset = "", DEFAULT_TZ_OFFSET

    # ⚠️ 瀏覽器回報的時區優先，IP 查到的只是備援——雲端根本拿不到 client IP，
    # 而且使用者掛 VPN 時 IP 的時區是錯的。`is not None` 不能寫成 `or`：UTC+0 是 0，會被當成 falsy。
    _browser_off = _browser_tz_offset()
    st.session_state["geo_tz_offset"] = _browser_off if _browser_off is not None else tz_offset
    if value:
        st.session_state["geo_weather_cache"] = {
            "ts": time.time(), "value": value, "tz": tz_offset,
        }
    return value


def fetch_auto_context() -> str:
    # 先查地理位置：時區偏移是在這裡寫進 session_state 的，順序反過來第一次會抓到舊值
    geo = _fetch_geo_weather()
    now = _local_now()
    parts = [f"{now.strftime('%H:%M')}（{get_time_of_day(now.hour)}）"]
    if geo:
        parts.append(geo)
    return "｜".join(parts)


# ── UI ────────────────────────────────────────────────────
st.set_page_config(page_title="SoundCurator", page_icon="🎵", layout="wide")
styles.inject_global_css()

# ⚠️ 一定要在 consume_oauth_callback() 之前：OAuth state 綁的就是這個代號。
# 這行會渲染一個高度 0 的隱形元件（CSS 已在上面注入，所以不佔版面）。
_resolve_browser_id()


# ── OAuth callback 處理 + 登入閘門 ─────────────────────
consume_oauth_callback()

# 元件首輪還沒回傳時，consume_oauth_callback() 會刻意不處理 ?code=（驗不了就別驗，
# 更不能清掉參數）。這裡把頁面停在一句說明上，等元件 postback 觸發的下一輪再處理。
if st.session_state.pop("oauth_waiting", False):
    st.info("正在完成登入…", icon=":material/lock:")
    st.stop()

# ── 跨 session 持久化（Supabase，見 db.py / FEEDBACK_PERSISTENCE.md）───────
# ⚠️ Secrets 沒設好時 db.is_enabled() 為 False → 以下全部是 no-op，安靜降級成 session 級，
# 行為與改版前完全一樣。所有 DB 操作都 try/except 包住，失敗一律重置連線後降級，絕不讓生成/
# 回饋壞掉。只有「登入 ＋ DB 可用 ＋ 已同意」時才真的讀寫。
def _persist_uk() -> str | None:
    """這位登入使用者的雜湊鍵（在登入區算好、快取在 session）；訪客或 DB 未啟用回 None。"""
    if is_guest_mode() or not db.is_enabled():
        return None
    return st.session_state.get("persist_uk")


def _effective_uk() -> str | None:
    """目前身分的持久化鍵：登入→persist_uk；訪客→guest_uk（Phase 5，per-browser）；都沒有→None。

    訪客的 guest_uk 由 _ensure_guest_uk() 從 localStorage 匿名代號算出（**非同步、首輪可能還沒好**）。
    回 None 代表「這個身分還不能記名持久化」——呼叫端據此降級（訪客歌單改匿名、逐首/歷史留 session）。
    """
    if not db.is_enabled():
        return None
    if is_guest_mode():
        return st.session_state.get("guest_uk")
    return st.session_state.get("persist_uk")


def _persist_fail(exc: Exception | None = None) -> None:
    """DB 操作失敗的統一出口：一律靜默降級成 session 級，絕不讓生成/回饋壞掉。

    ⚠️ **不要在這裡重置連線**——死連線由連線池的 check 自動汰換（見 db.get_pool），
    在這裡整池關掉反而會把其他使用者正在用的好連線一起丟掉，那正是舊版單一連線的失敗模式。
    只把例外**型別**印到 stderr（Manage app 撈得到）：DB 問題以前是 100% 靜默的，
    症狀看起來像「偶發、重試就好」，很難追回根因。
    ⚠️ 只印型別不印訊息——例外訊息可能含連線字串或資料內容。
    """
    if exc is not None:
        print(f"[DB] {type(exc).__name__}", file=sys.stderr, flush=True)


def _persist_sync() -> None:
    """登入或訪客（guest_uk 已解析）後跑一次：查同意；已同意就把回饋＋歷史從 DB 讀回 session。

    未同意 → 標記 persist_needs_consent（顯示同意卡；訪客的逐首/歷史維持 session 級、歌單改匿名聚合）。
    訪客首輪 guest_uk 還沒好時 uk=None、直接返回，等元件 postback 觸發 rerun 後的下一輪再跑。失敗靜默降級。"""
    uk = _effective_uk()
    if not uk or st.session_state.get("persist_synced"):
        return
    try:
        with db.connection() as conn:
            if conn is None:
                return
            if not db.has_consent(conn, uk):
                st.session_state["persist_needs_consent"] = True
                return
            fb = st.session_state.setdefault("track_feedback", {})
            for e in db.load_feedback(conn, uk):
                k = "fb::" + "||".join(_track_key(e["title"], e["artist"]))
                fb.setdefault(k, {"title": e["title"], "artist": e["artist"], "state": e["state"]})
            hist = db.load_history(conn, uk)
            if hist:
                st.session_state["recommend_history"] = (
                    hist + st.session_state.get("recommend_history", [])
                )[-HISTORY_KEEP * 4:]
            st.session_state["persist_synced"] = True
            st.session_state["persist_needs_consent"] = False
    except Exception as e:
        _persist_fail(e)


def _persist_feedback(track: dict, state: str | None) -> None:
    """回饋變動時同步寫 DB（best-effort）；state=None ＝取消。

    - 登入或**已同意的訪客** → 記名寫 `_effective_uk()`（可回讀/刪除）。
    - **未同意的訪客** → **匿名逐首聚合**：`user_key = "anon:"+gen_id`（不綁瀏覽器、不用同意，純供整體分析）。
      gen_id 進 key 是關鍵——feedback 表主鍵是 (user_key, track_key)，若用固定 "anon" 會讓不同訪客/生成
      對同一首歌的回饋在 (anon, track_key) 互撞、被 upsert 蓋成一列。加 gen_id 就各自成列、可聚合計數，
      且同一份歌單內 (anon:gen_id, track_key) 仍唯一＝同首歌切換讚/倒讚會正確覆蓋。分析走 `user_key like 'anon:%'`。
    - 登入未同意 → 跳過（session 級）。
    """
    uk = _effective_uk()
    if not uk or st.session_state.get("persist_needs_consent"):
        if not is_guest_mode():
            return                               # 登入未同意 → 不寫
        gen_id = st.session_state.get("gen_id")
        if not gen_id or not db.is_enabled():
            return
        uk = "anon:" + gen_id                     # 訪客未同意 → 匿名逐首聚合
    title = track.get("name") or track.get("title", "")
    artist = track.get("artist", "")
    try:
        with db.connection() as conn:
            if conn is None:
                return
            if state:
                _fame = track.get("fame")
                db.upsert_feedback(
                    conn, uk, title, artist, state,
                    fame=_fame if isinstance(_fame, int) else None,
                    is_discovery=bool(track.get("_discovery")),
                    reason=track.get("reason") or None,
                    ctx=st.session_state.get("last_gen_ctx") or {},
                )
            else:
                db.delete_feedback(conn, uk, title, artist)
    except Exception as e:
        _persist_fail(e)


def _persist_history(found: list[dict]) -> None:
    uk = _effective_uk()   # 登入或已同意的訪客才寫；未同意/無身分跳過
    if not uk or st.session_state.get("persist_needs_consent"):
        return
    try:
        with db.connection() as conn:
            if conn is None:
                return
            db.upsert_history(conn, uk, [
                {"title": t.get("name") or t.get("title", ""), "artist": t.get("artist", "")}
                for t in found
            ])
            db.trim_history(conn, uk)
    except Exception as e:
        _persist_fail(e)


def _persist_playlist(*, rating: int | None = None, saved: bool = False,
                      copied: bool = False) -> None:
    """歌單層級訊號（每次生成一列，gen_id 為鍵）：3 段滿意度＋加入/複製行為。best-effort。

    訪客（Phase 5）：**已同意→記名**（`guest_uk`，per-browser、可跨 session 回讀/刪除）；
    **未同意或 guest_uk 還沒好→匿名聚合**（固定 `"anon"`＋唯一 gen_id，無身分、不可回溯，維持改版前行為）。
    方式一是主要模式、用量最大，未同意也照收匿名滿意度不放掉資料。登入者維持「同意後才寫」＋雜湊 user_key。
    """
    gen_id = st.session_state.get("gen_id")
    if not gen_id or not db.is_enabled():
        return
    uk = _effective_uk()
    if not uk or st.session_state.get("persist_needs_consent"):
        if not is_guest_mode():
            return          # 登入未同意 → 不寫
        uk = "anon"         # 訪客未同意（或 id 未解析）→ 匿名聚合
    try:
        with db.connection() as conn:
            if conn is None:
                return
            db.upsert_playlist_feedback(
                conn, uk, gen_id, rating=rating, saved=saved, copied=copied,
                num_songs=len(st.session_state.get("found") or []),
                ctx=st.session_state.get("last_gen_ctx") or {},
            )
    except Exception as e:
        _persist_fail(e)


# 歌單層級 3 段滿意度：文獻上「拿到歌單當下答得出的是整份合不合味、不是逐首喜不喜歡」
# （見 FEEDBACK_PERSISTENCE.md 的研究段）。3 段（不用 0-100，避免極端值）。
# ⚠️ 用**文字**不用 sentiment 圖示——使用者反映那三個情緒圖示「看很久看不出意義」（2026-08-23）。
_PLAYLIST_RATING = {
    "不太合": 1,
    "還可以": 2,
    "很對味": 3,
}


def _render_playlist_rating() -> None:
    """歌曲清單之後的一句 3 段滿意度——看一眼就能答、不需先聽。
    登入者要同意後才顯示；訪客一律顯示——已同意＝記名收，未同意＝匿名聚合（見 _persist_playlist）。"""
    gen_id = st.session_state.get("gen_id")
    if not gen_id or not db.is_enabled():
        return
    if not is_guest_mode() and (not _persist_uk() or st.session_state.get("persist_needs_consent")):
        return   # 登入者未同意就不顯示
    # 訪客未同意（或 id 未解析）→ 匿名收、標「匿名統計」；已同意→記名、不標
    anon = is_guest_mode() and (not _effective_uk() or st.session_state.get("persist_needs_consent"))
    with st.container(key="playlist_rating"):   # keyed 容器：上下間距靠 styles 的 .st-key-playlist_rating 對稱化
        st.caption("這份歌單合你今天的味嗎？（看一眼就好，不用先聽）"
                   + ("　·　匿名統計" if anon else ""))
        wkey = f"w_rating_{gen_id}"
        sel = st.pills("歌單滿意度", options=list(_PLAYLIST_RATING), selection_mode="single",
                       key=wkey, label_visibility="collapsed")
    rating = _PLAYLIST_RATING.get(sel or "")
    if rating and rating != st.session_state.get(f"_rated_{gen_id}"):
        st.session_state[f"_rated_{gen_id}"] = rating   # 這份已寫過就不重複寫
        _persist_playlist(rating=rating)


def _render_consent_banner() -> None:
    """登入未同意時，在**歌單出現後**（結果區頂端）邀請記住回饋——這時使用者剛好想對這份
    歌單按讚/倒讚，比一進站就用同意框擋在表單上方更貼切。

    ⚠️ 刻意不放 sidebar：sidebar 預設收合、又用 CSS 藏了頂部列，藏在裡面找不到（實測）。
    ⚠️ 用 st.markdown 行內圖示（全域 CSS 已把行內 :material: 上下置中），不用 st.info——
    st.info 的圖示與文字各自一欄，文字沒跟圖示上下對齊，且那個藍色與 Y2K 主題不搭。
    卡片外觀由 styles.py 的 .st-key-consent_banner 上色。
    """
    uk = _effective_uk()
    if not uk or not st.session_state.get("persist_needs_consent"):
        return
    with st.container(key="consent_banner"):
        # 文案以「好處」領頭（越用越準／不再推你看過的／更懂你口味），隱私事實仍完整揭露、不藏——
        # 不是暗黑模式，是把價值講清楚讓人願意選。訪客＝這台瀏覽器不跨裝置；登入＝跨裝置。
        if is_guest_mode():
            st.markdown(
                ":material/auto_awesome: **要不要讓推薦越用越準？** 記住你按過的 :material/thumb_up: / "
                ":material/thumb_down: 和聽過的歌，下次就**不再推你已經看過的**、更貼你的口味。資料只以"
                "「雜湊後、看不出是誰」的形式留存——**不是帳號、不跨裝置、可隨時一鍵刪除**。"
            )
            btn_label = "好，開始記住我的口味"
        else:
            st.markdown(
                ":material/auto_awesome: **要不要讓推薦越用越準？** 記住你按過的 :material/thumb_up: / "
                ":material/thumb_down: 和聽過的歌，下次就**不再推你已經看過的**、**跨裝置**都更懂你的口味。"
                "資料只以「雜湊後、看不出是誰」的形式留存，**可隨時一鍵刪除**。"
            )
            btn_label = "好，讓推薦更懂我"
        if st.button(btn_label, icon=":material/check_circle:", key="consent_btn"):
            uk2 = _effective_uk()
            try:
                with db.connection() as conn:
                    if conn is not None and uk2:
                        db.set_consent(conn, uk2)
                        st.session_state["persist_needs_consent"] = False
                        st.session_state["persist_synced"] = False   # 觸發下一輪讀回
            except Exception as e:
                _persist_fail(e)
            st.rerun()


def _render_persist_sidebar() -> None:
    """**已同意後**才在 sidebar 顯示「已記住」狀態＋刪除鍵——刪除是設定類、偶爾才用，
    放收合的 sidebar 剛好；同意閘則走 _render_consent_banner 放主頁面。"""
    uk = _effective_uk()
    if not uk or st.session_state.get("persist_needs_consent"):
        return
    with st.sidebar:
        st.markdown("---")
        if is_guest_mode():
            st.caption(":material/database: 回饋與歷史已記在**這台瀏覽器**（雜湊儲存、不跨裝置）。")
        else:
            st.caption(":material/database: 回饋與歷史已跨裝置記住（雜湊儲存）。")
        if st.button("刪除我在本站的所有資料", icon=":material/delete:", width="stretch"):
            uk2 = _effective_uk()
            try:
                with db.connection() as conn:
                    if conn is not None and uk2:
                        db.delete_all(conn, uk2)
            except Exception as e:
                _persist_fail(e)
            for _k in ("track_feedback", "recommend_history", "persist_synced"):
                st.session_state.pop(_k, None)
            for _wk in [w for w in st.session_state if isinstance(w, str) and w.startswith("w_fb::")]:
                st.session_state.pop(_wk, None)
            st.session_state["persist_needs_consent"] = True
            st.rerun()


if not is_authenticated() and not is_guest_mode():
    show_login_required()
    st.stop()

# 登入後 / 訪客模式：sidebar 顯示用戶資訊 + 登出按鈕
if is_guest_mode():
    with st.sidebar:
        st.markdown("### :material/music_note: 訪客模式")
        st.caption("未連結 Spotify・推薦不會個人化")
        if st.button("切換為 Spotify 登入", icon=":material/swap_horiz:", width="stretch"):
            logout()
        st.markdown("---")
        _render_api_key_settings()
else:
    try:
        _sp_check = get_spotify_client()
        if "user_display_name" not in st.session_state:
            _u = _sp_check.current_user()
            st.session_state["user_display_name"] = _u.get("display_name") or _u.get("id", "Spotify User")
            # 跨 session 持久化的雜湊鍵（登入時算一次、快取；DB 未啟用就不算）
            if db.is_enabled():
                try:
                    st.session_state["persist_uk"] = db.user_key(_u.get("id", ""), db.hmac_secret())
                except Exception:
                    pass
        with st.sidebar:
            st.markdown(f"### :material/account_circle: {st.session_state['user_display_name']}")
            st.caption("已連結 Spotify")
            if st.button("登出", icon=":material/logout:", width="stretch"):
                logout()
            st.markdown("---")
            _render_api_key_settings()
    except spotipy.SpotifyException as e:
        st.error(f"Spotify token 無效，請重新登入：{e}")
        logout()
    except Exception as e:
        st.error(f"Spotify 連線異常：{e}")
        st.stop()

# 跨 session 持久化：登入或（已同意的）訪客 → 把回饋＋歷史讀回 session；sidebar 顯示刪除鈕。
# ⚠️ 順序：先 _ensure_guest_uk() 解析訪客 guest_uk（登入時 no-op），_persist_sync() 才拿得到訪客身分。
# DB 未啟用時全部 no-op。
_ensure_guest_uk()
_persist_sync()
_render_persist_sidebar()


# 時區直接向瀏覽器要，不依賴 IP（雲端的代理鏈拿不到 client IP，見 _client_ip）
sync_browser_timezone()
# IP 定位 + 天氣在背景先跑（約 3.3 秒），使用者填完情境按下生成時通常已經拿到結果
start_geo_prefetch()
# 聆聽資料（18 個 endpoint）同樣在背景先抓，按下生成時通常已經好了
start_profile_prefetch()

# 返回首頁：退出目前模式（訪客／登入）回到歡迎頁。放主頁面頂端而非收合的 sidebar
# ——sidebar 藏得住（同意卡實測就找不到），返回入口一定要看得見。
with st.container(key="back_home_row"):
    if st.button("返回首頁", icon=":material/arrow_back:", key="back_home"):
        logout()

st.markdown(styles.form_hero_html(), unsafe_allow_html=True)

# ══ 第一層：情境輸入（唯一必要的一區）═══════════════════
# 隱私說明收進 help（問號圖示的 tooltip），不佔版面
auto_ctx = st.toggle(
    "自動偵測位置與天氣",
    value=True,
    key="auto_ctx",
    help="啟用時會透過 [ipwho.is](https://ipwho.is) 取得 IP 地理位置，"
         "僅用於判斷天氣與時區，不儲存。",
)

# 兩欄都用 markdown 當標題（16px，跟投射問題同級——widget label 只有 14px），
# 並把原本的 label 收起來，讓左右兩個輸入框的頂端對齊。
# 括號補充包在 .y2k-keep（inline-block）裡：窄螢幕換行時整段一起下去，
# 不會斷成「…給 AI / 分析）」；桌機放得下時仍是一行
# 標題（含對話氣泡圖示）由 styles.context_label_html() 統一產出——
# 左欄與右欄的隱藏佔位必須是同一份內容，換行行為才一致（見該 helper 的 docstring）
col1, col2 = st.columns(2)
with col1:
    st.markdown(styles.context_label_html(), unsafe_allow_html=True)
    text_ctx = st.text_area(
        "分享一下你的日常吧",
        placeholder="例如：在咖啡廳讀書、深夜想一個人散步、運動前暖身…",
        height=106,
        key="text_ctx",
        label_visibility="collapsed",
    )
with col2:
    # 標題已併進左欄那句。這裡放同一句、同一種元件，再用 CSS 藏起來當佔位——
    # 視窗窄到標題換行時左右兩邊會一起換行，兩個輸入框的頂端才會永遠齊
    with st.container(key="ctx_label_spacer"):
        st.markdown(styles.context_label_html(), unsafe_allow_html=True)
    uploaded = st.file_uploader(
        "上傳情境圖片",
        type=["jpg", "jpeg", "png", "webp"],
        help="上傳一張能代表你當下心情或環境的照片，最大 10 MB",
        key="ctx_image",
        label_visibility="collapsed",
    )
    if uploaded:
        st.image(uploaded, width="stretch")

# ══ 投射問題（本站特色，從頁面最底下提到這裡）═══════════
if "projective_q" not in st.session_state:
    _q, _rest = _rotate_projective([], None)
    st.session_state["projective_q"], st.session_state["proj_order"] = _q, _rest

# 固定比例會讓短題目和按鈕之間留下一大片空白（題目 170–403px 不等，欄寬卻固定）。
# 改用 key 讓 styles.py 把這一列的兩欄變成 width:auto，按鈕永遠緊跟在題目後面。
with st.container(key="proj_row"):
    proj_col1, proj_col2 = st.columns([3, 2], vertical_alignment="center")
    with proj_col1:
        st.markdown(
            styles.projective_question_html(st.session_state["projective_q"]),
            unsafe_allow_html=True,
        )
    with proj_col2:
        if st.button("換一題", icon=":material/refresh:"):
            _q, _rest = _rotate_projective(
                st.session_state.get("proj_order") or [],
                st.session_state["projective_q"],
            )
            st.session_state["projective_q"], st.session_state["proj_order"] = _q, _rest
            st.session_state["projective_a"] = ""
            st.rerun()

projective_answer = st.text_input(
    "你的回答",
    key="projective_a",
    placeholder="隨意回答，越具體越好",
    label_visibility="collapsed",
)

# 推薦歷史：狀態列跟著生成按鈕走，清除按鈕收進「推薦歌曲數」（罕用且不可逆）
_session_hist_n = len(st.session_state.get("recommend_history", []))
_persistent_hist_n = 0 if is_guest_mode() else len(load_persistent_history())
_total_hist_n = _session_hist_n + _persistent_hist_n

# 訪客「探索度」：標籤 → recommend 的 fame_mode（見 recommend.GUEST_FAME_MODES）。
# 均衡＝改版前行為（預設）；探索才帶「至少一半 fame1-2」配額＋較嚴天花板。
_GUEST_FAME_LABELS = {"熟悉": "familiar", "均衡": "balanced", "探索": "discovery"}

_setting_sum = f"{st.session_state.get('num_songs', 15)} 首"
if is_guest_mode():
    _setting_sum += f" · {st.session_state.get('guest_fame_mode', '均衡')}"
else:
    _setting_sum += f" · 新藝人 {st.session_state.get('new_artist_ratio', 70)}%"

with st.expander(f"推薦歌曲數　·　{_setting_sum}", expanded=False,
                 key="exp_songs", icon=":material/tune:"):
    if is_guest_mode():
        new_artist_ratio = 70          # 訪客沒有聆聽紀錄，用不到「新藝人佔比」
        col_num, col_mode = st.columns(2)
        with col_num:
            num_songs = st.slider(
                "推薦歌曲數量", min_value=5, max_value=30, value=15, step=1, key="num_songs",
            )
        with col_mode:
            _fame_label = st.radio(
                "探索度", options=list(_GUEST_FAME_LABELS.keys()), index=1,
                horizontal=True, key="guest_fame_mode",
                help="熟悉 = 以你可能認得的歌為主｜均衡 = 混一些驚喜（預設）｜"
                     "探索 = 盡量給你沒聽過的冷門深軌。\n\n"
                     "沒有聆聽紀錄可比對，所以用「有多紅」當驚喜度的替代訊號：探索會要求 AI 至少一半"
                     "挑冷門曲、並擋掉太紅的歌，過濾較嚴、偶爾湊不滿。",
            )
        fame_mode = _GUEST_FAME_LABELS.get(_fame_label, "balanced")
    else:
        fame_mode = "balanced"         # 登入模式走 new_artist_ratio，fame_mode 不生效
        col_num, col_mode = st.columns(2)
        with col_num:
            num_songs = st.slider(
                "推薦歌曲數量", min_value=5, max_value=30, value=15, step=1, key="num_songs",
            )
        with col_mode:
            new_artist_ratio = st.slider(
                "新藝人佔比",
                min_value=0, max_value=100, value=70, step=10,
                format="%d%%", key="new_artist_ratio",
                help="0% = 全部從你熟悉的藝人挖深軌｜70% = 平衡｜"
                     "100% = 只推完全沒接觸過的音樂人。\n\n"
                     "研究顯示「有點陌生」才是最耐聽的位置，太熟和太陌生的歌單滿意度都會下降，"
                     "所以預設 70%；100% 是硬核探索模式，過濾很嚴，有時會湊不滿。",
            )

    st.markdown("---")
    if _total_hist_n > 0 and not is_guest_mode():
        st.caption(
            f":material/history: 已記住推薦過的 **{_total_hist_n}** 首歌"
            f"（本次 {_session_hist_n}・過往 {_persistent_hist_n}），生成時會自動避開。"
        )
    elif is_guest_mode():
        st.caption(":material/history: 訪客模式：推薦歷史僅在本次瀏覽期間有效，關掉分頁就重置。")
    elif _has_scope("playlist-read-private"):
        st.caption(":material/history: 尚未有推薦歷史。每次生成後會記住，跨 session 都不重複推薦。")
    else:
        st.caption(":material/history: 想跨 session 記住推薦歷史？請從側邊欄登出後重新登入授權。")

    _clr_hist_col, _clr_fb_col = st.columns(2)
    with _clr_hist_col:
        if st.button("清除推薦歷史", icon=":material/delete:",
                     disabled=_total_hist_n == 0, width="stretch"):
            st.session_state["recommend_history"] = []
            if not is_guest_mode():
                try:
                    n = clear_persistent_history()
                    if n > 0:
                        st.toast(f"已清除 {n} 首過往推薦歷史")
                except Exception:
                    st.toast("⚠️ 清除 Spotify 歷史歌單失敗，過往推薦歷史可能仍保留")
            st.rerun()
    with _clr_fb_col:
        _fb_n = len(st.session_state.get("track_feedback", {}))
        if st.button(f"清除歌曲回饋（{_fb_n}）", icon=":material/delete:",
                     disabled=_fb_n == 0, width="stretch"):
            st.session_state["track_feedback"] = {}
            # widget state 也要一起清：留著的話下次渲染 pills 會把舊選取重新寫回 dict
            for _k in [k for k in st.session_state if isinstance(k, str) and k.startswith("w_fb::")]:
                del st.session_state[_k]
            st.rerun()


# ══ 第二層：摺疊的偏好設定 ═══════════════════════════════
def _brief(items, limit: int = 2) -> str:
    """多選清單縮成摘要：前 limit 項 + 剩餘數量。"""
    items = list(items or [])
    if not items:
        return ""
    if len(items) <= limit:
        return "、".join(items)
    return "、".join(items[:limit]) + f" +{len(items) - limit}"


def _summary(parts, empty: str) -> str:
    """組出摺疊標題右側的摘要，全空時顯示 empty。"""
    parts = [p for p in parts if p]
    return " · ".join(parts) if parts else empty


# ⚠️ 摘要必須在 widget 建立「之前」算好（expander 的標題此時就要定），
#    所以一律從 session_state 讀——Streamlit 在 rerun 前已寫入最新值。
_fav_raw = st.session_state.get("fav_artists_input", "")
_fav_n = len([a for a in _fav_raw.replace("，", ",").split(",") if a.strip()])
_music_sum = _summary(
    [
        _brief(st.session_state.get("lang_pills")),
        _brief(st.session_state.get("genre_pills")),
        f"{_fav_n} 位指定歌手" if _fav_n else "",
    ],
    "不限語言與曲風",
)

with st.expander(f"音樂偏好　·　{_music_sum}", expanded=False,
                 key="exp_music", icon=":material/music_note:"):
    languages = st.pills(
        "想聽哪些語言的歌？（可複選；不選代表不限）",
        options=LANGUAGE_OPTIONS,
        selection_mode="multi",
        key="lang_pills",
    )
    genres = st.pills(
        "想聽哪些曲風？（可複選；不選代表不限）",
        options=GENRE_OPTIONS,
        selection_mode="multi",
        key="genre_pills",
    )
    fav_artists_raw = st.text_input(
        ":material/mic: 想聽哪些歌手的歌？（用逗號分隔）",
        key="fav_artists_input",
        placeholder="例：周杰倫, Taylor Swift, NewJeans, 陳奕迅",
        help="填入後 AI 會優先從這些歌手中推薦，同時兼顧你的情境偏好。",
    )
fav_artists = [a.strip() for a in fav_artists_raw.replace("，", ",").split(",") if a.strip()] or None

_mood_sum = _summary(
    [
        f"活力 {st.session_state.get('mood_energy', 5)}",
        f"情緒 {st.session_state.get('mood_valence', 5)}",
    ],
    "",
)

with st.expander(f"現在的心情　·　{_mood_sum}", expanded=False,
                 key="exp_mood", icon=":material/mood:"):
    mood_col1, mood_col2 = st.columns(2)
    with mood_col1:
        mood_energy = st.slider(
            "活力程度",
            min_value=1, max_value=10, value=5, step=1, key="mood_energy",
            help="1 = 完全放空｜10 = 精力爆棚",
        )
    with mood_col2:
        mood_valence = st.slider(
            "情緒",
            min_value=1, max_value=10, value=5, step=1, key="mood_valence",
            help="1 = 低落／煩躁｜5 = 平靜｜10 = 愉悅／興奮",
        )

_traits_sum = _summary(
    [
        v for v in (
            st.session_state.get("mbti"),
            st.session_state.get("blood_type"),
            st.session_state.get("zodiac"),
        ) if v and v != "不指定"
    ],
    "未填",
)

with st.expander(f"關於你　·　{_traits_sum}", expanded=False,
                 key="exp_traits", icon=":material/psychology:"):
    st.caption("不同性格／星座的音樂偏好取向不太一樣，AI 會納入考量。")
    mbti = st.selectbox("MBTI 性格類型", MBTI_TYPES, key="mbti")
    col_bt, col_zd = st.columns(2)
    with col_bt:
        blood_type = st.selectbox("血型", BLOOD_TYPE_OPTIONS, key="blood_type")
    with col_zd:
        zodiac = st.selectbox("星座", ZODIAC_OPTIONS, key="zodiac")

# ══ 生成按鈕：放在所有偏好設定之後（使用者填完再送出，2026-08-23 從表單上方移到這裡）═══
generate_slot = st.container()   # 就在此建，按鈕/狀態/進度都渲染在「關於你」下方
# 節流狀態要在建立按鈕「之前」算好——按鈕的 disabled 參數當下就要定
_rl_ok, _rl_why, _rl_wait, _rl_left = ratelimit.peek(_rate_key(), time.time())
_rl_exhausted = _rl_why == "daily"

# ⚠️ 冷卻中**不要**把按鈕 disable：按鈕的文字與 disabled 都是「渲染當下」的快照，
# Streamlit 沒有重跑就不會更新。實測 20 秒冷卻早就過了，畫面還停在「請稍候 6 秒」
# 而且點不動——使用者會以為壞了。改成讓他點得下去，由 consume() 用當下的時間
# 回一個準確的秒數；點擊本身就會觸發重跑，狀態永遠是新的。
# 每日上限則相反：它持續 24 小時，disable 不會有卡住的問題，而且明確擋住比較清楚。
# ⚠️ **全站閘門（global_*）跟冷卻同一邊，不要 disable**：它是暫時的，而且被它擋下
# 完全不扣個人額度（見 ratelimit.acquire 的順序保證），讓使用者點得下去反而能拿到
# 當下最準確的等待時間。
_clicked = generate_slot.button(
    "今日次數已用完" if _rl_exhausted else "生成推薦歌單",
    icon=":material/hourglass_top:" if _rl_exhausted else ":material/auto_awesome:",
    type="primary",
    width="stretch",
    key="btn_generate",
    disabled=_rl_exhausted,
)
# 冷卻/額度/歷史狀態合併成**一個** caption——多個 st.caption 之間的上下間距不一致
# （各自帶 stMarkdownContainer 的 -16px 負邊界，兩兩相加不均），改用 Markdown 硬換行
# 讓多行走同一元素的行高，間距才一致（見「版面幾何」）。
_status_lines = []
if _rl_exhausted:
    _status_lines.append(
        ":material/traffic: 本站的 AI 由站方自備、所有人共用同一份免費配額，因此設有每日上限。"
        "額度會在 24 小時內逐步恢復。"
    )
elif _rl_why == "global_day":
    _status_lines.append(
        ":material/traffic: 今天全站的 AI 額度已經用完了（所有使用者共用同一份免費配額），"
        "明天會逐步恢復。"
    )
elif _rl_why == "global_hour":
    _status_lines.append(
        f":material/groups: 現在使用的人比較多，{_human_wait(_rl_wait)}後會有名額釋出。"
    )
elif _rl_wait:
    _status_lines.append(f":material/hourglass_top: 剛生成過，約 {_rl_wait} 秒後可以再按一次。")
elif _rl_left <= 5:
    _status_lines.append(f":material/traffic: 今日還可以生成 {_rl_left} 次。")
if _total_hist_n > 0:
    _status_lines.append(f":material/history: 已記住推薦過的 {_total_hist_n} 首歌，這次會自動避開。")
if _status_lines:
    # keyed 容器：夾在生成按鈕與結果之間，上下間距靠 .st-key-gen_status 對稱化（先量再改）
    generate_slot.container(key="gen_status").caption("  \n".join(_status_lines))  # 兩空格+換行＝硬換行

if _clicked:
    # ⚠️ 先驗輸入、後扣額度：順序反過來的話，使用者什麼都沒填就按下去也會被扣一次，
    # 等於用「填錯」把自己的每日額度耗光。
    if not auto_ctx and not text_ctx.strip() and not uploaded:
        st.error("請至少啟用自動偵測、輸入文字，或上傳圖片其中一個。")
    # ⚠️ 真的要送出之前再扣一次額度，不能只信上面的 status()：那是唯讀的，
    # 跟這裡之間使用者可能已經多點了幾下（按鈕的 disabled 只是前端狀態）
    # ⚠️ acquire() 一次判定全站閘門＋個人額度，且保證「有扣就一定有生成」。
    #    不要退回 consume()——那只看個人額度，全站上限等於沒有。
    elif not (_rl := ratelimit.acquire(_rate_key(), time.time()))[0]:
        st.warning(_rate_limit_warning(_rl[1], _rl[2]), icon=":material/traffic:")
    else:
        # ⚠️ 清空舊結果一定要放在這裡（確定要生成之後），不能放在 if _clicked 的開頭：
        # 那樣的話「輸入沒填」或「被冷卻擋下」也會把使用者上一份歌單清掉——
        # 手滑多點一下就白白失去剛生成好的結果。實測確認過這個症狀。
        for k in ("found", "context_interp", "playlist_title", "playlist_blurb"):
            st.session_state.pop(k, None)

        context_parts = []

        # 進度顯示在生成按鈕正下方（跟著 container 走，不會掉到頁面底部）
        status_col, _ = generate_slot.columns([1, 1])
        with status_col:
            with st.status("準備中...", expanded=True) as status:
                profile = None
                if is_guest_mode():
                    st.write(":material/person_off: 訪客模式：不讀取個人資料")
                else:
                    st.write(":material/sync: 讀取 Spotify 聆聽資料...")
                    _sp_error = None
                    for _attempt in range(3):
                        try:
                            profile = fetch_user_profile()
                            st.write(f":material/check_circle: 已讀取：{st.session_state.get('user_display_name', 'Spotify 用戶')}")
                            _sp_error = None
                            break
                        except Exception as e:
                            _sp_error = e
                            if _attempt < 2:
                                st.write(f"⚠️ 連線中斷，第 {_attempt + 2} 次重試...")
                                time.sleep(1.5)
                    if _sp_error is not None:
                        st.error(f"Spotify 連線失敗：{_sp_error}")
                        st.stop()

                if auto_ctx:
                    st.write(":material/my_location: 偵測位置與天氣...")
                    try:
                        ctx = fetch_auto_context()
                        context_parts.append(f"環境情境：{ctx}")
                        st.write(f":material/location_on: {ctx}")
                    except Exception as e:
                        st.warning(f"自動偵測失敗：{e}")

                if uploaded:
                    st.write(":material/image: 分析圖片氛圍...")
                    try:
                        if uploaded.size > 10 * 1024 * 1024:
                            st.warning(f"圖片過大（{uploaded.size / 1024 / 1024:.1f} MB），請上傳 10 MB 以內的圖片。")
                        else:
                            img_bytes = uploaded.read()
                            mime = uploaded.type or "image/jpeg"
                            img_ctx = analyze_image(_gemini_key(), img_bytes, mime)
                            context_parts.append(f"圖片分析：{img_ctx}")
                            st.write(f":material/palette: {img_ctx}")
                    except Exception as e:
                        st.warning(f"圖片分析失敗：{e}")

                if text_ctx.strip():
                    context_parts.append(f"文字描述：{text_ctx.strip()}")
                    st.write(":material/chat_bubble: 文字情境已加入")

                # 組合使用者特質與當下狀態
                traits_parts = []
                if mbti and mbti != "不指定":
                    traits_parts.append(f"- MBTI 性格：{mbti}")
                if blood_type and blood_type != "不指定":
                    traits_parts.append(f"- 血型：{blood_type}")
                if zodiac and zodiac != "不指定":
                    traits_parts.append(f"- 星座：{zodiac}")
                energy_label = "低" if mood_energy <= 3 else "高" if mood_energy >= 8 else "中"
                valence_label = "低落" if mood_valence <= 3 else "愉悅" if mood_valence >= 8 else "平靜"
                traits_parts.append(f"- 當下心情：活力 {mood_energy}/10（{energy_label}）、情緒 {mood_valence}/10（{valence_label}）")
                if projective_answer.strip():
                    traits_parts.append(
                        f"- 投射問題「{st.session_state['projective_q']}」"
                        f"\n  使用者回答：{projective_answer.strip()}"
                        f"\n  （請從這個回答推測使用者的當下狀態、生活風格、潛在心情）"
                    )
                user_traits = "\n".join(traits_parts)

                # 歷史推薦：session 內 + 跨 session
                session_history = st.session_state.get("recommend_history", [])
                if is_guest_mode():
                    history = session_history
                else:
                    persistent_history = load_persistent_history()
                    history = session_history + persistent_history

                # 歌曲回饋（👍/👎/🎧）：曲目一律併進排除清單（就算清了推薦歷史，
                # 回饋過的歌也不再推薦；放在清單尾端＝一定落在 prompt 的最近 40 筆窗內），
                # 同時整理成 prompt 的品味引導區塊
                _fb_all = list(st.session_state.get("track_feedback", {}).values())
                if _fb_all:
                    history = history + [
                        {"title": f["title"], "artist": f["artist"]} for f in _fb_all
                    ]
                feedback = {
                    "liked": [f for f in _fb_all if f["state"] == "like"],
                    "disliked": [f for f in _fb_all if f["state"] == "dislike"],
                    "heard": [f for f in _fb_all if f["state"] == "heard"],
                }
                if not any(feedback.values()):
                    feedback = None
                else:
                    # 真實使用者的回饋量進日誌（Manage app 可撈）——除了 EVAL.md 之外
                    # 第二個演算法品質訊號源：👍 率高的 prompt 改動才是真的有效
                    print(
                        f"[FEEDBACK] liked={len(feedback['liked'])} "
                        f"disliked={len(feedback['disliked'])} heard={len(feedback['heard'])} "
                        f"guest={is_guest_mode()}",
                        file=sys.stderr, flush=True,
                    )
                # 這行是生成當下的暫態敘事，只留最關鍵的個人化旋鈕，保持一行不換行
                # （語言/曲風/避開過往等細節本來就顯示在表單摘要與結果頁，不用在這裡重述）
                _ratio_msg = (
                    f"探索度：{st.session_state.get('guest_fame_mode', '均衡')}"
                    if is_guest_mode()
                    else f"新藝人 {new_artist_ratio}%"
                )
                st.write(
                    f":material/auto_awesome: Gemini 生成 {num_songs} 首推薦中（{_ratio_msg}）..."
                )
                # 兩種模式都多要一些候選：刷掉一部分後才不會湊不滿使用者要的首數。
                # 訪客的過濾較輕（去重＋同藝人上限），倍率不用登入版那麼大；
                # +2 的下限讓 5 首這種小額也有實質餘裕
                _gen_n = (
                    min(max(num_songs + 2, int(num_songs * GUEST_OVERGEN_FACTOR)), 40)
                    if is_guest_mode()
                    else min(int(num_songs * OVERGEN_FACTOR), 40)
                )
                try:
                    result = get_recommendations(
                        _gemini_key(),
                        profile, "\n".join(context_parts), _gen_n, new_artist_ratio, user_traits,
                        languages=languages or None,
                        genres=genres or None,
                        history=history or None,
                        fav_artists=fav_artists,
                        feedback=feedback,
                        fame_mode=fame_mode,
                    )
                except Exception as e:
                    st.error(f"推薦生成失敗：{e}")
                    st.stop()

                # 在 Spotify 搜尋之前先把 LLM 輸出做一次去重（正規化後的 歌名+藝人）
                raw_recs = result.get("recommendations", [])
                pre_dedupe_n = len(raw_recs)
                seen_rec: set[tuple[str, str]] = set()
                unique_recs = []
                for rec in raw_recs:
                    k = _track_key(rec.get("title", ""), rec.get("artist", ""))
                    if k in seen_rec:
                        continue
                    seen_rec.add(k)
                    unique_recs.append(rec)

                _search_token = None
                _has_spotify = bool(
                    _get_credential("SPOTIFY_CLIENT_ID")
                    and _get_credential("SPOTIFY_CLIENT_SECRET")
                )
                if _has_spotify:
                    # 兩種模式現在都超額生成，訊息統一成「候選 → 篩出」
                    _cand_msg = f"{len(unique_recs)} 首候選 → 篩出 {num_songs} 首"
                    st.write(f":material/search: Spotify 搜尋歌曲...（{_cand_msg}，並行搜尋）")
                    _search_token = _get_search_token()
                else:
                    st.write(f"⚠️ 未設定 Spotify API，跳過搜尋（{len(unique_recs)} 首）")

                _rate_limited: list[bool] = []   # 這裡是模組層級，用 list 當旗標比 global 乾淨
                _repair_budget = [REPAIR_MAX_PER_BATCH]  # 幻覺補救額度，整次生成共用（含補生成輪）

                # 補救的排除集合：歷史＋已聽過的曲目＋本次已出的卡（_resolve 邊出邊加）。
                # 少了任何一塊，補救就會補出重複的歌
                _exclude_keys: set[tuple[str, str]] = set(_history_keys(history))
                if profile is not None:
                    _exclude_keys |= {tuple(k) for k in (profile.get("known_track_keys") or ())}

                def _repair(rec: dict) -> dict | None:
                    """幻覺補救：搜不到的候選換成同一位歌手真實存在的深軌。

                    實測的幻覺模式是「歌手真的存在、歌名是編的」——方向對、細節錯，
                    所以同歌手替換能保留推薦意圖。額度用完或撞到限流就不再嘗試。
                    """
                    if _rate_limited or _repair_budget[0] <= 0 or not _search_token:
                        return None
                    try:
                        fixed = repair_hallucinated_track(
                            rec.get("title", ""), rec.get("artist", ""),
                            _exclude_keys, sp=_sp(_search_token),
                        )
                    except spotipy.SpotifyException as e:
                        if e.http_status == 429:
                            _rate_limited.append(True)
                        return None
                    except Exception:
                        return None
                    if fixed is not None:
                        _repair_budget[0] -= 1
                    return fixed

                def _resolve(recs: list[dict]) -> list[dict]:
                    """候選 → 曲目卡。搜不到的先試同歌手補救，再不行以搜尋連結卡呈現。"""
                    if _search_token and recs:
                        results, hit = _search_tracks_parallel(recs, _search_token)
                        if hit:
                            _rate_limited.append(True)
                    else:
                        results = [None] * len(recs)
                    cards = []
                    for rec, r in zip(recs, results):
                        if not r:
                            r = _repair(rec)
                        if r:
                            r["reason"] = rec.get("reason", "")
                            # Spotify 已停止提供 popularity，改由 LLM 自評的 fame 遞補
                            # （補救卡沿用原候選的 fame——同歌手的量級大致可轉移）
                            r["fame"] = rec.get("fame")
                            cards.append(r)
                            _exclude_keys.add(_track_key_from(
                                r["name"], (r.get("artist_names") or [r.get("artist", "")])[0]
                            ))
                        else:
                            _q = quote(f"{rec['title']} {rec['artist']}", safe="")
                            cards.append({
                                "name": rec["title"],
                                "artist": rec["artist"],
                                "album": "",
                                "url": f"https://open.spotify.com/search/{_q}",
                                "uri": None,
                                "cover": "",
                                "reason": rec.get("reason", ""),
                                "fame": rec.get("fame"),
                                "_no_spotify": True,
                            })
                    return cards

                found = _resolve(unique_recs)

                # 驗證鏈：去重 → 排除聽過的曲目 → 分探索/熟悉兩桶 → 探索桶套流行度天花板
                # → 依「LLM 順位 + 新穎度」重排取額
                def _curate(cards: list[dict], fav_pool: list[dict] | None = None) -> tuple[list[dict], dict]:
                    return curate_tracks(
                        cards, history=history, profile=profile,
                        new_ratio=new_artist_ratio, num_songs=num_songs,
                        # 撞到限流時搜不到不代表歌是假的，補位卡不該再套比例上限
                        spare_capped=not _rate_limited,
                        # 指定歌手保底：帶著點名歌手（fav_pool 第一輪為 None，只先算 fav_have/floor）
                        fav_artists=fav_artists, fav_pool=fav_pool,
                        # 訪客探索度（熟悉/均衡/探索）→ fame 天花板；登入模式不生效
                        fame_mode=fame_mode,
                    )

                raw_found = found
                found, _novelty = _curate(raw_found)

                # 補生成：過濾後湊不滿時，帶著「已經出現過」的清單再要一輪更冷門的。
                # 不是把清單縮短、也不是回退熱門——這是 Melo 那種 reflective retry。
                # ⚠️ 判斷「夠不夠」要看**能播的**首數：搜不到的補位卡也算進去的話，
                # 清單看起來是滿的、補生成永遠不會觸發，使用者卻拿到一堆死連結。
                def _playable(cards: list[dict], st_: dict) -> int:
                    return len(cards) - st_["spare_used"]

                # 撞到速率限制時不要補生成——再打只會罰更久，而且問題不在候選不夠
                # （訪客模式也補：歷史累積多了以後，去重會讓清單默默縮水）
                if not _rate_limited and _playable(found, _novelty) < num_songs:
                    for _ in range(REFILL_MAX):
                        _short = num_songs - _playable(found, _novelty)
                        _refill_hint = "更冷門的" if profile is not None else "不同的"
                        st.write(f":material/refresh: 過濾後少了 {_short} 首，補生成一輪{_refill_hint}...")
                        try:
                            _extra = get_recommendations(
                                _gemini_key(),
                                profile, "\n".join(context_parts),
                                min(max(_short * 2, 6), 30), new_artist_ratio, user_traits,
                                languages=languages or None,
                                genres=genres or None,
                                history=history or None,
                                fav_artists=fav_artists,
                                refill_exclude=[
                                    (r.get("title", ""), r.get("artist", "")) for r in unique_recs
                                ],
                                feedback=feedback,
                                fame_mode=fame_mode,
                            )
                        except Exception as e:
                            st.write(f"⚠️ 補生成失敗，沿用現有結果（{e}）")
                            break
                        _new_recs = []
                        for rec in _extra.get("recommendations", []):
                            k = _track_key(rec.get("title", ""), rec.get("artist", ""))
                            if k in seen_rec:
                                continue
                            seen_rec.add(k)
                            _new_recs.append(rec)
                            unique_recs.append(rec)
                        if not _new_recs:
                            break
                        # 整批重跑而不是把兩份結果相加——否則同藝人上限會被算兩次
                        raw_found = raw_found + _resolve(_new_recs)
                        found, _novelty = _curate(raw_found)
                        if _playable(found, _novelty) >= num_songs:
                            break

                # 指定歌手保底：LLM 對「指定歌手」的遵守率實測只有 0.2，同藝人上限又把
                # 兩位歌手卡在 4 首。上面每輪 _curate（fav_pool=None）已算好 fav_have/fav_floor，
                # 不夠就去抓那些歌手在 Spotify 上真實存在的深軌補到保底線（零幻覺），
                # 並放寬他們的同藝人上限。撞到限流則跳過（跟幻覺補救同一態度：別再打）。
                if (fav_artists and _search_token and not _rate_limited
                        and _novelty.get("fav_have", 0) < _novelty.get("fav_floor", 0)):
                    st.write(":material/mic: 指定歌手保底：補上真實深軌...")
                    try:
                        _fav_pool = fav_artist_pool(
                            fav_artists, _exclude_keys, sp=_sp(_search_token)
                        )
                    except spotipy.SpotifyException as e:
                        if e.http_status == 429:
                            _rate_limited.append(True)
                        _fav_pool = []
                    except Exception:
                        _fav_pool = []
                    if _fav_pool:
                        found, _novelty = _curate(raw_found, fav_pool=_fav_pool)

                # ⚠️ 提示一律寫進 session_state：這段程式跑在 st.status 容器裡，
                # 結尾的 st.rerun() 會把容器內容清掉，直接 st.warning() 使用者根本看不到。
                # ⚠️ 而且要放在補生成迴圈**之後**——限流可能是補生成那一輪才撞到的，
                # 在迴圈前組訊息的話那種情況會兩則都不出現，使用者拿到短少的清單且零解釋。
                _notices: list[str] = []
                if _rate_limited:
                    _n_link = _novelty["spare_used"] if profile is not None else 0
                    _notices.append(
                        "Spotify 搜尋暫時達到請求上限"
                        + (f"，這次有 {_n_link} 首只能附搜尋連結" if _n_link else "")
                        + "。過一陣子再試就會恢復。"
                    )
                if profile is not None:
                    # 量測用：新歌手比例、探索額度的平均熱門度、各關卡刷掉幾首、
                    # 幻覺補救了幾首（repaired 上升＋spare_used 下降＝補救在生效）
                    _repaired_n = sum(1 for t in found if t.get("_repaired"))
                    print(
                        f"[NOVELTY] {_novelty} known={profile.get('known_stats')} "
                        f"repaired={_repaired_n} "
                        f"search_cache={search_cache_info()} repair_cache={repair_cache_info()}",
                        file=sys.stderr, flush=True,
                    )
                    if not profile.get("known_artist_ids"):
                        _notices.append(
                            "讀不到你的聆聽紀錄（Spotify 可能暫時擋住了請求），"
                            "這次推薦沒有個人化過濾。稍後重試通常就會恢復。"
                        )
                    # 過濾太嚴時寧可少幾首，但要講清楚——不要讓清單默默縮水
                    # （撞到速率限制時不重複解釋，上面那則訊息已經說明原因）
                    if not _rate_limited and _playable(found, _novelty) < num_songs:
                        # ⚠️ 三個原因都要列。只報 known_track / pop_blocked 的話，
                        # 100% 模式下最大宗的「熟悉歌手候選用不上」不會被算到，
                        # 訊息會變成自相矛盾的「擋掉了 0 首…0 首」
                        _unused_familiar = _novelty["familiar_pool"] - _novelty["picked_familiar"]
                        _hist_dup = _novelty["dup_history"]
                        _why = []
                        if _hist_dup:
                            _why.append(f"{_hist_dup} 首之前已經推薦過的歌")
                        if _novelty["known_track"]:
                            _why.append(f"{_novelty['known_track']} 首你已經聽過的歌")
                        if _unused_familiar > 0:
                            _why.append(f"{_unused_familiar} 首你熟悉歌手的歌")
                        if _novelty["pop_blocked"]:
                            _why.append(f"{_novelty['pop_blocked']} 首熱門到「幾乎不可能沒聽過」的歌")
                        if _novelty["spare_used"]:
                            _why.append(f"{_novelty['spare_used']} 首在 Spotify 找不到（只附搜尋連結）")
                        # 建議要對得上真正的主因，不然會出現「歷史太滿」卻叫人調新藝人佔比
                        if _hist_dup >= max(1, _novelty["candidates"] // 3):
                            _advice = "想要更多首可以到「推薦歌曲數」裡清除推薦歷史。"
                        elif new_artist_ratio > 0:
                            _advice = "想要更多首可以把「新藝人佔比」調低一點。"
                        else:
                            _advice = "想要更多首可以清除推薦歷史，或把推薦數量調低。"
                        _notices.append(
                            f"嚴格過濾後這次只湊到 {_playable(found, _novelty)} 首可播放的歌"
                            f"（原本要 {num_songs} 首）："
                            + (f"扣掉了{'、'.join(_why)}。" if _why else "可用的候選不足。")
                            + _advice
                        )
                elif not _rate_limited and _playable(found, _novelty) < num_songs:
                    # 訪客版的湊不滿說明：原因照實列全（少列任何一個都可能自相矛盾），
                    # 主因幾乎都是歷史撞歌，建議固定指向「清除推薦歷史」
                    _why = []
                    if _novelty["dup_history"]:
                        _why.append(f"{_novelty['dup_history']} 首之前已經推薦過的歌")
                    if _novelty["dup_batch"]:
                        _why.append(f"{_novelty['dup_batch']} 首同批重複的提名")
                    if _novelty["artist_capped"]:
                        _why.append(f"{_novelty['artist_capped']} 首超過同一歌手上限的歌")
                    _notices.append(
                        f"過濾後這次只湊到 {_playable(found, _novelty)} 首"
                        f"（原本要 {num_songs} 首）："
                        + (f"扣掉了{'、'.join(_why)}。" if _why else "AI 給的可用候選不足。")
                        + "想要更多首可以到「推薦歌曲數」裡清除推薦歷史，或換個情境再生成一次。"
                    )

                st.session_state["novelty_notice"] = _notices
                # 結果頁要顯示「這批有幾首真的出圈」，得撐過結尾的 st.rerun()
                st.session_state["novelty_stats"] = _novelty if profile is not None else None

                # 更新 session 歷史
                new_session = session_history + [
                    {"title": t["name"], "artist": t["artist"]} for t in found
                ]
                st.session_state["recommend_history"] = new_session[-HISTORY_KEEP * 4:]

                # 持久化到 Spotify 私人歷史歌單（訪客模式跳過）
                if not is_guest_mode():
                    try:
                        append_to_persistent_history(found)
                    except Exception:
                        pass

                # 跨 session 持久化（DB）：記下這批的情境快照（給回饋當演算法探勘的欄位）＋寫歷史。
                # 登入且已同意才真的寫；訪客/DB 未啟用為 no-op。
                st.session_state["last_gen_ctx"] = {
                    "guest": is_guest_mode(),
                    "lang": languages or None,
                    "genre": genres or None,
                    "fame_mode": fame_mode if is_guest_mode() else None,
                    "new_ratio": None if is_guest_mode() else new_artist_ratio,
                    # 心情雙軸（1-10）——唯一「結構化＋對品味有效度＋識別風險低」的表單訊號，
                    # 刻意只收這兩個數字（星座/血型/自由文字仍不存，見 FEEDBACK_PERSISTENCE.md「訪客資料」）
                    "mood_energy": mood_energy,
                    "mood_valence": mood_valence,
                }
                # 每次生成給一個 id，當歌單層級訊號（評分/加入）的鍵
                st.session_state["gen_id"] = secrets.token_hex(8)
                _persist_history(found)

                status.update(label=f":material/check_circle: 完成！找到 {len(found)} 首推薦", state="complete")

        # 結果寫入 session_state，讓「加入歌單」按鈕能存取
        st.session_state.found = found
        st.session_state.context_interp = result.get("context_interpretation", "")
        st.session_state.playlist_title = result.get("playlist_title", "")
        st.session_state.playlist_blurb = result.get("playlist_blurb", "")
        # 強制重跑，讓頁面頂端的 _hist_n 讀到剛存入的歷史計數
        st.rerun()


# ── 提示訊息（放在結果區之外）────────────────────────────
# ⚠️ 不能放進下面的 `if st.session_state.found:`：過濾太嚴導致一首都不剩時，
# 原因說明剛好也跟著消失，畫面變成什麼都沒發生——那正是最需要解釋的情況。
_notice_state = st.session_state.get("novelty_notice") or []
if isinstance(_notice_state, str):      # 舊版存字串，直接迭代會逐字元印出來
    _notice_state = [_notice_state]
for _notice in _notice_state:
    st.info(_notice, icon=":material/explore:")

if "found" in st.session_state and not st.session_state.found:
    st.warning(
        "這次過濾後一首都沒剩下。可以把「新藝人佔比」調低、清除推薦歷史，"
        "或換個情境描述再試一次。",
        icon=":material/search_off:",
    )

# ── 顯示結果（從 session_state 讀取，這樣即使重跑也不會消失）─────────
if "found" in st.session_state and st.session_state.found:
    found = st.session_state.found

    st.markdown(styles.results_header_html(len(found)), unsafe_allow_html=True)
    # 同意閘：歌單出現後才邀請記住回饋（登入＋DB可用＋未同意時）
    _render_consent_banner()
    view_col, plat_col, slider_col = st.columns([2, 2, 3], vertical_alignment="center")
    with view_col:
        view_mode = st.radio(
            "顯示方式",
            options=["條列式", "網格"],
            index=1,
            horizontal=True,
            label_visibility="collapsed",
        )
    with plat_col:
        play_platform = st.radio(
            "用什麼聽",
            options=list(PLAY_PLATFORMS),
            index=0,
            horizontal=True,
            label_visibility="collapsed",
            key="play_platform",
            help="YouTube 走搜尋連結，不需要 Spotify 帳號也能聽；"
                 "Spotify 搜不到的歌換成 YouTube 通常反而找得到。",
        )
    with slider_col:
        if view_mode == "網格":
            cols_per_row = st.slider("每列幾首", min_value=3, max_value=10, value=5, step=1)

    # ── 曲目回饋（👍/👎/🎧）─────────────────────────────
    # 單選 pills（再點一次取消）。真相來源是 st.session_state["track_feedback"]——
    # 它撐得過重新生成與檢視切換；widget state 只是 UI 快照，Streamlit 對
    # 「這一輪沒渲染的 widget」會回收 state（生成中結果區整段不渲染就會發生），
    # 所以每次渲染前先從 dict 把選取值 seed 回 widget key。
    # pills 是原生元件，圖示只能走 :material/xxx:（B 層圖示系統，2026-08-21）
    _FB_STATE_BY_LABEL = {
        ":material/thumb_up:": "like",
        ":material/thumb_down:": "dislike",
        ":material/headphones:": "heard",
    }
    _FB_LABEL_BY_STATE = {v: k for k, v in _FB_STATE_BY_LABEL.items()}

    def _feedback_key(track: dict) -> str:
        return "fb::" + "||".join(
            _track_key(track.get("name") or track.get("title", ""), track.get("artist", ""))
        )

    def _render_feedback(track: dict) -> None:
        fb = st.session_state.setdefault("track_feedback", {})
        k = _feedback_key(track)
        wkey = "w_" + k
        if wkey not in st.session_state and k in fb:
            st.session_state[wkey] = _FB_LABEL_BY_STATE.get(fb[k]["state"])
        _old_state = fb.get(k, {}).get("state")
        sel = st.pills(
            "回饋", options=list(_FB_STATE_BY_LABEL), selection_mode="single",
            key=wkey, label_visibility="collapsed",
        )
        state = _FB_STATE_BY_LABEL.get(sel or "")
        if state:
            fb[k] = {
                "title": track.get("name") or track.get("title", ""),
                "artist": track.get("artist", ""),
                "state": state,
            }
        else:
            fb.pop(k, None)
        # 真的變動了才寫 DB（此函式每次渲染都會跑；登入讀回 seed 的那次 old==new，不會誤寫）
        if state != _old_state:
            _persist_feedback(track, state)

    # view_mode != 網格 時 cols_per_row 沒定義，靠 or 短路避開
    _fb_visible = view_mode != "網格" or cols_per_row <= 5
    if _fb_visible:
        st.caption(
            "先標 :material/headphones: 早就聽過（幫我校準新鮮度）；等真的去聽了，可以再回來給予回饋"
        )

    if view_mode == "網格":
        # key="track_grid" 讓 styles.py 把同一列的卡片拉成等高（見 .st-key-track_grid），
        # 否則歌名長短、有無專輯／理由會讓每張卡不一樣高，Spotify 按鈕就參差不齊
        with st.container(key="track_grid"):
            for i in range(0, len(found), cols_per_row):
                cols = st.columns(cols_per_row)
                for j, col in enumerate(cols):
                    idx = i + j
                    if idx < len(found):
                        track = found[idx]
                        with col:
                            show_album = cols_per_row <= 5
                            card_track = track if show_album else {**track, "album": "", "reason": ""}
                            st.markdown(
                                # 密集網格連專輯名和理由都放不下，標籤也要縮成只有圖示
                                styles.track_card_html(card_track, idx, compact_badge=not show_album),
                                unsafe_allow_html=True,
                            )
                            _label, _url = play_link(track, play_platform)
                            st.link_button(_label, _url, width="stretch")
                            if show_album:
                                # 密集網格（>5/列）欄寬塞不下三顆 pills，回饋鈕跟
                                # 專輯名/理由走同一條「密集就省略」的界線
                                _render_feedback(track)
    else:
        for i, track in enumerate(found):
            st.markdown(
                styles.track_list_html(track, i),
                unsafe_allow_html=True,
            )
            _label, _url = play_link(track, play_platform)
            st.link_button(_label, _url, width="stretch")
            _render_feedback(track)

    # ══ 歌曲清單之後（2026-08-23 版面）：情境解讀 → 出圈摘要 → 加入 Spotify → 評分 → 複製 ══
    st.divider()

    # AI 情境解讀
    if st.session_state.context_interp:
        st.markdown(
            styles.context_interpretation_html(st.session_state.context_interp),
            unsafe_allow_html=True,
        )

    # 出圈成果一行摘要。對使用者是透明度，對開發是免費的儀表板——
    # 「新歌手比例」是這次改版唯一真正的驗收指標（登入模式才有 novelty_stats）
    _ns = st.session_state.get("novelty_stats")
    if _ns:
        _parts = [f"🧭 這批有 **{_ns['picked_new']}/{len(found)}** 首來自你沒接觸過的音樂人"]
        if _ns.get("avg_pop_new") is not None:
            _parts.append(f"平均知名度 {_ns['avg_pop_new']}/100（越低越冷門）")
        _blocked = _ns["known_track"] + _ns["pop_blocked"] + _ns["dup_history"]
        if _blocked:
            _parts.append(f"幫你擋掉 {_blocked} 首可能聽過的")
        st.caption("　·　".join(_parts))

    # 加入 Spotify 歌單按鈕（訪客模式隱藏）
    save_clicked = False
    if not is_guest_mode():
        save_col1, save_col2 = st.columns([3, 1])
        with save_col1:
            playlist_name = st.text_input(
                "歌單名稱",
                value=st.session_state.get("playlist_title", "").strip()
                or f"我的專屬歌單 {_local_now().strftime('%m/%d')}",
                label_visibility="collapsed",
            )
        with save_col2:
            save_clicked = st.button("加入 Spotify", icon=":material/playlist_add:",
                                     type="primary", width="stretch")

    if save_clicked:
        # 記下「想收藏整份」的行為訊號——不管 Spotify 寫入成功或 403，意圖都已表達（比嘴巴說可信）
        _persist_playlist(saved=True)
        with st.spinner("建立歌單並寫入 Spotify..."):
            try:
                uris = [t["uri"] for t in found if t.get("uri")]
                pl = create_playlist_with_tracks(
                    playlist_name, uris,
                    description=st.session_state.get("playlist_blurb", "")
                    or st.session_state.get("context_interp", ""),
                )
                st.success(f"歌單建立成功！[在 Spotify 開啟]({pl['external_urls']['spotify']})")
            except Exception as e:
                err_msg = str(e)
                if "403" in err_msg or "Forbidden" in err_msg:
                    st.error("Spotify 寫入被拒絕（403 Forbidden）")
                    with st.expander("為什麼會這樣？怎麼解決？", expanded=True,
                                     icon=":material/menu_book:"):
                        st.markdown("""
**原因**：Spotify 對 Development Mode App 的歌單寫入有限制，你的帳號可能不在這個 App 的授權用戶清單，或 App 沒有寫入權限。

**解決方向（依序嘗試）**：

1. **檢查 User Management Email**
   到 [Developer Dashboard](https://developer.spotify.com/dashboard) → 你的 App → Settings → User Management，
   確認填的 Email 完全等於你 Spotify 帳號註冊的 Email（到 [Spotify Profile](https://www.spotify.com/account/profile) 查看）。

2. **重新授權 App**
   到 [Spotify Apps 設定](https://www.spotify.com/account/apps) 撤銷這個 App 的授權，
   然後從側邊欄登出、重新登入，強制觸發新的權限授予。

3. **用自己的 API Keys（BYOK，最可靠）**
   在「自訂 API Keys」填入自己申請的 Client ID / Secret 後重新登入——
   自己 App 的擁有者寫入自己的歌單不受此限制。

> ⚠️ 網路上常見的「申請 Extended Quota Mode」目前對個人開發者實際上已無法通過，不建議花時間等審核。
                        """)
                    st.markdown("---")
                    st.markdown("**手動加入歌單的方法**：用下方卡片每首歌的「▶ Spotify」按鈕開啟歌曲，在 Spotify 中對歌曲按右鍵 → 加入歌單。")
                else:
                    st.error(f"寫入失敗：{e}")

    # ── 歌單整體評分：瀏覽完歌單、看過 meta 之後才問（使用者看過清單再評分）──
    st.divider()
    _render_playlist_rating()

    # 組合可分享的純文字（在欄位外先計算，不渲染任何元件）
    _ctx = st.session_state.get("context_interp", "")
    _lines = ["🎵 SoundCurator — AI 推薦歌單"]
    if _ctx:
        _lines += [f"情境：{_ctx}", ""]
    for _i, _t in enumerate(found, 1):
        _lines.append(f"{_i}. {_t['name']} — {_t['artist']}")
        _lines.append(f"   💡 {_t['reason']}")
        _, _share_url = play_link(_t, play_platform)   # 分享文字跟著使用者選的平台走
        if _share_url:
            _lines.append(f"   ▶ {_share_url}")
        _lines.append("")
    _share_text = "\n".join(_lines).strip()

    # ── 複製歌單 ─────────────────────────────────────────
    st.divider()
    st.markdown(styles.section_header_html("複製歌單", icon="clipboard"), unsafe_allow_html=True)
    st.caption(f"點擊右上角複製圖示即可一鍵複製（含 {play_platform} 連結）")
    st.code(_share_text, language=None)

    # ── IG 限動分享圖卡（三種樣式都開放選；設計稿：Claude Design artifact d387af5f）──
    st.divider()
    st.markdown(styles.section_header_html("分享到 IG 限動", icon="vinyl"),
                unsafe_allow_html=True)
    st.caption("生成 1080×1920 的限時動態圖卡（封面牆＋歌單標題），下載後直接發限動")
    _style_code = st.radio(
        "圖卡樣式",
        share_card.STYLE_ORDER,
        format_func=lambda c: share_card.STYLES[c]["label"],
        captions=[share_card.STYLES[c]["caption"] for c in share_card.STYLE_ORDER],
        horizontal=True, key="share_card_style", label_visibility="collapsed",
    )
    # 圖卡跟著 (這份歌單, 樣式) 走：換樣式或重新生成才重畫，其餘 rerun（含按下載鈕）沿用
    _card_key = (st.session_state.get("gen_id"), _style_code)
    _card = st.session_state.get("share_card_png")
    if st.button("生成分享圖卡", icon=":material/image:", key="btn_share_card"):
        with st.spinner("抓封面、畫圖卡中..."):
            # 封面走 Spotify 圖片 CDN（i.scdn.co），不吃 API 配額；搜不到的曲目畫佔位磚
            _covers = share_card.fetch_covers([t.get("cover") or "" for t in found])
            _card = {"key": _card_key, "png": share_card.render_story_png(
                found, _covers, style=_style_code,
                playlist_title=st.session_state.get("playlist_title", "").strip()
                or f"我的專屬歌單 {_local_now().strftime('%m/%d')}",
                discovery_count=sum(1 for t in found if t.get("_discovery")),
                when=_local_now(),
            )}
            st.session_state["share_card_png"] = _card
    if _card and _card.get("key") == _card_key:
        _img_col, _dl_col = st.columns([1, 2], vertical_alignment="center")
        with _img_col:
            st.image(_card["png"], width=260)
        with _dl_col:
            st.download_button(
                "下載圖卡 PNG", data=_card["png"],
                file_name="soundcurator_story.png", mime="image/png",
                type="primary", icon=":material/download:", key="btn_share_card_dl",
            )
            st.caption("IG 限動開相簿選這張就能發；排版已避開上下的 IG 介面遮擋區")
