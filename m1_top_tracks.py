"""
M1: Spotify OAuth 授權 + 讀取個人 Top Tracks
執行前須先在 .env 填入 Spotify App 憑證（參考 .env.example）
"""

import os
from dotenv import load_dotenv
import spotipy
from spotipy.oauth2 import SpotifyOAuth

load_dotenv()

SCOPES = "user-top-read user-read-recently-played"


def get_spotify_client() -> spotipy.Spotify:
    auth_manager = SpotifyOAuth(
        client_id=os.getenv("SPOTIFY_CLIENT_ID"),
        client_secret=os.getenv("SPOTIFY_CLIENT_SECRET"),
        redirect_uri=os.getenv("SPOTIFY_REDIRECT_URI", "http://localhost:8888/callback"),
        scope=SCOPES,
        open_browser=True,
    )
    return spotipy.Spotify(auth_manager=auth_manager)


def fetch_top_tracks(sp: spotipy.Spotify, time_range: str = "medium_term", limit: int = 20) -> list[dict]:
    """
    time_range: short_term (4週) | medium_term (6個月) | long_term (全期)
    """
    result = sp.current_user_top_tracks(limit=limit, time_range=time_range)
    return result["items"]


def print_tracks(tracks: list[dict], title: str) -> None:
    print(f"\n{'='*50}")
    print(f"  {title}")
    print(f"{'='*50}")
    for i, track in enumerate(tracks, 1):
        artists = ", ".join(a["name"] for a in track["artists"])
        popularity = track.get("popularity", 0)
        print(f"{i:>3}. {track['name']}")
        print(f"      演出者：{artists}")
        print(f"      熱門度：{'█' * (popularity // 10)}{'░' * (10 - popularity // 10)} {popularity}/100")
        print()


def main() -> None:
    print("正在連線 Spotify（首次執行會開啟瀏覽器授權）...")
    sp = get_spotify_client()

    user = sp.current_user()
    print(f"\n已登入：{user['display_name']} ({user['id']})")
    print(f"追蹤者：{user['followers']['total']} 人")

    # 三個時間範圍的 Top Tracks
    for time_range, label in [
        ("short_term", "近 4 週最常聽"),
        ("medium_term", "近 6 個月最常聽"),
        ("long_term",   "全時期最常聽"),
    ]:
        tracks = fetch_top_tracks(sp, time_range=time_range, limit=10)
        print_tracks(tracks, label)

    # 輸出可供後續階段使用的 track URI 清單
    print("\n--- 近 6 個月 Top 20 Track URIs（供 M2/M3 使用）---")
    top20 = fetch_top_tracks(sp, time_range="medium_term", limit=20)
    for track in top20:
        artists = ", ".join(a["name"] for a in track["artists"])
        print(f"{track['uri']}  # {track['name']} - {artists}")


if __name__ == "__main__":
    main()
