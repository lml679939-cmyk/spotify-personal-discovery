"""
Spotify Personal Discovery - Web UI
"""

import io
import random
import time
from datetime import datetime, timezone, timedelta
from urllib.parse import quote

import requests
import streamlit as st
from dotenv import load_dotenv
import spotipy
import styles

import share_card
from recommend import (
    HISTORY_KEEP,
    _norm,
    analyze_image,
    dedupe_tracks,
    get_recommendations,
)
from spotify_api import (
    _get_auth_manager,
    _get_credential,
    _get_env,
    _get_search_token,
    _has_scope,
    _search_tracks_parallel,
    append_to_persistent_history,
    clear_persistent_history,
    consume_oauth_callback,
    create_playlist_with_tracks,
    fetch_user_profile,
    get_spotify_client,
    is_authenticated,
    load_persistent_history,
)

load_dotenv()


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

PROJECTIVE_QUESTIONS = [
    "📱 你手機現在的桌布是什麼？",
    "🖼️ 你相簿中最新一張照片裡有什麼？",
    "💬 你剛剛 LINE / 訊息最後傳了什麼？",
    "🔍 最近一次 Google 搜尋了什麼？",
    "🎬 最近讓你印象最深的一個畫面（電影/影集/現實）是？",
    "☕ 你現在桌上有什麼東西？",
    "😂 上次讓你笑出聲的東西是？",
    "💭 最近腦中一直循環的一句話或歌詞？",
    "🌙 昨晚的夢（如果記得）是什麼？",
    "📚 最近在看的書/影集/YouTube 是？",
    "👕 你今天穿什麼顏色的衣服？",
    "🪟 你窗外現在看到什麼？",
    "🍴 你今天最想吃什麼？",
    "🧍 你最近一次發呆是在想什麼？",
    "🎒 如果現在出門你會帶什麼？",
]


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
        "found", "context_interp",
        "recommend_history",
        "share_images", "share_palette",
        "guest_mode",
    ):
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
        "🎶 直接開始推薦",
        type="primary",
        use_container_width=True,
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
        auth_manager = _get_auth_manager()
        auth_url = auth_manager.get_authorize_url()
        st.link_button(
            "🎧 用 Spotify 登入",
            auth_url,
            type="secondary",
            use_container_width=True,
        )
        st.caption("🔒 Token 只存在瀏覽器分頁記憶體，關掉就消失。")

        # 授權名單的說明只在真的登入失敗時才出現，平常不佔首頁版面
        auth_err = st.session_state.get("spotify_auth_error")
        if auth_err:
            st.warning(
                "⚠️ Spotify 授權失敗（"
                f"`{auth_err}`）。本站的 Spotify 登入有人數上限，"
                "你的帳號可能還沒被加入授權名單——"
                "先用上面的「🎶 直接開始推薦」即可，"
                "或展開下方進階設定用自己的 Spotify 登入。"
            )
    else:
        st.warning("本站尚未設定 Spotify 登入，請用上方的訪客模式，或在下方進階設定填入自己的 Spotify App。")

    # ── 進階：自備 Spotify App ──
    st.markdown(styles.divider_html(), unsafe_allow_html=True)
    _render_api_key_settings()


def _render_api_key_settings(expanded: bool = False) -> None:
    """渲染進階 Spotify 設定區（登入頁 + sidebar 共用）。
    Gemini 由本站自備，使用者不需要也不能填。"""
    default_redirect = _get_env("SPOTIFY_REDIRECT_URI") or "http://127.0.0.1:8501/"

    with st.expander("🔧 進階（選填）：用自己的 Spotify 登入", expanded=expanded):

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
        st.markdown(
            styles.byok_spotify_steps_html(default_redirect),
            unsafe_allow_html=True,
        )

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

        st.caption(
            f"✅ Redirect URI 已自動設定為：`{default_redirect}`　"
            "（如需修改請展開進階設定）"
        )
        with st.expander("🔧 進階：手動修改 Redirect URI", expanded=False):
            st.text_input(
                "Redirect URI（需與 Spotify Dashboard 設定一致）",
                key="custom_SPOTIFY_REDIRECT_URI",
                placeholder=default_redirect,
                help=f"通常不需要改動，預設值：{default_redirect}",
            )

        # ── 隱私說明 ──
        st.markdown(styles.byok_privacy_badge_html(), unsafe_allow_html=True)


# ── Context helpers ───────────────────────────────────────
def get_time_of_day(hour: int) -> str:
    if 5 <= hour < 9:  return "清晨"
    if 9 <= hour < 12: return "上午"
    if 12 <= hour < 14: return "中午"
    if 14 <= hour < 18: return "下午"
    if 18 <= hour < 21: return "傍晚"
    if 21 <= hour < 24: return "晚上"
    return "深夜"


def _fetch_geo_weather() -> str:
    """IP 定位 + 天氣，session 內快取 AUTO_CONTEXT_TTL 秒。查不到時回空字串，不拋例外。"""
    cached = st.session_state.get("geo_weather_cache")
    if cached and time.time() - cached["ts"] < AUTO_CONTEXT_TTL:
        return cached["value"]

    # 取得使用者真實 IP（雲端部署時 Streamlit 伺服器 IP 會是美國）
    try:
        forwarded = st.context.headers.get("X-Forwarded-For", "")
        client_ip = forwarded.split(",")[0].strip() if forwarded else ""
    except Exception:
        client_ip = ""
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
    st.session_state["geo_tz_offset"] = (geo.get("timezone") or {}).get("offset", 28800)

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

    value = "｜".join(p for p in (place, weather) if p)
    if value:
        st.session_state["geo_weather_cache"] = {"ts": time.time(), "value": value}
    return value


def fetch_auto_context() -> str:
    now = datetime.now()
    parts = [f"{now.strftime('%H:%M')}（{get_time_of_day(now.hour)}）"]
    geo = _fetch_geo_weather()
    if geo:
        parts.append(geo)
    return "｜".join(parts)


# ── UI ────────────────────────────────────────────────────
st.set_page_config(page_title="Spotify Personal Discovery", page_icon="🎵", layout="wide")
styles.inject_global_css()



# ── OAuth callback 處理 + 登入閘門 ─────────────────────
consume_oauth_callback()

if not is_authenticated() and not is_guest_mode():
    show_login_required()
    st.stop()

# 登入後 / 訪客模式：sidebar 顯示用戶資訊 + 登出按鈕
if is_guest_mode():
    with st.sidebar:
        st.markdown("### 🎶 訪客模式")
        st.caption("未連結 Spotify・推薦不會個人化")
        if st.button("🔄 切換為 Spotify 登入", use_container_width=True):
            logout()
        st.markdown("---")
        _render_api_key_settings()
else:
    try:
        _sp_check = get_spotify_client()
        if "user_display_name" not in st.session_state:
            _u = _sp_check.current_user()
            st.session_state["user_display_name"] = _u.get("display_name") or _u.get("id", "Spotify User")
        with st.sidebar:
            st.markdown(f"### 👤 {st.session_state['user_display_name']}")
            st.caption("已連結 Spotify")
            if st.button("🚪 登出", use_container_width=True):
                logout()
            st.markdown("---")
            _render_api_key_settings()
    except spotipy.SpotifyException as e:
        st.error(f"Spotify token 無效，請重新登入：{e}")
        logout()
    except Exception as e:
        st.error(f"Spotify 連線異常：{e}")
        st.stop()


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
CTX_LABEL = (
    '分享一下你的日常吧'
    '<span class="y2k-keep">（也可以上傳圖片給 AI 分析）</span>'
)

col1, col2 = st.columns(2)
with col1:
    st.markdown(f"**{CTX_LABEL}**", unsafe_allow_html=True)
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
        st.markdown(f"**{CTX_LABEL}**", unsafe_allow_html=True)
    uploaded = st.file_uploader(
        "上傳情境圖片",
        type=["jpg", "jpeg", "png", "webp"],
        help="上傳一張能代表你當下心情或環境的照片，最大 10 MB",
        key="ctx_image",
        label_visibility="collapsed",
    )
    if uploaded:
        st.image(uploaded, use_container_width=True)

# ══ 投射問題（本站特色，從頁面最底下提到這裡）═══════════
if "projective_q" not in st.session_state:
    st.session_state["projective_q"] = random.choice(PROJECTIVE_QUESTIONS)

# 固定比例會讓短題目和按鈕之間留下一大片空白（題目 170–403px 不等，欄寬卻固定）。
# 改用 key 讓 styles.py 把這一列的兩欄變成 width:auto，按鈕永遠緊跟在題目後面。
with st.container(key="proj_row"):
    proj_col1, proj_col2 = st.columns([3, 2], vertical_alignment="center")
    with proj_col1:
        st.markdown(f"**{st.session_state['projective_q']}**")
    with proj_col2:
        if st.button("🔄 換一題"):
            _cur = st.session_state["projective_q"]
            st.session_state["projective_q"] = random.choice(
                [q for q in PROJECTIVE_QUESTIONS if q != _cur]
            )
            st.session_state["projective_a"] = ""
            st.rerun()

projective_answer = st.text_input(
    "你的回答",
    key="projective_a",
    placeholder="隨意回答，越具體越好",
    label_visibility="collapsed",
)

# 生成按鈕的版面位置。實際內容要等下方所有 widget 都建立完才填得進去，
# 用 container 佔位就能讓按鈕顯示在偏好設定「上面」，程式碼卻仍在後面。
generate_slot = st.container()

# 推薦歷史：狀態列跟著生成按鈕走，清除按鈕收進「推薦歌曲數」（罕用且不可逆）
_session_hist_n = len(st.session_state.get("recommend_history", []))
_persistent_hist_n = 0 if is_guest_mode() else len(load_persistent_history())
_total_hist_n = _session_hist_n + _persistent_hist_n

_setting_sum = f"{st.session_state.get('num_songs', 15)} 首"
if not is_guest_mode():
    _setting_sum += f" · 新藝人 {st.session_state.get('new_artist_ratio', 70)}%"

with st.expander(f"⚙️ 推薦歌曲數　·　{_setting_sum}", expanded=False, key="exp_songs"):
    if is_guest_mode():
        num_songs = st.slider(
            "推薦歌曲數量", min_value=5, max_value=30, value=15, step=1, key="num_songs",
        )
        new_artist_ratio = 70
    else:
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
                help="0% = 全部從你熟悉的藝人推｜70% = 平衡｜100% = 完全沒接觸過的新藝人",
            )

    st.markdown("---")
    if _total_hist_n > 0 and not is_guest_mode():
        st.caption(
            f"🧠 已記住推薦過的 **{_total_hist_n}** 首歌"
            f"（本次 {_session_hist_n}・過往 {_persistent_hist_n}），生成時會自動避開。"
        )
    elif is_guest_mode():
        st.caption("🧠 訪客模式：推薦歷史僅在本次瀏覽期間有效，關掉分頁就重置。")
    elif _has_scope("playlist-read-private"):
        st.caption("🧠 尚未有推薦歷史。每次生成後會記住，跨 session 都不重複推薦。")
    else:
        st.caption("🧠 想跨 session 記住推薦歷史？請從側邊欄登出後重新登入授權。")

    if st.button("🗑 清除推薦歷史", disabled=_total_hist_n == 0):
        st.session_state["recommend_history"] = []
        if not is_guest_mode():
            try:
                n = clear_persistent_history()
                if n > 0:
                    st.toast(f"已清除 {n} 首過往推薦歷史")
            except Exception:
                st.toast("⚠️ 清除 Spotify 歷史歌單失敗，過往推薦歷史可能仍保留")
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

with st.expander(f"🎵 音樂偏好　·　{_music_sum}", expanded=False, key="exp_music"):
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
        "🎤 想聽哪些歌手的歌？（用逗號分隔）",
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

with st.expander(f"😊 現在的心情　·　{_mood_sum}", expanded=False, key="exp_mood"):
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

with st.expander(f"🧠 關於你　·　{_traits_sum}", expanded=False, key="exp_traits"):
    st.caption("選填。不同性格／星座的音樂偏好取向不太一樣，AI 會納入考量。")
    mbti = st.selectbox("MBTI 性格類型", MBTI_TYPES, key="mbti")
    col_bt, col_zd = st.columns(2)
    with col_bt:
        blood_type = st.selectbox("血型", BLOOD_TYPE_OPTIONS, key="blood_type")
    with col_zd:
        zodiac = st.selectbox("星座", ZODIAC_OPTIONS, key="zodiac")

# ══ 把生成按鈕填回上方預留的位置 ═════════════════════════
_clicked = generate_slot.button(
    "✨ 生成推薦歌單", type="primary", use_container_width=True, key="btn_generate"
)
if _total_hist_n > 0:
    generate_slot.caption(f"🧠 已記住推薦過的 {_total_hist_n} 首歌，這次會自動避開。")

if _clicked:
    # 清空舊結果
    for k in ("found", "context_interp"):
        st.session_state.pop(k, None)

    if not auto_ctx and not text_ctx.strip() and not uploaded:
        st.error("請至少啟用自動偵測、輸入文字，或上傳圖片其中一個。")
    else:
        context_parts = []

        # 進度顯示在生成按鈕正下方（跟著 container 走，不會掉到頁面底部）
        status_col, _ = generate_slot.columns([1, 1])
        with status_col:
            with st.status("準備中...", expanded=True) as status:
                profile = None
                if is_guest_mode():
                    st.write("🎶 訪客模式：不讀取個人資料")
                else:
                    st.write("🔗 讀取 Spotify 聆聽資料...")
                    _sp_error = None
                    for _attempt in range(3):
                        try:
                            profile = fetch_user_profile()
                            st.write(f"✅ 已讀取：{st.session_state.get('user_display_name', 'Spotify 用戶')}")
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
                    st.write("🌍 偵測位置與天氣...")
                    try:
                        ctx = fetch_auto_context()
                        context_parts.append(f"環境情境：{ctx}")
                        st.write(f"📍 {ctx}")
                    except Exception as e:
                        st.warning(f"自動偵測失敗：{e}")

                if uploaded:
                    st.write("🖼️ 分析圖片氛圍...")
                    try:
                        if uploaded.size > 10 * 1024 * 1024:
                            st.warning(f"圖片過大（{uploaded.size / 1024 / 1024:.1f} MB），請上傳 10 MB 以內的圖片。")
                        else:
                            img_bytes = uploaded.read()
                            mime = uploaded.type or "image/jpeg"
                            img_ctx = analyze_image(_gemini_key(), img_bytes, mime)
                            context_parts.append(f"圖片分析：{img_ctx}")
                            st.write(f"🎨 {img_ctx}")
                    except Exception as e:
                        st.warning(f"圖片分析失敗：{e}")

                if text_ctx.strip():
                    context_parts.append(f"文字描述：{text_ctx.strip()}")
                    st.write(f"💬 文字情境已加入")

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
                lang_msg = "、".join(languages) if languages else "不限"
                genre_msg = "、".join(genres) if genres else "不限"
                _ratio_msg = "" if is_guest_mode() else f"新藝人 {new_artist_ratio}%・"
                st.write(
                    f"🤖 Gemini 生成 {num_songs} 首推薦中"
                    f"（{_ratio_msg}語言：{lang_msg}・曲風：{genre_msg}"
                    f"・避開過往 {len(history)} 首）..."
                )
                try:
                    result = get_recommendations(
                        _gemini_key(),
                        profile, "\n".join(context_parts), num_songs, new_artist_ratio, user_traits,
                        languages=languages or None,
                        genres=genres or None,
                        history=history or None,
                        fav_artists=fav_artists,
                    )
                except Exception as e:
                    st.error(f"推薦生成失敗：{e}")
                    st.stop()

                # 在 Spotify 搜尋之前先把 LLM 輸出做一次去重（依 title+artist）
                raw_recs = result.get("recommendations", [])
                pre_dedupe_n = len(raw_recs)
                seen_rec: set[tuple[str, str]] = set()
                unique_recs = []
                for rec in raw_recs:
                    k = (_norm(rec.get("title", "")), _norm(rec.get("artist", "")))
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
                    st.write(f"🔍 Spotify 搜尋歌曲...（{len(unique_recs)}/{pre_dedupe_n} 首去重後，並行搜尋）")
                    _search_token = _get_search_token()
                else:
                    st.write(f"⚠️ 未設定 Spotify API，跳過搜尋（{len(unique_recs)} 首）")

                if _search_token:
                    search_results = _search_tracks_parallel(unique_recs, _search_token)
                else:
                    search_results = [None] * len(unique_recs)

                found = []
                for rec, r in zip(unique_recs, search_results):
                    if r:
                        r["reason"] = rec["reason"]
                        found.append(r)
                    else:
                        _search_q = quote(f"{rec['title']} {rec['artist']}", safe="")
                        found.append({
                            "name": rec["title"],
                            "artist": rec["artist"],
                            "album": "",
                            "url": f"https://open.spotify.com/search/{_search_q}",
                            "uri": None,
                            "cover": "",
                            "reason": rec["reason"],
                            "_no_spotify": True,
                        })

                # 後處理：去重 + 同藝人最多 N 首 + 排除歷史
                found = dedupe_tracks(found, history=history, profile=profile, new_ratio=new_artist_ratio)

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

                status.update(label=f"✅ 完成！找到 {len(found)} 首推薦", state="complete")

        # 結果寫入 session_state，讓「加入歌單」按鈕能存取
        st.session_state.found = found
        st.session_state.context_interp = result.get("context_interpretation", "")
        # 強制重跑，讓頁面頂端的 _hist_n 讀到剛存入的歷史計數
        st.rerun()


# ── 顯示結果（從 session_state 讀取，這樣即使重跑也不會消失）─────────
if "found" in st.session_state and st.session_state.found:
    found = st.session_state.found

    if st.session_state.context_interp:
        st.markdown(
            styles.context_interpretation_html(st.session_state.context_interp),
            unsafe_allow_html=True,
        )

    # 加入 Spotify 歌單按鈕（訪客模式隱藏）
    save_clicked = False
    if not is_guest_mode():
        save_col1, save_col2 = st.columns([3, 1])
        with save_col1:
            playlist_name = st.text_input(
                "歌單名稱",
                value=f"AI Discovery {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                label_visibility="collapsed",
            )
        with save_col2:
            save_clicked = st.button("💾 加入 Spotify", type="primary", use_container_width=True)

    if save_clicked:
        with st.spinner("建立歌單並寫入 Spotify..."):
            try:
                uris = [t["uri"] for t in found if t.get("uri")]
                pl = create_playlist_with_tracks(playlist_name, uris)
                st.success(f"✅ 歌單建立成功！[在 Spotify 開啟]({pl['external_urls']['spotify']})")
            except Exception as e:
                err_msg = str(e)
                if "403" in err_msg or "Forbidden" in err_msg:
                    st.error("❌ Spotify 寫入被拒絕（403 Forbidden）")
                    with st.expander("📖 為什麼會這樣？怎麼解決？", expanded=True):
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

    st.markdown(styles.results_header_html(len(found)), unsafe_allow_html=True)
    view_col, slider_col = st.columns([2, 3])
    with view_col:
        view_mode = st.radio(
            "顯示方式",
            options=["條列式", "網格"],
            index=1,
            horizontal=True,
            label_visibility="collapsed",
        )
    with slider_col:
        if view_mode == "網格":
            cols_per_row = st.slider("每列幾首", min_value=3, max_value=10, value=5, step=1)

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
                                styles.track_card_html(card_track, idx),
                                unsafe_allow_html=True,
                            )
                            btn_label = "🔍 搜尋" if track.get("_no_spotify") else "▶ Spotify"
                            st.link_button(btn_label, track["url"], use_container_width=True)
    else:
        for i, track in enumerate(found):
            st.markdown(
                styles.track_list_html(track, i),
                unsafe_allow_html=True,
            )
            btn_label = "🔍 搜尋" if track.get("_no_spotify") else "▶ Spotify"
            st.link_button(btn_label, track["url"], use_container_width=True)

    # ── 複製 / 分享到 LINE ──────────────────────────────────
    st.divider()

    # 組合可分享的純文字（在欄位外先計算，不渲染任何元件）
    _ctx = st.session_state.get("context_interp", "")
    _lines = ["🎵 Spotify Personal Discovery — AI 推薦歌單"]
    if _ctx:
        _lines += [f"情境：{_ctx}", ""]
    for _i, _t in enumerate(found, 1):
        _lines.append(f"{_i}. {_t['name']} — {_t['artist']}")
        _lines.append(f"   💡 {_t['reason']}")
        if _t.get("url"):
            _lines.append(f"   ▶ {_t['url']}")
        _lines.append("")
    _share_text = "\n".join(_lines).strip()

    # ── 複製歌單 ＋ 分享到 IG 限時動態（左右並排）──────────
    st.divider()
    share_col, ig_col = st.columns([1, 1], gap="large")

    with share_col:
        st.subheader("📋 複製或分享歌單")
        st.caption("點擊右上角複製圖示即可一鍵複製（含 Spotify 連結）")
        st.code(_share_text, language=None)

    with ig_col:
        st.subheader("📲 分享到 IG 限時動態")
        st.caption("生成 1080×1920 的 Wrapped 風格圖卡，色彩每次隨機，可直接下載發到 IG Story")
        share_mode = st.radio(
            "圖卡模式",
            options=["單張總合卡", "多張分頁（4 張）"],
            horizontal=True,
            key="share_mode",
        )
        if st.button("🎨 生成分享圖", use_container_width=True, key="gen_share"):
            seed = str(time.time())
            _tz_sec = st.session_state.get("geo_tz_offset", 28800)
            _local_now = datetime.now(timezone(timedelta(seconds=_tz_sec)))
            with st.spinner("正在生成圖卡..."):
                ctx_interp = st.session_state.get("context_interp", "")
                if share_mode == "單張總合卡":
                    img, palette_name = share_card.generate_single(found, ctx_interp, seed=seed, local_now=_local_now)
                    st.session_state["share_images"] = [("總合卡", img)]
                else:
                    slides, palette_name = share_card.generate_deck(found, ctx_interp, seed=seed, local_now=_local_now)
                    st.session_state["share_images"] = slides
                st.session_state["share_palette"] = palette_name

        if "share_images" in st.session_state and st.session_state["share_images"]:
            share_images = st.session_state["share_images"]
            st.info(f"🎨 本次色系：**{st.session_state['share_palette']}**　·　不喜歡可再按一次生成換色")
            if len(share_images) == 1:
                label, img = share_images[0]
                st.image(img, width=300)
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                st.download_button(
                    "💾 下載 PNG",
                    data=buf.getvalue(),
                    file_name=f"ai-discovery-{datetime.now().strftime('%Y%m%d-%H%M')}.png",
                    mime="image/png",
                    use_container_width=True,
                    type="primary",
                )
                st.caption("下載後在 IG 限時動態選擇此圖即可上傳")
            else:
                thumb_cols = st.columns(len(share_images))
                for i, (label, img) in enumerate(share_images):
                    with thumb_cols[i]:
                        st.image(img, use_container_width=True)
                        st.caption(f"**{i + 1}. {label}**")
                        buf = io.BytesIO()
                        img.save(buf, format="PNG")
                        st.download_button(
                            "💾 下載",
                            data=buf.getvalue(),
                            file_name=f"ai-discovery-{i+1}-{label}-{datetime.now().strftime('%Y%m%d-%H%M')}.png",
                            mime="image/png",
                            use_container_width=True,
                            key=f"dl_share_{i}",
                        )
