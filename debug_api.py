import os, requests, json
from dotenv import load_dotenv
load_dotenv()
from spotipy.oauth2 import SpotifyOAuth

auth = SpotifyOAuth(
    client_id=os.getenv("SPOTIFY_CLIENT_ID"),
    client_secret=os.getenv("SPOTIFY_CLIENT_SECRET"),
    redirect_uri=os.getenv("SPOTIFY_REDIRECT_URI"),
    scope="playlist-modify-public playlist-modify-private user-top-read",
)
token = auth.get_cached_token() or auth.get_access_token(as_dict=True)
headers = {"Authorization": f"Bearer {token['access_token']}", "Content-Type": "application/json"}

me = requests.get("https://api.spotify.com/v1/me", headers=headers).json()
user_id = me["id"]
print("User ID:", user_id)

# 測試 1：建立 public 歌單
r1 = requests.post(
    f"https://api.spotify.com/v1/users/{user_id}/playlists",
    headers=headers,
    json={"name": "Test Playlist", "public": True, "description": "test"},
)
print("建立 public 歌單 Status:", r1.status_code)

# 測試 2：儲存一首歌到 Liked Songs（不同的寫入 API）
r2 = requests.put(
    "https://api.spotify.com/v1/me/tracks",
    headers={**headers, "Content-Type": "application/json"},
    params={"ids": "4uLU6hMCjMI75M1A2tKUQC"},
)
print("儲存 Liked Song Status:", r2.status_code)
