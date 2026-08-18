"""
推薦引擎：prompt 組裝、Gemini 呼叫、JSON 解析、後處理去重。
不依賴 Streamlit——可直接被 pytest import。
"""

import json
import re
import time

from google import genai
from google.genai import types

GEMINI_MODEL = "gemini-2.5-flash"

MAX_TRACKS_PER_ARTIST = 2  # 同一次推薦中，同藝人最多出現幾首
HISTORY_KEEP = 200          # 注入 prompt 的歷史推薦上限


# ── Gemini 回應處理 ───────────────────────────────────────
def _strip_code_fence(text: str) -> str:
    """去掉 Gemini 回應可能包的 ```json ... ``` code fence。"""
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return text.strip()


def _friendly_gemini_error(e: Exception) -> Exception:
    """把 Gemini 常見錯誤轉成使用者看得懂的訊息；不認得的原樣回傳。"""
    err = str(e)
    if "429" in err or "RESOURCE_EXHAUSTED" in err:
        return ValueError(
            "Gemini API 配額已用盡（429）。免費額度有每分鐘/每日上限："
            "請稍等 1 分鐘再試；若持續發生，到 https://aistudio.google.com/ "
            "檢查你的 API Key 用量，或明天再試。"
        )
    if "API key not valid" in err or "API_KEY_INVALID" in err:
        return ValueError("Gemini API Key 無效，請確認側邊欄「自訂 API Keys」填入的 Key 是否正確。")
    return e


def _parse_json_robust(text: str) -> dict:
    """Parse JSON from Gemini response with multiple fallback strategies."""
    text = _strip_code_fence(text)

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


# ── 圖片分析 ──────────────────────────────────────────────
def analyze_image(api_key: str, image_bytes: bytes, mime: str) -> str:
    client = genai.Client(api_key=api_key)
    try:
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=[
                types.Part.from_bytes(data=image_bytes, mime_type=mime),
                "請用音樂氛圍的角度分析這張圖片，輸出 JSON：{\"mood\":\"整體情緒\",\"atmosphere\":\"氛圍描述（30字內）\",\"tempo_suggestion\":\"slow/mid/upbeat/dance\",\"energy\":能量1-10,\"keywords\":[\"關鍵字1\",\"關鍵字2\",\"關鍵字3\"]}。只輸出JSON。",
            ],
        )
    except Exception as e:
        raise _friendly_gemini_error(e) from e
    d = json.loads(_strip_code_fence(response.text))
    return f"情緒：{d['mood']}｜氛圍：{d['atmosphere']}｜節奏：{d['tempo_suggestion']}｜能量：{d['energy']}/10"


# ── Prompt 組裝 ───────────────────────────────────────────
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


# ── Gemini 推薦 ───────────────────────────────────────────
def get_recommendations(
    api_key: str,
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
    client = genai.Client(api_key=api_key)
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

    # 最多重試 3 次（含 503 過載）；429 配額用盡 / Key 無效直接給友善訊息，不浪費重試
    for attempt in range(3):
        try:
            text = _call_gemini(with_mime=True)
            if not text:
                text = _call_gemini(with_mime=False)
            if text:
                return _parse_json_robust(text)
        except Exception as e:
            friendly = _friendly_gemini_error(e)
            if friendly is not e:
                raise friendly from e
            err = str(e)
            is_503 = "503" in err or "UNAVAILABLE" in err
            if is_503 and attempt < 2:
                time.sleep(8 * (attempt + 1))  # 8s, 16s
                continue
            if attempt == 2:
                raise
    raise ValueError("Gemini 回傳空回應，請稍後再試")


# ── 後處理去重 ────────────────────────────────────────────
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
