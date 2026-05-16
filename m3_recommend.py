"""
M3: LLM 推薦引擎
流程：Spotify Top Tracks → Gemini 生成候選歌單 → Spotify Search 解析 URI → 輸出結果
"""

import os
import json
from dotenv import load_dotenv
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from google import genai

load_dotenv()

SCOPES = "user-top-read user-read-recently-played user-library-read"


def get_spotify_client() -> spotipy.Spotify:
    auth_manager = SpotifyOAuth(
        client_id=os.getenv("SPOTIFY_CLIENT_ID"),
        client_secret=os.getenv("SPOTIFY_CLIENT_SECRET"),
        redirect_uri=os.getenv("SPOTIFY_REDIRECT_URI"),
        scope=SCOPES,
        open_browser=True,
    )
    return spotipy.Spotify(auth_manager=auth_manager)


def fetch_user_profile(sp: spotipy.Spotify) -> dict:
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

    # 合併所有來源，建立完整「已聽過」清單
    all_tracks = (
        top_tracks_medium + top_tracks_short
        + [i["track"] for i in recently_played]
        + [i["track"] for i in saved_tracks]
    )
    heard_titles   = sorted({t["name"] for t in all_tracks})
    heard_artists  = sorted({a["name"] for t in all_tracks for a in t["artists"]})

    return {
        "top_tracks_recent":  [track_str(t) for t in top_tracks_short],
        "top_tracks_overall": [track_str(t) for t in top_tracks_medium],
        "top_artists":  [a["name"] for a in top_artists],
        "top_genres":   list({g for a in top_artists for g in a.get("genres", [])}),
        "heard_titles":  heard_titles,
        "heard_artists": heard_artists,
    }


def build_prompt(profile: dict) -> str:
    heard_titles_str  = "\n".join(f"- {t}" for t in profile["heard_titles"][:80])
    heard_artists_str = ", ".join(profile["heard_artists"][:60])
    return f"""你是一個專業音樂推薦 AI。根據以下使用者的聆聽資料，推薦 20 首他「確定沒聽過、但會喜歡」的歌曲。

## 使用者口味
**喜愛藝人：** {", ".join(profile["top_artists"])}
**音樂風格：** {", ".join(profile["top_genres"][:10]) if profile["top_genres"] else "pop, indie pop"}
**近期常聽：**
{chr(10).join(f"- {t}" for t in profile["top_tracks_recent"])}

## 已聽過的歌曲（絕對禁止推薦）
以下歌名完全禁止出現在推薦中：
{heard_titles_str}

## 已接觸的藝人（限制推薦）
{heard_artists_str}
→ 這些藝人只能推薦他們的冷門深軌或 B-side，不能推他們的熱門主打歌

## 推薦策略（按優先順序）
1. 最優先：推薦完全未在上方出現的全新藝人（至少 12 首）
2. 已接觸藝人的冷門深軌可佔最多 8 首
3. 年代橫跨至少 3 個時期（70s-80s / 90s-00s / 2010s-now）
4. 允許跨語言（英、韓、日、法、西語）

只輸出 JSON：
{{
  "recommendations": [
    {{
      "title": "歌曲名稱（原文）",
      "artist": "藝人名稱（原文）",
      "reason": "推薦理由（15字以內）",
      "is_new_artist": true
    }}
  ]
}}"""


def get_recommendations_from_gemini(prompt: str) -> list[dict]:
    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
    )
    text = response.text.strip()
    # 去除可能的 markdown code block
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text.strip())["recommendations"]


def search_track_on_spotify(sp: spotipy.Spotify, title: str, artist: str) -> dict | None:
    query = f"track:{title} artist:{artist}"
    results = sp.search(q=query, type="track", limit=1)
    items = results["tracks"]["items"]
    if not items:
        # 放寬搜尋
        results = sp.search(q=f"{title} {artist}", type="track", limit=1)
        items = results["tracks"]["items"]
    if not items:
        return None
    track = items[0]
    return {
        "name": track["name"],
        "artist": ", ".join(a["name"] for a in track["artists"]),
        "uri": track["uri"],
        "url": track["external_urls"]["spotify"],
        "album": track["album"]["name"],
    }


def main() -> None:
    print("正在連線 Spotify...")
    sp = get_spotify_client()
    user = sp.current_user()
    print(f"已登入：{user['display_name']}\n")

    print("讀取聆聽資料...")
    profile = fetch_user_profile(sp)
    print(f"Top 藝人：{', '.join(profile['top_artists'][:5])}...")

    print("\n請 Gemini 生成推薦歌單...")
    prompt = build_prompt(profile)
    recommendations = get_recommendations_from_gemini(prompt)
    print(f"Gemini 生成了 {len(recommendations)} 首推薦\n")

    print("在 Spotify 搜尋歌曲...")
    found = []
    not_found = []
    for rec in recommendations:
        result = search_track_on_spotify(sp, rec["title"], rec["artist"])
        if result:
            result["reason"] = rec["reason"]
            found.append(result)
        else:
            not_found.append(f"{rec['title']} - {rec['artist']}")

    print(f"\n{'='*55}")
    print(f"  LML 的個人化推薦歌單（{len(found)} 首）")
    print(f"{'='*55}")
    for i, track in enumerate(found, 1):
        print(f"\n{i:>2}. {track['name']}")
        print(f"    演出者：{track['artist']}")
        print(f"    專輯：{track['album']}")
        print(f"    理由：{track['reason']}")
        print(f"    連結：{track['url']}")

    if not_found:
        print(f"\n（Spotify 找不到的推薦：{', '.join(not_found)}）")

    # 輸出 URI 清單供未來使用
    uris = [t["uri"] for t in found]
    print(f"\n--- Track URIs（供 M4 使用）---")
    for uri in uris:
        print(uri)


if __name__ == "__main__":
    main()
