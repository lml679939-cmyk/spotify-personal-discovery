"""
M4: 多模態情境推薦
支援「圖片」、「文字描述」、「自動偵測地理位置/天氣/時間」當作情境，影響推薦風格。
三種輸入可以單獨使用或混合疊加。

使用方式：
    python m4_contextual_recommend.py --text "下雨天想一個人散步"
    python m4_contextual_recommend.py --image "C:/path/to/photo.jpg"
    python m4_contextual_recommend.py --auto-context
    python m4_contextual_recommend.py --auto-context --text "想專心讀書"
    python m4_contextual_recommend.py                          # 進入互動模式
"""

import argparse
import json
import mimetypes
import os
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from google import genai
from google.genai import types

load_dotenv()

SCOPES = "user-top-read user-read-recently-played user-library-read"
GEMINI_MODEL = "gemini-2.5-flash"

# WMO Weather codes (Open-Meteo)
WMO_CODES = {
    0: "晴朗",
    1: "大致晴朗", 2: "局部多雲", 3: "陰天",
    45: "霧", 48: "結霜霧",
    51: "輕微毛毛雨", 53: "中度毛毛雨", 55: "大毛毛雨",
    56: "凍毛毛雨", 57: "強烈凍毛毛雨",
    61: "小雨", 63: "中雨", 65: "大雨",
    66: "凍雨", 67: "強烈凍雨",
    71: "小雪", 73: "中雪", 75: "大雪", 77: "雪粒",
    80: "陣雨", 81: "中陣雨", 82: "強陣雨",
    85: "陣雪", 86: "強陣雪",
    95: "雷雨", 96: "雷雨夾小冰雹", 99: "雷雨夾大冰雹",
}


def get_time_of_day(hour: int) -> str:
    if 5 <= hour < 9: return "清晨"
    if 9 <= hour < 12: return "上午"
    if 12 <= hour < 14: return "中午"
    if 14 <= hour < 18: return "下午"
    if 18 <= hour < 21: return "傍晚"
    if 21 <= hour < 24: return "晚上"
    return "深夜"


def fetch_geolocation() -> dict:
    """IP-based geolocation, no API key needed."""
    r = requests.get("http://ip-api.com/json/?fields=city,country,lat,lon", timeout=10)
    r.raise_for_status()
    data = r.json()
    return {
        "city": data.get("city", "未知"),
        "country": data.get("country", "未知"),
        "lat": data.get("lat"),
        "lon": data.get("lon"),
    }


def fetch_weather(lat: float, lon: float) -> dict:
    """Open-Meteo current weather, no API key needed."""
    r = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": lat,
            "longitude": lon,
            "current": "temperature_2m,weather_code,wind_speed_10m,is_day",
            "timezone": "auto",
        },
        timeout=10,
    )
    r.raise_for_status()
    cur = r.json()["current"]
    return {
        "temperature": cur["temperature_2m"],
        "code": cur["weather_code"],
        "description": WMO_CODES.get(cur["weather_code"], f"天氣代碼{cur['weather_code']}"),
        "wind_speed": cur["wind_speed_10m"],
        "is_day": bool(cur["is_day"]),
    }


def fetch_auto_context() -> str:
    """偵測地理位置 + 天氣 + 時間，回傳結構化情境字串"""
    print("自動偵測情境...")
    geo = fetch_geolocation()
    print(f"  位置：{geo['city']}, {geo['country']}")

    weather = fetch_weather(geo["lat"], geo["lon"])
    print(f"  天氣：{weather['description']} {weather['temperature']}°C（風速 {weather['wind_speed']} km/h）")

    now = datetime.now()
    time_label = get_time_of_day(now.hour)
    print(f"  時間：{now.strftime('%H:%M')}（{time_label}）")

    return (
        f"現在時間 {now.strftime('%Y-%m-%d %H:%M')}（{time_label}），"
        f"地點：{geo['city']}, {geo['country']}，"
        f"天氣：{weather['description']}，氣溫 {weather['temperature']}°C，"
        f"{'白天' if weather['is_day'] else '夜晚'}"
    )


def get_spotify_client() -> spotipy.Spotify:
    auth_manager = SpotifyOAuth(
        client_id=os.getenv("SPOTIFY_CLIENT_ID"),
        client_secret=os.getenv("SPOTIFY_CLIENT_SECRET"),
        redirect_uri=os.getenv("SPOTIFY_REDIRECT_URI"),
        scope=SCOPES,
        open_browser=True,
    )
    return spotipy.Spotify(auth_manager=auth_manager)


def get_gemini_client() -> genai.Client:
    return genai.Client(api_key=os.getenv("GEMINI_API_KEY"))


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

    all_tracks = (
        top_tracks_medium + top_tracks_short
        + [i["track"] for i in recently_played]
        + [i["track"] for i in saved_tracks]
    )
    return {
        "top_tracks_recent":  [track_str(t) for t in top_tracks_short],
        "top_tracks_overall": [track_str(t) for t in top_tracks_medium],
        "top_artists":  [a["name"] for a in top_artists],
        "top_genres":   list({g for a in top_artists for g in a.get("genres", [])}),
        "heard_titles":  sorted({t["name"] for t in all_tracks}),
        "heard_artists": sorted({a["name"] for t in all_tracks for a in t["artists"]}),
    }


def analyze_image_context(client: genai.Client, image_path: Path) -> str:
    """請 Gemini Vision 描述圖片氛圍 → 結構化情境標籤"""
    mime, _ = mimetypes.guess_type(image_path)
    if not mime:
        mime = "image/jpeg"
    image_bytes = image_path.read_bytes()

    prompt = """請用音樂氛圍的角度分析這張圖片，輸出 JSON：
{
  "mood": "整體情緒（如：melancholic / energetic / cozy / euphoric）",
  "atmosphere": "氛圍描述（30字內）",
  "tempo_suggestion": "適合的節奏（slow / mid / upbeat / dance）",
  "energy": "1-10 的能量等級",
  "keywords": ["關鍵字1", "關鍵字2", "關鍵字3"]
}
只輸出 JSON，不要其他文字。"""

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=[
            types.Part.from_bytes(data=image_bytes, mime_type=mime),
            prompt,
        ],
    )
    text = response.text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    parsed = json.loads(text.strip())
    return (
        f"情緒：{parsed['mood']}｜氛圍：{parsed['atmosphere']}｜"
        f"節奏：{parsed['tempo_suggestion']}｜能量：{parsed['energy']}/10｜"
        f"關鍵字：{', '.join(parsed['keywords'])}"
    )


def build_prompt(profile: dict, context: str) -> str:
    heard_titles_str  = "\n".join(f"- {t}" for t in profile["heard_titles"][:80])
    heard_artists_str = ", ".join(profile["heard_artists"][:60])
    return f"""你是一個專業音樂推薦 AI。根據使用者的「聆聽口味」與「當下情境」，推薦 15 首他確定沒聽過、且符合此情境的歌曲。

## 使用者口味
**喜愛藝人：** {", ".join(profile["top_artists"])}
**音樂風格：** {", ".join(profile["top_genres"][:10]) if profile["top_genres"] else "pop, indie pop"}

## 當下情境（最高優先權）
{context}

## 已聽過的歌曲（絕對禁止推薦）
{heard_titles_str}

## 已接觸的藝人（限制推薦）
{heard_artists_str}
→ 這些藝人只能推冷門深軌/B-side，不能推熱門主打歌

## 推薦策略
1. 情境氛圍必須匹配（最高優先）
2. 最優先推薦完全未出現過的全新藝人（至少 10 首）
3. 已接觸藝人的冷門深軌最多 5 首
4. 允許跨語言，年代多樣化

只輸出 JSON：
{{
  "context_interpretation": "情境理解（一句話）",
  "recommendations": [
    {{
      "title": "歌曲名稱（原文）",
      "artist": "藝人名稱（原文）",
      "reason": "為何符合此情境（20字內）"
    }}
  ]
}}"""


def get_recommendations(client: genai.Client, prompt: str) -> dict:
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
    )
    text = response.text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text.strip())


def search_track_on_spotify(sp: spotipy.Spotify, title: str, artist: str) -> dict | None:
    results = sp.search(q=f"track:{title} artist:{artist}", type="track", limit=1)
    items = results["tracks"]["items"]
    if not items:
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


def parse_args():
    parser = argparse.ArgumentParser(description="多模態情境音樂推薦")
    parser.add_argument("--image", "-i", type=str, help="情境圖片路徑")
    parser.add_argument("--text", "-t", type=str, help="情境文字描述")
    parser.add_argument("--auto-context", "-a", action="store_true",
                        help="自動抓取地理位置、天氣、時間當作情境")
    return parser.parse_args()


def interactive_input() -> tuple[Path | None, str | None]:
    print("沒有提供 --image 或 --text，進入互動模式。")
    print("（兩者皆可為空，按 Enter 跳過）\n")
    text = input("文字描述當下情境（例如：下雨天、深夜開車、咖啡廳寫作業）：").strip() or None
    image_input = input("圖片路徑（可拖曳檔案到這裡，沒有就按 Enter）：").strip().strip('"') or None
    image_path = Path(image_input) if image_input else None
    return image_path, text


def main() -> None:
    args = parse_args()
    image_path = Path(args.image) if args.image else None
    text = args.text
    auto = args.auto_context

    if not image_path and not text and not auto:
        image_path, text = interactive_input()

    if not image_path and not text and not auto:
        print("錯誤：必須至少提供圖片、文字或 --auto-context 其中一個。")
        return

    if image_path and not image_path.exists():
        print(f"錯誤：找不到圖片 {image_path}")
        return

    auto_context_str = None
    if auto:
        print()
        try:
            auto_context_str = fetch_auto_context()
        except Exception as e:
            print(f"  自動情境偵測失敗：{e}（繼續其他情境）")

    print("\n正在連線 Spotify...")
    sp = get_spotify_client()
    user = sp.current_user()
    print(f"已登入：{user['display_name']}")

    print("\n讀取聆聽資料...")
    profile = fetch_user_profile(sp)

    gem = get_gemini_client()

    context_parts = []
    if auto_context_str:
        context_parts.append(f"環境情境（自動偵測）：{auto_context_str}")
    if image_path:
        print(f"\n分析圖片：{image_path.name}")
        image_context = analyze_image_context(gem, image_path)
        print(f"  圖片情境：{image_context}")
        context_parts.append(f"圖片分析：{image_context}")
    if text:
        print(f"\n文字情境：{text}")
        context_parts.append(f"文字描述：{text}")

    context = "\n".join(context_parts)

    print("\n請 Gemini 根據情境生成推薦...")
    prompt = build_prompt(profile, context)
    result = get_recommendations(gem, prompt)

    print(f"\nGemini 對情境的理解：{result.get('context_interpretation', '')}")
    print(f"生成了 {len(result['recommendations'])} 首推薦\n")

    print("在 Spotify 搜尋歌曲...")
    found = []
    not_found = []
    for rec in result["recommendations"]:
        r = search_track_on_spotify(sp, rec["title"], rec["artist"])
        if r:
            r["reason"] = rec["reason"]
            found.append(r)
        else:
            not_found.append(f"{rec['title']} - {rec['artist']}")

    print(f"\n{'='*55}")
    print(f"  情境化推薦歌單（{len(found)} 首）")
    print(f"{'='*55}")
    for i, track in enumerate(found, 1):
        print(f"\n{i:>2}. {track['name']}")
        print(f"    演出者：{track['artist']}")
        print(f"    專輯：{track['album']}")
        print(f"    理由：{track['reason']}")
        print(f"    連結：{track['url']}")

    if not_found:
        print(f"\n（Spotify 找不到：{', '.join(not_found)}）")


if __name__ == "__main__":
    main()
