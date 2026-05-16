"""
M2: 將 Top Tracks 寫入新歌單並推送到 Spotify 帳號
執行前確保 .env 已設定好（與 M1 相同）
"""

import os
from datetime import datetime
from dotenv import load_dotenv
import spotipy
from spotipy.oauth2 import SpotifyOAuth

load_dotenv()

SCOPES = (
    "user-top-read "
    "user-read-recently-played "
    "playlist-modify-public "
    "playlist-modify-private"
)


def get_spotify_client() -> spotipy.Spotify:
    auth_manager = SpotifyOAuth(
        client_id=os.getenv("SPOTIFY_CLIENT_ID"),
        client_secret=os.getenv("SPOTIFY_CLIENT_SECRET"),
        redirect_uri=os.getenv("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8888/callback"),
        scope=SCOPES,
        open_browser=True,
        show_dialog=True,
    )
    return spotipy.Spotify(auth_manager=auth_manager)


def fetch_top_track_uris(sp: spotipy.Spotify, time_range: str = "medium_term", limit: int = 20) -> list[str]:
    result = sp.current_user_top_tracks(limit=limit, time_range=time_range)
    return [track["uri"] for track in result["items"]]


def create_discovery_playlist(sp: spotipy.Spotify, user_id: str, track_uris: list[str]) -> dict:
    today = datetime.now().strftime("%Y-%m-%d")
    playlist_name = f"LML Discovery {today}"
    playlist_desc = f"由 Spotify Personal Discovery App 自動生成・{today}"

    playlist = sp.user_playlist_create(
        user=user_id,
        name=playlist_name,
        public=False,
        description=playlist_desc,
    )

    # Spotify 單次最多加 100 首，分批處理
    for i in range(0, len(track_uris), 100):
        sp.playlist_add_items(playlist["id"], track_uris[i:i + 100])

    return playlist


def main() -> None:
    print("正在連線 Spotify...")
    sp = get_spotify_client()

    user = sp.current_user()
    user_id = user["id"]
    print(f"已登入：{user['display_name']} ({user_id})")

    print("\n讀取近 6 個月 Top 20 曲目...")
    track_uris = fetch_top_track_uris(sp, time_range="medium_term", limit=20)
    print(f"取得 {len(track_uris)} 首曲目")

    print("\n建立歌單並寫入 Spotify...")
    playlist = create_discovery_playlist(sp, user_id, track_uris)

    print(f"\n✓ 歌單建立成功！")
    print(f"  名稱：{playlist['name']}")
    print(f"  ID：{playlist['id']}")
    print(f"  網址：{playlist['external_urls']['spotify']}")
    print(f"\n現在打開 Spotify 就能看到「{playlist['name']}」歌單。")


if __name__ == "__main__":
    main()
