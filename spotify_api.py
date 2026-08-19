"""
Spotify API 層：OAuth、client、搜尋、歌單、跨 session 歷史。
只在函式被呼叫時才碰 session_state——import 本模組不會執行任何 UI 程式碼。
"""

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import streamlit as st
import spotipy
from spotipy.oauth2 import SpotifyOAuth, SpotifyClientCredentials
from spotipy.cache_handler import MemoryCacheHandler

PERSISTENT_HISTORY_MAX = 500  # 跨 session 歷史歌單保留上限，超過會修剪最舊的


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
    "user-top-read user-read-recently-played user-library-read "
    "playlist-read-private playlist-modify-public playlist-modify-private"
)

# 跨 session 歷史（存在 Spotify 私人歌單裡）
HISTORY_PLAYLIST_NAME = "🤖 AI Discovery History (請勿手動刪除)"

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
    """頁面載入時呼叫：處理 Spotify 導回的 ?code=xxx（交換 token）或 ?error=xxx（授權失敗）。

    失敗訊息寫入 st.session_state["spotify_auth_error"]，由登入頁決定呈現方式——
    不在這裡 st.error()，否則錯誤會出現在 hero 之前。
    """
    if "spotify_token" in st.session_state:
        return

    err = st.query_params.get("error")
    if err:
        st.session_state["spotify_auth_error"] = err
        try:
            st.query_params.clear()
        except Exception:
            pass
        return

    code = st.query_params.get("code")
    if not code:
        return
    try:
        auth_manager = _get_auth_manager()
        token_info = auth_manager.get_access_token(code, as_dict=True, check_cache=False)
        st.session_state["spotify_token"] = token_info
        st.session_state.pop("spotify_auth_error", None)
    except Exception as e:
        st.session_state["spotify_auth_error"] = str(e)
    finally:
        # 清掉 URL 上的 code，避免重新整理時重複交換
        try:
            st.query_params.clear()
        except Exception:
            pass


def is_authenticated() -> bool:
    return "spotify_token" in st.session_state

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


def search_track(title: str, artist: str, sp: spotipy.Spotify | None = None) -> dict | None:
    if sp is None:
        sp = get_spotify_client() if is_authenticated() else _get_guest_spotify_client()
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
    images = t["album"].get("images") or []
    return {
        "name": t["name"],
        "artist": ", ".join(a["name"] for a in t["artists"]),
        "album": t["album"]["name"],
        "url": t["external_urls"]["spotify"],
        "uri": t["uri"],
        "cover": images[1]["url"] if len(images) > 1 else (images[0]["url"] if images else ""),
    }


def _get_search_token() -> str | None:
    """取得可供搜尋用的 access token。必須在主執行緒呼叫（會碰 session_state）。"""
    if is_authenticated():
        get_spotify_client()  # 觸發必要的 token refresh
        return st.session_state["spotify_token"]["access_token"]
    cid = _get_credential("SPOTIFY_CLIENT_ID")
    csec = _get_credential("SPOTIFY_CLIENT_SECRET")
    if not cid or not csec:
        return None
    try:
        auth = SpotifyClientCredentials(client_id=cid, client_secret=csec)
        return auth.get_access_token(as_dict=False)
    except Exception:
        return None


def _search_tracks_parallel(recs: list[dict], token: str, max_workers: int = 8) -> list[dict | None]:
    """並行搜尋 Spotify，保持輸入順序。單首失敗視為找不到（回 None），不中斷整批。
    每個 worker thread 用自己的 Spotify client（requests.Session 非 thread-safe）。"""
    tls = threading.local()

    def _worker(rec: dict) -> dict | None:
        sp = getattr(tls, "sp", None)
        if sp is None:
            sp = spotipy.Spotify(auth=token)
            tls.sp = sp
        try:
            return search_track(rec["title"], rec["artist"], sp=sp)
        except Exception:
            return None

    with ThreadPoolExecutor(max_workers=min(max_workers, max(1, len(recs)))) as ex:
        return list(ex.map(_worker, recs))


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


