"""
Spotify Personal Discovery - Web UI
"""

import json
import mimetypes
import os
import random
import tempfile
from datetime import datetime
from pathlib import Path

import io

import requests
import streamlit as st
from dotenv import load_dotenv
import spotipy
from spotipy.oauth2 import SpotifyOAuth, SpotifyClientCredentials
from spotipy.cache_handler import MemoryCacheHandler
from google import genai
from google.genai import types
import styles

import share_card

load_dotenv()


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

GEMINI_MODEL = "gemini-2.5-flash"
SCOPES = (
    "user-top-read user-read-recently-played user-library-read "
    "playlist-read-private playlist-modify-public playlist-modify-private"
)

# 跨 session 歷史（存在 Spotify 私人歌單裡）
HISTORY_PLAYLIST_NAME = "🤖 AI Discovery History (請勿手動刪除)"

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

ACTIVITY_OPTIONS = [
    "讀書", "工作", "通勤", "開車", "運動", "散步",
    "放鬆", "聚會", "煮飯", "做家事", "睡前", "剛起床",
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

MAX_TRACKS_PER_ARTIST = 2  # 同一次推薦中，同藝人最多出現幾首
HISTORY_KEEP = 200          # session 內保留的歷史推薦上限

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


# ── Spotify 多用戶 OAuth ────────────────────────────────
def _get_auth_manager() -> SpotifyOAuth:
    """每次 call 都新建一個 OAuth manager，搭配 MemoryCacheHandler 確保多用戶獨立。"""
    return SpotifyOAuth(
        client_id=_get_credential("SPOTIFY_CLIENT_ID"),
        client_secret=_get_credential("SPOTIFY_CLIENT_SECRET"),
        redirect_uri=_get_credential("SPOTIFY_REDIRECT_URI"),
        scope=SCOPES,
        cache_handler=MemoryCacheHandler(),  # 不寫 .cache 檔，避免多用戶污染
        open_browser=False,
        show_dialog=False,
    )


def consume_oauth_callback() -> None:
    """頁面載入時呼叫：如果 URL 含有 ?code=xxx，交換 token 並寫入 session。"""
    if "spotify_token" in st.session_state:
        return
    code = st.query_params.get("code")
    if not code:
        return
    try:
        auth_manager = _get_auth_manager()
        token_info = auth_manager.get_access_token(code, as_dict=True, check_cache=False)
        st.session_state["spotify_token"] = token_info
    except Exception as e:
        st.error(f"Spotify 授權失敗：{e}")
    finally:
        # 清掉 URL 上的 code，避免重新整理時重複交換
        try:
            st.query_params.clear()
        except Exception:
            pass


def is_authenticated() -> bool:
    return "spotify_token" in st.session_state


def logout() -> None:
    for k in (
        "spotify_token",
        "user_profile",
        "user_display_name",
        "found", "not_found", "context_interp",
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


def _get_guest_spotify_client() -> spotipy.Spotify | None:
    """Client-credentials flow for search without user login."""
    cid = _get_credential("SPOTIFY_CLIENT_ID")
    csec = _get_credential("SPOTIFY_CLIENT_SECRET")
    if not cid or not csec:
        return None
    try:
        return spotipy.Spotify(auth_manager=SpotifyClientCredentials(
            client_id=cid, client_secret=csec,
        ))
    except Exception:
        return None


def show_login_required() -> None:
    """未登入時顯示的歡迎/登入頁：Spotify 登入 + 訪客模式 + BYOK 設定。"""

    # ── Hero ──
    st.markdown(styles.login_hero_html(), unsafe_allow_html=True)

    # ── 方式一：Spotify 登入 ──
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
            type="primary",
            use_container_width=True,
        )
    else:
        st.warning("尚未設定 Spotify API Keys，請在下方「自訂 API Keys」區填入後即可登入。")

    st.caption("🔒 Token 只存在瀏覽器分頁記憶體，關掉就消失。")

    # ── 方式二：訪客模式 ──
    st.markdown(styles.divider_html(), unsafe_allow_html=True)
    st.markdown(styles.login_guest_card(), unsafe_allow_html=True)

    has_gemini = bool(_get_credential("GEMINI_API_KEY"))
    if has_gemini:
        if st.button("🎶 不登入，直接推薦", type="primary", use_container_width=True):
            enter_guest_mode()
    else:
        st.warning("訪客模式需要 Gemini API Key，請在下方「自訂 API Keys」區填入。")

    # ── BYOK 設定區 ──
    st.markdown(styles.divider_html(), unsafe_allow_html=True)
    _render_api_key_settings(expanded=not has_spotify_creds and not has_gemini)


def _render_api_key_settings(expanded: bool = False) -> None:
    """渲染 API Keys 設定區（登入頁 + sidebar 共用）。"""
    default_redirect = _get_env("SPOTIFY_REDIRECT_URI") or "http://127.0.0.1:8501/"

    with st.expander("⚙️ 自訂 API Keys — 讓所有人都能使用", expanded=expanded):

        # ── 說明標語 ──
        st.markdown(
            "<div style=\"font-family:'Nunito','Noto Sans TC',sans-serif;font-size:0.92rem;"
            "color:#2D1B4E;line-height:1.7;padding:4px 0 8px 0\">"
            "填入自己的 API Keys 後，你就<strong>不受 Spotify 用戶數限制</strong>，"
            "也能使用自己的 Gemini 免費額度。每個人申請都只需要 <strong>3-5 分鐘</strong>。"
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

        st.markdown("<div style='margin-top:12px'></div>", unsafe_allow_html=True)

        # ── Gemini 步驟卡 ──
        st.markdown(
            styles.byok_gemini_section_html(),
            unsafe_allow_html=True,
        )

        # ── Gemini 輸入欄 ──
        st.text_input(
            "Gemini API Key",
            key="custom_GEMINI_API_KEY",
            type="password",
            placeholder="貼上你的 Gemini API Key",
        )

        # ── 隱私說明 ──
        st.markdown(styles.byok_privacy_badge_html(), unsafe_allow_html=True)


def get_spotify_client() -> spotipy.Spotify:
    """取得 Spotify client。呼叫前必須 is_authenticated() == True。Token 過期時自動 refresh。"""
    auth_manager = _get_auth_manager()
    token_info = st.session_state["spotify_token"]
    if auth_manager.is_token_expired(token_info):
        token_info = auth_manager.refresh_access_token(token_info["refresh_token"])
        st.session_state["spotify_token"] = token_info
    return spotipy.Spotify(auth=token_info["access_token"])


def fetch_user_profile() -> dict:
    """讀使用者聆聽資料；以 user_id 為 key 快取在 session_state（per-user safe）。"""
    sp = get_spotify_client()
    user = sp.current_user()
    cache_key = f"user_profile::{user['id']}"
    if cache_key in st.session_state:
        return st.session_state[cache_key]

    top_tracks_medium = sp.current_user_top_tracks(limit=20, time_range="medium_term")["items"]
    top_tracks_short  = sp.current_user_top_tracks(limit=10, time_range="short_term")["items"]
    top_artists       = sp.current_user_top_artists(limit=15, time_range="medium_term")["items"]
    recently_played   = sp.current_user_recently_played(limit=50)["items"]
    saved_tracks = (
        sp.current_user_saved_tracks(limit=50, offset=0)["items"]
        + sp.current_user_saved_tracks(limit=50, offset=50)["items"]
    )

    def track_str(t):
        return f"{t['name']} - {', '.join(a['name'] for a in t['artists'])}"

    all_tracks = (
        top_tracks_medium + top_tracks_short
        + [i["track"] for i in recently_played]
        + [i["track"] for i in saved_tracks]
    )
    profile = {
        "top_tracks_recent":  [track_str(t) for t in top_tracks_short],
        "top_tracks_overall": [track_str(t) for t in top_tracks_medium],
        "top_artists":  [a["name"] for a in top_artists],
        "top_genres":   list({g for a in top_artists for g in a.get("genres", [])}),
        "heard_titles":  sorted({t["name"] for t in all_tracks}),
        "heard_artists": sorted({a["name"] for t in all_tracks for a in t["artists"]}),
    }
    st.session_state[cache_key] = profile
    return profile


def create_playlist_with_tracks(playlist_name: str, track_uris: list[str]) -> dict:
    """建立新歌單並加入曲目，回傳歌單資訊"""
    sp = get_spotify_client()
    # 新 endpoint：POST /me/playlists（舊的 /users/{id}/playlists 已被移除）
    playlist = sp._post(
        "me/playlists",
        payload={
            "name": playlist_name,
            "public": False,
            "description": f"由 Spotify Personal Discovery 自動生成・{datetime.now().strftime('%Y-%m-%d %H:%M')}",
        },
    )
    # 新 endpoint：POST /playlists/{id}/items（舊的 /tracks 已被改名）
    for i in range(0, len(track_uris), 100):
        sp._post(
            f"playlists/{playlist['id']}/items",
            payload={"uris": track_uris[i:i + 100]},
        )
    return playlist


def search_track(title: str, artist: str) -> dict | None:
    if is_authenticated():
        sp = get_spotify_client()
    else:
        sp = _get_guest_spotify_client()
    if sp is None:
        return None
    results = sp.search(q=f"track:{title} artist:{artist}", type="track", limit=1)
    items = results["tracks"]["items"]
    if not items:
        results = sp.search(q=f"{title} {artist}", type="track", limit=1)
        items = results["tracks"]["items"]
    if not items:
        return None
    t = items[0]
    return {
        "name": t["name"],
        "artist": ", ".join(a["name"] for a in t["artists"]),
        "album": t["album"]["name"],
        "url": t["external_urls"]["spotify"],
        "uri": t["uri"],
        "cover": t["album"]["images"][1]["url"] if len(t["album"]["images"]) > 1 else t["album"]["images"][0]["url"],
    }


# ── Context helpers ───────────────────────────────────────
def get_time_of_day(hour: int) -> str:
    if 5 <= hour < 9:  return "清晨"
    if 9 <= hour < 12: return "上午"
    if 12 <= hour < 14: return "中午"
    if 14 <= hour < 18: return "下午"
    if 18 <= hour < 21: return "傍晚"
    if 21 <= hour < 24: return "晚上"
    return "深夜"


def fetch_auto_context() -> str:
    # 取得使用者真實 IP（雲端部署時 Streamlit 伺服器 IP 會是美國）
    try:
        forwarded = st.context.headers.get("X-Forwarded-For", "")
        client_ip = forwarded.split(",")[0].strip() if forwarded else ""
    except Exception:
        client_ip = ""
    ip_segment = f"/{client_ip}" if client_ip else ""

    # ipwho.is：免費、HTTPS、無需 API key
    geo = requests.get(f"https://ipwho.is{ip_segment}", timeout=10).json()
    city = geo.get("city", "未知"); country = geo.get("country", "")
    lat = geo.get("latitude"); lon = geo.get("longitude")
    tz_offset_sec = geo.get("timezone", {}).get("offset", 28800)  # 預設 UTC+8
    st.session_state["geo_tz_offset"] = tz_offset_sec

    w = requests.get("https://api.open-meteo.com/v1/forecast", params={
        "latitude": lat, "longitude": lon,
        "current": "temperature_2m,weather_code,wind_speed_10m,is_day",
        "timezone": "auto",
    }, timeout=10).json()["current"]

    desc = WMO_CODES.get(w["weather_code"], "")
    now = datetime.now()
    time_label = get_time_of_day(now.hour)

    return (
        f"{now.strftime('%H:%M')}（{time_label}）｜"
        f"{city}, {country}｜"
        f"{desc} {w['temperature_2m']}°C"
    )


def analyze_image(image_bytes: bytes, mime: str) -> str:
    client = genai.Client(api_key=_get_credential("GEMINI_API_KEY"))
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=[
            types.Part.from_bytes(data=image_bytes, mime_type=mime),
            "請用音樂氛圍的角度分析這張圖片，輸出 JSON：{\"mood\":\"整體情緒\",\"atmosphere\":\"氛圍描述（30字內）\",\"tempo_suggestion\":\"slow/mid/upbeat/dance\",\"energy\":能量1-10,\"keywords\":[\"關鍵字1\",\"關鍵字2\",\"關鍵字3\"]}。只輸出JSON。",
        ],
    )
    text = response.text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"): text = text[4:]
    d = json.loads(text.strip())
    return f"情緒：{d['mood']}｜氛圍：{d['atmosphere']}｜節奏：{d['tempo_suggestion']}｜能量：{d['energy']}/10"


# ── Recommendation ────────────────────────────────────────
def build_prompt(
    profile: dict,
    context: str,
    num_songs: int = 15,
    new_ratio: int = 70,
    user_traits: str = "",
    languages: list[str] | None = None,
    genres: list[str] | None = None,
    history: list[dict] | None = None,
    fav_artists: list[str] | None = None,
) -> str:
    heard_titles_str  = "\n".join(f"- {t}" for t in profile["heard_titles"])
    heard_artists_str = ", ".join(profile["heard_artists"])
    traits_block = f"\n## 使用者個人特質與當下狀態\n{user_traits}\n" if user_traits else ""

    new_count = round(num_songs * new_ratio / 100)
    familiar_count = num_songs - new_count

    if new_ratio == 100:
        mode_block = f"""## 推薦組合：全部新藝人 🆕（{num_songs} 首）
**絕對規則：所有 {num_songs} 首推薦都必須是「已接觸藝人」清單中【完全沒有出現】的藝人。**
- 禁止推薦上方藝人清單中的任何藝人（連他們的冷門歌都不行）
- 偏好 Spotify 熱門度 < 50 的小眾藝人、獨立廠牌、地下音樂人
- 推薦前請逐項檢查：「這個藝人在已接觸清單裡嗎？」有的話換一個"""
    elif new_ratio == 0:
        mode_block = f"""## 推薦組合：全部熟悉藝人 💛（{num_songs} 首）
- 可以從「已接觸藝人」清單中推薦你熟悉或應該熟悉的曲目
- 包括深軌、B-side、合輯版本、甚至他們的熱門歌
- 重點是「在你舒適圈內」找符合情境的歌"""
    else:
        mode_block = f"""## 推薦組合（嚴格遵守數量）
- **{new_count} 首**必須是「已接觸藝人」清單中【完全沒有出現】的全新藝人
- **{familiar_count} 首**可以是已接觸藝人的冷門深軌（不能是熱門主打歌）
- 比例：{new_ratio}% 新藝人 / {100 - new_ratio}% 熟悉藝人
- 請逐首檢查並確認比例正確"""

    # 語言偏好
    if languages:
        lang_block = (
            "## 語言偏好（必須遵守）\n"
            f"- 只推薦以下語言的歌：{', '.join(languages)}\n"
            "- 「華語」表示國語/中文歌；「其他語言」代表上述未列的小眾語種（如泰語、印尼語、葡語等）\n"
            "- 不要推薦清單外語言的歌\n"
        )
    else:
        lang_block = "## 語言偏好\n- 不限語言，鼓勵跨語種混搭（英、華、韓、日、法、西、葡⋯）\n"

    # 曲風偏好
    if genres:
        genre_block = (
            "## 曲風偏好（必須遵守）\n"
            f"- 只推薦以下曲風的歌：{', '.join(genres)}\n"
            "- 曲風可廣義解讀子分支（例：選 Pop 可包含 Synth-pop、Dream-pop、City-pop 等；選 Rock 可包含 Indie Rock、Post-rock、Shoegaze 等）\n"
            "- 不要混入清單外的曲風\n"
        )
    else:
        genre_block = "## 曲風偏好\n- 不限曲風，依情境自由選擇\n"

    # 指定歌手偏好
    if fav_artists:
        fav_block = (
            "## 使用者指定歌手（高優先）\n"
            f"- 使用者特別想聽這些歌手：{', '.join(fav_artists)}\n"
            "- 請盡量從這些歌手中挑選歌曲（至少一半推薦來自這裡），但仍要避開已聽清單\n"
            "- 若這些歌手的歌與情境不符，可部分推薦其他符合情境的歌手\n"
        )
    else:
        fav_block = ""

    # 歷史推薦（避免重複）
    if history:
        recent = history[-HISTORY_KEEP:]
        history_str = "\n".join(f"- {h['title']} - {h['artist']}" for h in recent)
        recent_artists = sorted({h["artist"] for h in recent[-60:]})
        history_block = (
            "## 本次 session 已推薦過的歌曲（絕對禁止再次推薦，含這些歌名 + 藝人組合）\n"
            f"{history_str}\n"
            "\n## 最近推薦過的藝人（請優先換新藝人，避免反覆推同一群人）\n"
            f"{', '.join(recent_artists)}\n"
        )
    else:
        history_block = ""

    return f"""你是專業音樂推薦 AI。根據使用者口味與情境，推薦 {num_songs} 首符合情境的歌。

## 使用者口味
喜愛藝人：{", ".join(profile["top_artists"])}
風格：{", ".join(profile["top_genres"][:8]) if profile["top_genres"] else "pop, indie pop"}
{traits_block}
{fav_block}## 當下情境（最高優先）
{context}

{lang_block}
{genre_block}
## 已聽過的歌曲（絕對禁止推薦這些歌名）
{heard_titles_str}

## 已接觸的藝人清單
{heard_artists_str}

{history_block}
{mode_block}

## 多樣性硬性規則（必須遵守）
- 同一個藝人在這 {num_songs} 首推薦中**最多出現 {MAX_TRACKS_PER_ARTIST} 首**
- 每首歌的 title + artist 組合必須唯一，不能重複
- 推薦完請自我檢查一次：是否有藝人超過 {MAX_TRACKS_PER_ARTIST} 首？是否有重複曲目？

## 其他規則
- 年代多樣化（不要全是同一年的歌）

只輸出 JSON：
{{"context_interpretation":"情境理解（一句話）","recommendations":[{{"title":"歌名","artist":"藝人","reason":"理由20字內"}}]}}"""


def build_guest_prompt(
    context: str,
    num_songs: int = 15,
    user_traits: str = "",
    languages: list[str] | None = None,
    genres: list[str] | None = None,
    history: list[dict] | None = None,
    fav_artists: list[str] | None = None,
) -> str:
    """訪客模式 prompt：沒有個人聆聽資料，純靠情境推薦。"""
    if languages:
        lang_block = (
            "## 語言偏好（必須遵守）\n"
            f"- 只推薦以下語言的歌：{', '.join(languages)}\n"
            "- 「華語」表示國語/中文歌；「其他語言」代表上述未列的小眾語種\n"
        )
    else:
        lang_block = "## 語言偏好\n- 不限語言，鼓勵跨語種混搭\n"

    if genres:
        genre_block = (
            "## 曲風偏好（必須遵守）\n"
            f"- 只推薦以下曲風的歌：{', '.join(genres)}\n"
            "- 曲風可廣義解讀子分支\n"
        )
    else:
        genre_block = "## 曲風偏好\n- 不限曲風，依情境自由選擇\n"

    if history:
        recent = history[-HISTORY_KEEP:]
        history_str = "\n".join(f"- {h['title']} - {h['artist']}" for h in recent)
        history_block = (
            "## 本次已推薦過的歌曲（絕對禁止再次推薦）\n"
            f"{history_str}\n"
        )
    else:
        history_block = ""

    traits_block = f"\n## 使用者個人特質與當下狀態\n{user_traits}\n" if user_traits else ""

    # 指定歌手偏好
    if fav_artists:
        fav_block = (
            "## 使用者指定歌手（高優先）\n"
            f"- 使用者特別想聽這些歌手：{', '.join(fav_artists)}\n"
            "- 請盡量從這些歌手中挑選歌曲（至少一半推薦來自這裡）\n"
            "- 若這些歌手的歌與情境不符，可部分推薦其他符合情境的歌手\n"
        )
    else:
        fav_block = ""

    return f"""你是專業音樂推薦 AI。根據使用者描述的情境與偏好，推薦 {num_songs} 首歌。

注意：這位使用者沒有提供個人聆聽紀錄，所以請完全根據情境推薦。
{traits_block}
{fav_block}## 當下情境（最高優先）
{context}

{lang_block}
{genre_block}
{history_block}
## 多樣性硬性規則（必須遵守）
- 同一個藝人最多出現 {MAX_TRACKS_PER_ARTIST} 首
- 每首歌的 title + artist 組合必須唯一
- 年代多樣化
- 推薦的歌必須是在 Spotify 上找得到的真實歌曲

只輸出 JSON：
{{"context_interpretation":"情境理解（一句話）","recommendations":[{{"title":"歌名","artist":"藝人","reason":"理由20字內"}}]}}"""


def _parse_json_robust(text: str) -> dict:
    """Parse JSON from Gemini response with multiple fallback strategies."""
    import re
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Fallback: regex-extract each field individually
    result = {"context_interpretation": "", "recommendations": []}
    ci = re.search(r'"context_interpretation"\s*:\s*"((?:[^"\\]|\\.)*)"', text)
    if ci:
        result["context_interpretation"] = ci.group(1)
    for m in re.finditer(
        r'\{"title"\s*:\s*"((?:[^"\\]|\\.)*)"\s*,\s*"artist"\s*:\s*"((?:[^"\\]|\\.)*)"\s*,\s*"reason"\s*:\s*"((?:[^"\\]|\\.)*)"\s*\}',
        text,
    ):
        result["recommendations"].append(
            {"title": m.group(1), "artist": m.group(2), "reason": m.group(3)}
        )
    if result["recommendations"]:
        return result
    raise json.JSONDecodeError("Cannot parse Gemini response", text, 0)


def get_recommendations(
    profile: dict | None,
    context: str,
    num_songs: int = 15,
    new_ratio: int = 70,
    user_traits: str = "",
    languages: list[str] | None = None,
    genres: list[str] | None = None,
    history: list[dict] | None = None,
    fav_artists: list[str] | None = None,
) -> dict:
    import time
    client = genai.Client(api_key=_get_credential("GEMINI_API_KEY"))
    if profile is None:
        prompt = build_guest_prompt(
            context, num_songs, user_traits,
            languages=languages, genres=genres, history=history,
            fav_artists=fav_artists,
        )
    else:
        prompt = build_prompt(
            profile, context, num_songs, new_ratio, user_traits,
            languages=languages, genres=genres, history=history,
            fav_artists=fav_artists,
        )

    def _call_gemini(with_mime: bool) -> str:
        cfg = types.GenerateContentConfig(response_mime_type="application/json") if with_mime else None
        kwargs = {"model": GEMINI_MODEL, "contents": prompt}
        if cfg:
            kwargs["config"] = cfg
        resp = client.models.generate_content(**kwargs)
        return (resp.text or "").strip()

    # 最多重試 3 次（含 503 過載）
    for attempt in range(3):
        try:
            text = _call_gemini(with_mime=True)
            if not text:
                text = _call_gemini(with_mime=False)
            if text:
                return _parse_json_robust(text)
        except Exception as e:
            err = str(e)
            is_503 = "503" in err or "UNAVAILABLE" in err
            if is_503 and attempt < 2:
                time.sleep(8 * (attempt + 1))  # 8s, 16s
                continue
            if attempt == 2:
                raise
    raise ValueError("Gemini 回傳空回應，請稍後再試")


def _norm(s: str) -> str:
    return (s or "").strip().lower()


def dedupe_tracks(
    tracks: list[dict],
    history: list[dict] | None = None,
    profile: dict | None = None,
    new_ratio: int = 70,
) -> list[dict]:
    """同次推薦內以 (title, artist) 去重，且同藝人最多 MAX_TRACKS_PER_ARTIST 首；
    同時排除 session 歷史；並依使用者 profile 硬性過濾：
      - 任何模式下：歌名出現在 heard_titles 直接排除
      - new_ratio == 100：藝人（含合作藝人）出現在 heard_artists 直接排除
    """
    history = history or []
    seen_pairs: set[tuple[str, str]] = {
        (_norm(h["title"]), _norm(h["artist"])) for h in history
    }
    heard_titles_norm: set[str] = set()
    heard_artists_norm: set[str] = set()
    if profile:
        heard_titles_norm = {_norm(t) for t in profile.get("heard_titles", [])}
        heard_artists_norm = {_norm(a) for a in profile.get("heard_artists", [])}

    artist_count: dict[str, int] = {}
    deduped: list[dict] = []
    for t in tracks:
        title = t.get("name") or t.get("title") or ""
        artist = t.get("artist") or ""
        key = (_norm(title), _norm(artist))
        if key in seen_pairs:
            continue
        # 硬性過濾：歌名在已聽過清單裡直接排除
        if _norm(title) in heard_titles_norm:
            continue
        ak = _norm(artist)
        all_artists = [a.strip() for a in ak.split(",") if a.strip()]
        primary = all_artists[0] if all_artists else ""
        # 100% 新藝人模式：任一合作藝人在 heard_artists 中就排除
        if new_ratio == 100 and any(a in heard_artists_norm for a in all_artists):
            continue
        if artist_count.get(primary, 0) >= MAX_TRACKS_PER_ARTIST:
            continue
        seen_pairs.add(key)
        artist_count[primary] = artist_count.get(primary, 0) + 1
        deduped.append(t)
    return deduped


# ── 跨 session 歷史（持久化在 Spotify 私人歌單） ────────────
def _has_scope(scope_name: str) -> bool:
    """檢查目前 token 是否含某個 scope。"""
    token = st.session_state.get("spotify_token") or {}
    return scope_name in (token.get("scope") or "")


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
            "description": "Spotify Personal Discovery 自動管理：記錄推薦過的歌曲以避免重複。可以在 App 內按「清除歷史」清空。",
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
        for i in range(0, len(all_uris), 100):
            chunk = [{"uri": u} for u in all_uris[i:i+100]]
            sp._delete(f"playlists/{pid}/tracks", payload={"tracks": chunk})
    except Exception:
        pass
    cache_key = f"persistent_history::{pid}"
    if cache_key in st.session_state:
        st.session_state[cache_key] = []
    return len(all_uris)


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

st.divider()

st.subheader("設定情境")
st.markdown("<div style='margin-top: 1.2rem;'></div>", unsafe_allow_html=True)

# 個人特質區（一次填、session 內沿用）
with st.expander("🧠 關於你（選填，讓 AI 更懂你）", expanded=False):
    mbti = st.selectbox(
        "MBTI 性格類型",
        MBTI_TYPES,
        index=MBTI_TYPES.index(st.session_state.get("mbti", "不指定")),
        help="不同性格類型對音樂的偏好取向不太一樣，AI 會納入考量",
    )
    st.session_state["mbti"] = mbti

    col_bt, col_zd = st.columns(2)
    with col_bt:
        blood_type = st.selectbox(
            "血型",
            BLOOD_TYPE_OPTIONS,
            index=BLOOD_TYPE_OPTIONS.index(st.session_state.get("blood_type", "不指定")),
        )
        st.session_state["blood_type"] = blood_type
    with col_zd:
        zodiac = st.selectbox(
            "星座",
            ZODIAC_OPTIONS,
            index=ZODIAC_OPTIONS.index(st.session_state.get("zodiac", "不指定")),
        )
        st.session_state["zodiac"] = zodiac

st.markdown("<div style='margin-top: 1.2rem;'></div>", unsafe_allow_html=True)
auto_ctx = st.toggle("自動偵測位置與天氣", value=True)
st.caption("啟用時會透過 [ipwho.is](https://ipwho.is) 取得 IP 地理位置，僅用於判斷天氣與時區，不儲存。")

col1, col2 = st.columns(2)

with col1:
    text_ctx = st.text_area(
        "文字描述（選填）",
        placeholder="例如：在咖啡廳讀書、深夜想一個人散步、運動前暖身…",
        height=98,
    )

with col2:
    uploaded = st.file_uploader(
        "上傳情境圖片（選填）",
        type=["jpg", "jpeg", "png", "webp"],
        help="上傳一張能代表你當下心情或環境的照片，最大 10 MB",
    )
    if uploaded:
        st.image(uploaded, use_container_width=True)

# 心情雙軸滑桿
mood_col1, mood_col2 = st.columns(2)
with mood_col1:
    mood_energy = st.slider(
        "活力程度",
        min_value=1, max_value=10, value=5, step=1,
        help="1 = 完全放空｜10 = 精力爆棚",
    )
with mood_col2:
    mood_valence = st.slider(
        "情緒",
        min_value=1, max_value=10, value=5, step=1,
        help="1 = 低落／煩躁｜5 = 平靜｜10 = 愉悅／興奮",
    )

# 活動情境快速選擇
st.markdown("<div style='margin-top: 1.2rem;'></div>", unsafe_allow_html=True)
activity = st.pills(
    "正在做 / 即將做什麼？（選填）",
    options=ACTIVITY_OPTIONS,
    selection_mode="single",
    default=None,
)

# 語言與曲風偏好（多選）
st.markdown("<div style='margin-top: 1.2rem;'></div>", unsafe_allow_html=True)
languages = st.pills(
    "想聽哪些語言的歌？（選填，可複選；不選代表不限）",
    options=LANGUAGE_OPTIONS,
    selection_mode="multi",
    default=None,
    key="lang_pills",
)

st.markdown("<div style='margin-top: 0.8rem;'></div>", unsafe_allow_html=True)
genres = st.pills(
    "想聽哪些曲風？(選填，可複選；不選代表不限)",
    options=GENRE_OPTIONS,
    selection_mode="multi",
    default=None,
    key="genre_pills",
)

st.markdown("<div style='margin-top: 0.8rem;'></div>", unsafe_allow_html=True)
fav_artists_raw = st.text_input(
    "🎤 想聽哪些歌手的歌？（選填，用逗號分隔）",
    key="fav_artists_input",
    placeholder="例：周杰倫, Taylor Swift, NewJeans, 陳奕迅",
    help="填入後 AI 會優先從這些歌手中推薦，同時兼顧你的情境偏好。",
)
# 解析成清單，過濾空白
fav_artists = [a.strip() for a in fav_artists_raw.replace('，', ',').split(',') if a.strip()] or None

st.markdown("<div style='margin-top: 2.4rem;'></div>", unsafe_allow_html=True)
# 隨機投射問題
if "projective_q" not in st.session_state:
    st.session_state["projective_q"] = random.choice(PROJECTIVE_QUESTIONS)

proj_col1, proj_col2 = st.columns([5, 1])
with proj_col1:
    st.markdown(f"**🎲 隨機投射問題（選填）**  \n{st.session_state['projective_q']}")
with proj_col2:
    if st.button("換一題", use_container_width=True):
        current = st.session_state["projective_q"]
        choices = [q for q in PROJECTIVE_QUESTIONS if q != current]
        st.session_state["projective_q"] = random.choice(choices)
        st.session_state["projective_a"] = ""
        st.rerun()

st.markdown("<div style='margin-top: -2.6rem;'></div>", unsafe_allow_html=True)
projective_answer = st.text_input(
    "你的回答",
    key="projective_a",
    placeholder="隨意回答，越具體越好（讓 AI 從中讀出你的當下狀態）",
    label_visibility="collapsed",
)
st.markdown("<div style='margin-top: 1.2rem;'></div>", unsafe_allow_html=True)

if is_guest_mode():
    num_songs = st.slider("推薦歌曲數量", min_value=5, max_value=30, value=15, step=1)
    new_artist_ratio = 70
else:
    col_num, col_mode = st.columns([1, 1])
    with col_num:
        num_songs = st.slider("推薦歌曲數量", min_value=5, max_value=30, value=15, step=1)
    with col_mode:
        new_artist_ratio = st.slider(
            "新藝人佔比",
            min_value=0, max_value=100, value=70, step=10,
            format="%d%%",
            help="0% = 全部從你熟悉的藝人推｜70% = 平衡｜100% = 完全沒接觸過的新藝人",
        )

st.divider()

# 推薦歷史狀態列 + 清除歷史
_session_hist_n = len(st.session_state.get("recommend_history", []))
if is_guest_mode():
    _persistent_hist_n = 0
    _total_hist_n = _session_hist_n
else:
    _persistent_hist = load_persistent_history()
    _persistent_hist_n = len(_persistent_hist)
    _total_hist_n = _session_hist_n + _persistent_hist_n

hist_col1, hist_col2 = st.columns([4, 1])
with hist_col1:
    if _total_hist_n > 0:
        if is_guest_mode():
            st.caption(f"🧠 已記住本次推薦過的 **{_session_hist_n}** 首歌，下次生成會自動避開。")
        else:
            st.caption(
                f"🧠 已記住推薦過的 **{_total_hist_n}** 首歌"
                f"（本次 {_session_hist_n}・過往 {_persistent_hist_n}），下次生成會自動避開。"
            )
    elif is_guest_mode():
        st.caption("🧠 訪客模式：推薦歷史僅在本次瀏覽期間有效。")
    elif _has_scope("playlist-read-private"):
        st.caption("🧠 尚未有推薦歷史。每次生成後會記住，跨 session 都不重複推薦。")
    else:
        st.caption("🧠 想跨 session 記住推薦歷史？請從側邊欄登出後重新登入授權。")
with hist_col2:
    if st.button("🗑 清除歷史", use_container_width=True, disabled=_total_hist_n == 0):
        st.session_state["recommend_history"] = []
        if not is_guest_mode():
            try:
                n = clear_persistent_history()
                if n > 0:
                    st.toast(f"已清除 {n} 首過往推薦歷史")
            except Exception:
                pass
        st.rerun()

# 生成按鈕
if st.button("✨ 生成推薦歌單", type="primary", use_container_width=True):
    # 清空舊結果
    for k in ("found", "not_found", "context_interp"):
        st.session_state.pop(k, None)

    if not auto_ctx and not text_ctx.strip() and not uploaded:
        st.error("請至少啟用自動偵測、輸入文字，或上傳圖片其中一個。")
    else:
        context_parts = []

        status_col, _ = st.columns([1, 1])
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
                                import time; time.sleep(1.5)
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
                            img_ctx = analyze_image(img_bytes, mime)
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
                if activity:
                    traits_parts.append(f"- 正在做：{activity}")
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
                st.write(
                    f"🤖 Gemini 生成 {num_songs} 首推薦中"
                    f"（新藝人 {new_artist_ratio}%・語言：{lang_msg}・曲風：{genre_msg}"
                    f"・避開過往 {len(history)} 首）..."
                )
                try:
                    result = get_recommendations(
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

                _has_spotify = bool(
                    _get_credential("SPOTIFY_CLIENT_ID")
                    and _get_credential("SPOTIFY_CLIENT_SECRET")
                )
                if _has_spotify:
                    st.write(f"🔍 Spotify 搜尋歌曲...（{len(unique_recs)}/{pre_dedupe_n} 首去重後）")
                else:
                    st.write(f"⚠️ 未設定 Spotify API，跳過搜尋（{len(unique_recs)} 首）")

                found = []
                not_found = []
                for rec in unique_recs:
                    if _has_spotify:
                        r = search_track(rec["title"], rec["artist"])
                    else:
                        r = None
                    if r:
                        r["reason"] = rec["reason"]
                        found.append(r)
                    else:
                        found.append({
                            "name": rec["title"],
                            "artist": rec["artist"],
                            "album": "",
                            "url": f"https://open.spotify.com/search/{rec['title']}%20{rec['artist']}",
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
        st.session_state.not_found = not_found
        st.session_state.context_interp = result.get("context_interpretation", "")
        # 強制重跑，讓頁面頂端的 _hist_n 讀到剛存入的歷史計數
        st.rerun()


# ── 顯示結果（從 session_state 讀取，這樣即使重跑也不會消失）─────────
if "found" in st.session_state and st.session_state.found:
    found = st.session_state.found
    not_found = st.session_state.not_found

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
**原因**：Spotify 2024-11 政策變更，對 Development Mode 的新 App 限制了寫入 API。

**三個解決方向**：

1. **檢查 User Management Email**
   到 [Developer Dashboard](https://developer.spotify.com/dashboard) → 你的 App → Settings → User Management，
   確認填的 Email 完全等於你 Spotify 帳號註冊的 Email（到 [Spotify Profile](https://www.spotify.com/account/profile) 查看）。

2. **重新授權 App**
   到 [Spotify Apps 設定](https://www.spotify.com/account/apps) 撤銷你建立的 App 授權，
   然後刪除 `.cache` 重新登入，會強制觸發新的權限授予。

3. **申請 Extended Quota Mode**（最終解法）
   到 Developer Dashboard 你的 App → Extended Quota Mode 申請，
   填寫用途說明後等待 Spotify 審核（通常數天到數週）。
                        """)
                    st.markdown("---")
                    st.markdown("**手動加入歌單的方法**：用下方卡片每首歌的「在 Spotify 開啟」按鈕，在 Spotify 中對歌曲按右鍵 → 加入歌單。")
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

    if not_found:
        with st.expander("Spotify 找不到的推薦"):
            for nf in not_found:
                st.text(f"• {nf}")

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
    share_col, ig_col = st.columns([1, 1])

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
            import time
            from datetime import timezone, timedelta
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
