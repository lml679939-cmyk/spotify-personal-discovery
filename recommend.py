"""
推薦引擎：prompt 組裝、Gemini 呼叫、JSON 解析、後處理去重。
不依賴 Streamlit——可直接被 pytest import。
"""

import json
import re
import time
import unicodedata
from functools import lru_cache
from urllib.parse import quote, urlparse

from google import genai
from google.genai import types

GEMINI_MODEL = "gemini-2.5-flash"

# gemini-2.5-flash 預設會先「思考」再回答，實測這一步就吃掉 13 秒
# （同一個 prompt：thinking 開啟 18.15s / 關閉 5.03s，thoughts_token 2181–3052）。
# 推薦歌單是「照規則產出 JSON」的任務，不需要推理鏈；語言/曲風/避開歷史等限制實測都仍遵守。
_NO_THINKING = types.ThinkingConfig(thinking_budget=0)


MAX_TRACKS_PER_ARTIST = 2  # 同一次推薦中，同藝人最多出現幾首
HISTORY_KEEP = 200          # session 內保留的歷史推薦上限
PROMPT_HISTORY_MAX = 40     # 其中真正寫進 prompt 的筆數（完整排除靠程式端，見下）
FEEDBACK_PROMPT_MAX = 20    # 每類回饋（讚/倒讚/聽過）最多寫進 prompt 的筆數，同短清單原則
REFILL_MAX = 1              # 湊不滿時最多補生成幾次（共用 Gemini Key 的配額很珍貴）
# 搜不到的候選只能當補位。實測把 LLM 推向冷門後，幻覺曲目（歌手真的存在、歌名是編的）
# 大增——不設上限的話清單會被「只有搜尋連結」的卡片塞滿，看起來滿了其實不能播。
SPARE_MAX_RATIO = 0.2

# ── 出圈（novelty）參數 ───────────────────────────────────
# 為什麼需要這些：使用者選「100% 新藝人」卻還是拿到聽過的歌，原因有兩個——
#   1. Spotify 給我們的聆聽紀錄只是取樣，使用者透過電台/YouTube/朋友聽過的遠不止這些
#   2. LLM 有量化過的流行度偏差，傾向推每個曲風「最有名」的歌，那正是最可能已經聽過的
# 對策是把流行度（popularity 0-100）當成「大概聽過」的代理指標——推薦系統文獻的標準
# 新穎性度量 EPC 本質就是 1 - popularity——在探索額度上加一道天花板，並用它參與重排。
OVERGEN_FACTOR = 1.6         # 超額生成倍率：驗證鏈會刷掉一部分，先多要一些候選
GUEST_OVERGEN_FACTOR = 1.25  # 訪客版超額倍率：過濾只有去重＋同藝人上限，餘裕不用像登入版那麼大
POP_CEILING_DISCOVERY = 65   # 探索額度的流行度上限（超過視為「不可能沒聽過」）
POP_CEILING_STRICT = 55      # new_ratio == 100（硬核探索）時收緊
POP_CEILING_RELAX_STEP = 10  # 候選不足時每輪放寬多少（不回退熱門，只逐步放寬）
POP_CEILING_MAX_RELAX = 80   # 放寬的絕對上限：再上去就是「不可能沒聽過」的大熱門了，
                             # 湊不滿寧可少幾首——不然放寬會把天花板擋掉的歌整批放回來
NOVELTY_WEIGHT = 0.35        # 重排權重：0 = 完全照 LLM 順序，1 = 純冷門優先
UNKNOWN_POP = 50             # 連 fame 都沒有時的中間值——不確定就不加分也不擋

# ⚠️ Spotify 已經把熱門度訊號整批收掉了（2026-08 實測：搜尋與 /tracks 的 track 物件
# 都沒有 popularity 這個鍵，artist 也沒有 popularity / followers / genres）。
# 天花板沒有資料就是空轉，所以改請 LLM 自評知名度 fame 1-5，換算成 0-100 當替代指標。
# popularity 若哪天回來（或使用者 token 拿得到）會優先採用，不用改程式。
# 對應到兩道天花板：硬核模式(55) 只放行 fame 1-2，一般模式(65) 放行到 fame 3，
# 湊不滿時硬核會放寬到 65（＝退而求其次收 fame 3），但永遠收不到 fame 4-5。
FAME_TO_POP = {1: 10, 2: 35, 3: 60, 4: 80, 5: 95}


def _fame_score(v) -> int | None:
    """LLM 自評的 fame 換算成 0-100。認不得就回 None（交給呼叫端當「不確定」處理）。

    模型偶爾會把數字寫成字串（"fame":"5"），不容錯的話最紅的歌會直接穿過天花板。
    bool 要先擋掉——Python 的 True 會被 int() 當成 1，也就是最冷門那一級。
    """
    if isinstance(v, bool):
        return None
    try:
        return FAME_TO_POP.get(int(float(v)))
    except (TypeError, ValueError):
        return None


@lru_cache(maxsize=4)
def _client(api_key: str) -> genai.Client:
    """共用 genai.Client。

    建構一次實測要 ~2.4 秒，而 app.py 每次按「生成推薦歌單」都會走一次；
    key 相同就重用（底層 httpx 連線也一併重用，省掉 TLS 握手）。
    """
    return genai.Client(api_key=api_key)


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


# 逐個撈出「不含巢狀括號」的物件，再從裡面各自抓欄位。
# ⚠️ 不要寫成固定鍵順序的單一 regex——加一個 fame 欄位就會整個失效，
# 而且舊測試用舊格式照樣會過，看不出來已經壞了。
_JSON_OBJ_RE = re.compile(r"\{[^{}]*\}")


def _str_field(obj: str, key: str) -> str:
    m = re.search(rf'"{key}"\s*:\s*"((?:[^"\\]|\\.)*)"', obj)
    return m.group(1) if m else ""


def _int_field(obj: str, key: str) -> int | None:
    m = re.search(rf'"{key}"\s*:\s*(\d+)', obj)
    return int(m.group(1)) if m else None


def _parse_json_robust(text: str) -> dict:
    """Parse JSON from Gemini response with multiple fallback strategies."""
    text = _strip_code_fence(text)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Fallback：回應被截斷時，把還完整的曲目物件一個個撈出來
    result = {
        "taste_profile": _str_field(text, "taste_profile"),
        "context_interpretation": _str_field(text, "context_interpretation"),
        "recommendations": [],
    }
    for m in _JSON_OBJ_RE.finditer(text):
        obj = m.group(0)
        title, artist = _str_field(obj, "title"), _str_field(obj, "artist")
        if not title or not artist:
            continue
        rec = {"title": title, "artist": artist, "reason": _str_field(obj, "reason")}
        fame = _int_field(obj, "fame")
        if fame is not None:
            rec["fame"] = fame
        result["recommendations"].append(rec)
    if result["recommendations"]:
        return result
    raise json.JSONDecodeError("Cannot parse Gemini response", text, 0)


def _flatten_channels(data: dict) -> dict:
    """把雙通道回應（discovery / familiar）攤平成單一 recommendations 清單。

    通道標籤只用來塑形「要生成什麼」，不拿來當事實——曲目屬於探索還是熟悉，
    一律由 curate_tracks() 依「這位音樂人在不在使用者的已知清單裡」重新判定。
    訪客模式與 regex fallback 產出的舊格式（recommendations）也走這裡，維持相容。
    """
    recs = data.get("recommendations")
    # ⚠️ 用 isinstance 判斷的話，模型同時吐 "recommendations":[] 與 "discovery":[...] 時
    # 空清單會勝出，兩個通道的內容全部被丟掉
    if not recs:
        recs = list(data.get("discovery") or []) + list(data.get("familiar") or [])
    return {
        "taste_profile": data.get("taste_profile", ""),
        "context_interpretation": data.get("context_interpretation", ""),
        "recommendations": [
            r for r in recs if isinstance(r, dict) and r.get("title") and r.get("artist")
        ],
    }


# ── 圖片分析 ──────────────────────────────────────────────
def analyze_image(api_key: str, image_bytes: bytes, mime: str) -> str:
    client = _client(api_key)
    try:
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                thinking_config=_NO_THINKING,
            ),
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
    refill_exclude: list[tuple[str, str]] | None = None,
    feedback: dict | None = None,
) -> str:
    traits_block = f"\n## 使用者個人特質與當下狀態\n{user_traits}\n" if user_traits else ""
    feedback_block = _feedback_block(feedback)

    disc_n = round(num_songs * new_ratio / 100)
    fam_n = num_songs - disc_n

    # 兩個清單分開要，才能給各自不同的指令——混在一份清單裡時「推新的」和「挖深軌」
    # 這兩種相反的要求會互相稀釋，而且沒辦法保證探索額度真的有足夠候選。
    channels = []
    if disc_n:
        channels.append(f"""### discovery（{disc_n} 首）— 使用者沒接觸過的音樂人
- **從 taste_profile 的特徵出發**去找人，不要從上面的喜愛藝人聯想「同等級的大牌」
- 優先「相鄰但不同」的音樂人：他們的合作者、同廠牌夥伴、影響過他們或受他們影響的人、
  同曲風但不同國家或不同年代的獨立音樂人
- 曲目優先選專輯曲目、B-side、非主打歌；**避開每位音樂人串流量最高的那幾首代表作**
- 目標是「值得被發現」而不是「人人都知道」——但仍要好聽、仍要貼合情境""")
    if fam_n:
        channels.append(f"""### familiar（{fam_n} 首）— 上面喜愛藝人清單裡的深軌
- 只從使用者的喜愛藝人中挑
- **避開他們的熱門主打歌**：專輯曲目、B-side、合輯版本、早期作品都好
- 目標是「這位我很熟，但這首我沒聽過」""")
    mode_block = "## 這次要產出的清單\n" + "\n\n".join(channels)

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

    # 補生成（第一輪湊不滿時）
    if refill_exclude:
        pairs = "\n".join(f"- {t} - {a}" for t, a in refill_exclude[-60:])
        refill_block = (
            "\n## 這是補充生成（重要）\n"
            "上一輪的推薦有不少太熱門、或使用者其實已經聽過，被系統過濾掉了。\n"
            "這一輪請往**更冷門、更小眾**的方向挑，並換掉下列已經出現過的曲目：\n"
            f"{pairs}\n"
        )
    else:
        refill_block = ""

    # 排除清單放在最後、緊鄰輸出格式——長 context 的中段最容易被忽略，
    # 而且清單愈長遵守率愈差，所以這裡只放 top 50 歌手（完整排除靠程式端的 curate_tracks）
    checks = []
    if disc_n and profile["heard_artists"]:
        checks.append(
            "discovery 清單裡的每一位音樂人，都必須不在下面這份「使用者已經在聽」的清單中：\n"
            f"{', '.join(profile['heard_artists'])}"
        )
    if history:
        recent = history[-PROMPT_HISTORY_MAX:]
        checks.append(
            "下列曲目最近已經推薦過，這次請換別的：\n"
            + "\n".join(f"- {h['title']} - {h['artist']}" for h in recent)
        )
    check_block = ("\n## 輸出前的最後檢查\n" + "\n\n".join(checks) + "\n") if checks else ""

    # 只列出有配額的通道——JSON 範本裡出現的鍵，LLM 就算配額是 0 也會硬生一些出來填
    # discovery 的 reason 要寫成「橋接句」——點出這位陌生音樂人跟使用者已經在聽的
    # 東西有什麼關係。陌生推薦附上這種解釋，接受度會明顯提高。
    item_disc = ('{"title":"歌名","artist":"音樂人","fame":3,'
                 '"reason":"和你聽的音樂的連結，例如「與○○同廠牌」「一樣的迷幻吉他」，20字內"}')
    item_fam = '{"title":"歌名","artist":"音樂人","fame":3,"reason":"理由20字內"}'
    schema_parts = ['"taste_profile":"品味特徵 2-3 句"',
                    '"context_interpretation":"情境理解（一句話）"']
    if disc_n:
        schema_parts.append(f'"discovery":[{item_disc}]')
    if fam_n:
        schema_parts.append(f'"familiar":[{item_fam}]')
    schema = "{" + ",".join(schema_parts) + "}"

    return f"""你是專業音樂推薦 AI。根據使用者口味與情境，推薦 {num_songs} 首符合情境的歌。

## 第一步：先歸納品味特徵（寫進 taste_profile 欄位）
用 2-3 句描述這位使用者的音樂品味——曲風細類、年代、製作質感、能量、語言傾向。
接下來的推薦要**從這些特徵出發**，而不是從「他喜歡的藝人」直接聯想到同溫層的知名歌手。

## 使用者口味
喜愛藝人：{", ".join(profile["top_artists"])}
風格：{", ".join(profile["top_genres"][:8]) if profile["top_genres"] else "pop, indie pop"}
{traits_block}{feedback_block}
{fav_block}## 當下情境（最高優先）
{context}

{lang_block}
{genre_block}
{mode_block}

## 每首都要標 fame（這個欄位會被用來過濾，請誠實評估）
這首歌有多紅，填 1-5 的整數。**判斷基準：這首歌在該音樂人的 Spotify 熱門曲目排行第幾。**
- 5 = 跨越樂迷圈的國民金曲（例：Adele《Someone Like You》）
- 4 = **這位音樂人最有名的那幾首之一**，排在他的熱門前 5（例：Nick Drake《Pink Moon》、
  Gorillaz《On Melancholy Hill》、Radiohead《Creep》）——被歌單、廣告、電影用過的通常都在這一級
- 3 = 樂迷普遍知道，但不是他最紅的那幾首
- 2 = 要聽過整張專輯才會知道的曲目
- 1 = 只有死忠樂迷才知道

**這份清單裡至少一半必須是 fame 1 或 2。** 如果你發現自己整批都標 3，那代表挑的其實
都是安全牌——請換成同一批音樂人更深的曲目，或換更小眾的音樂人。

## 多樣性硬性規則（必須遵守）
- 同一個音樂人在這 {num_songs} 首推薦中**最多出現 {MAX_TRACKS_PER_ARTIST} 首**
- 每首歌的 title + artist 組合必須唯一，不能重複
- 年代多樣化（不要全是同一年的歌）
- **只推薦你確定存在的曲目**。想不起某位音樂人的具體曲名時就換一位你熟悉曲目的音樂人——
  寧可給一首你確定有的專輯曲，也不要猜一個「聽起來像是他會有」的歌名（這種找不到會被丟掉）
{refill_block}{check_block}
只輸出 JSON：
{schema}"""


def _feedback_block(feedback: dict | None) -> str:
    """使用者對過往推薦的回饋 → prompt 區塊（兩種模式共用）。

    喜歡＝正向錨點（往相鄰方向探索）、不喜歡＝避開方向、聽過了＝出圈校準。
    「不要重複推薦這些歌」的**保證**不在這裡——app.py 會把回饋曲目併進 history
    走程式端排除；這個區塊只做品味引導（prompt 只做機率優化的同一條原則）。
    """
    if not feedback:
        return ""

    def _lines(items: list[dict]) -> str:
        return "\n".join(f"- {i['title']} - {i['artist']}" for i in items[-FEEDBACK_PROMPT_MAX:])

    parts = []
    if feedback.get("liked"):
        parts.append(
            "按過讚的歌（重要品味訊號——請往這些歌的相鄰方向探索：同氛圍、同場景、"
            "相似製作質感的其他音樂人，但不要重複推薦這些歌本身）：\n" + _lines(feedback["liked"])
        )
    if feedback.get("disliked"):
        parts.append(
            "明確不喜歡的歌（避開與這些相似的方向）：\n" + _lines(feedback["disliked"])
        )
    if feedback.get("heard"):
        parts.append(
            "回報「早就聽過」的歌（代表那次推得不夠新，請更大膽探索）：\n"
            + _lines(feedback["heard"])
        )
    if not parts:
        return ""
    return "\n## 使用者對過往推薦的回饋\n" + "\n\n".join(parts) + "\n"


def build_guest_prompt(
    context: str,
    num_songs: int = 15,
    user_traits: str = "",
    languages: list[str] | None = None,
    genres: list[str] | None = None,
    history: list[dict] | None = None,
    fav_artists: list[str] | None = None,
    refill_exclude: list[tuple[str, str]] | None = None,
    feedback: dict | None = None,
) -> str:
    """訪客模式 prompt：沒有個人聆聽資料，純靠情境推薦。"""
    feedback_block = _feedback_block(feedback)
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
        # 與登入版同一條原則：prompt 只放最近 PROMPT_HISTORY_MAX 筆做機率優化
        # （清單愈長遵守率愈差），完整排除靠程式端 _basic_dedupe 拿整份歷史比對
        recent = history[-PROMPT_HISTORY_MAX:]
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

    # 補生成（第一輪湊不滿時）。訪客版湊不滿的原因幾乎都是與過往推薦撞歌，
    # 所以指令是「換別的」，不是登入版的「往更冷門挑」
    if refill_exclude:
        pairs = "\n".join(f"- {t} - {a}" for t, a in refill_exclude[-60:])
        refill_block = (
            "\n## 這是補充生成（重要）\n"
            "上一輪的推薦有幾首與過往推薦重複，被系統過濾掉了。\n"
            "這一輪請換不同的曲目與音樂人，並避開下列已經出現過的：\n"
            f"{pairs}\n"
        )
    else:
        refill_block = ""

    return f"""你是專業音樂推薦 AI。根據使用者描述的情境與偏好，推薦 {num_songs} 首歌。

注意：這位使用者沒有提供個人聆聽紀錄，所以請完全根據情境推薦。
{traits_block}{feedback_block}
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
{refill_block}
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
    refill_exclude: list[tuple[str, str]] | None = None,
    feedback: dict | None = None,
) -> dict:
    client = _client(api_key)
    if profile is None:
        prompt = build_guest_prompt(
            context, num_songs, user_traits,
            languages=languages, genres=genres, history=history,
            fav_artists=fav_artists, refill_exclude=refill_exclude,
            feedback=feedback,
        )
    else:
        prompt = build_prompt(
            profile, context, num_songs, new_ratio, user_traits,
            languages=languages, genres=genres, history=history,
            fav_artists=fav_artists, refill_exclude=refill_exclude,
            feedback=feedback,
        )

    def _call_gemini(with_mime: bool) -> str:
        cfg = types.GenerateContentConfig(
            response_mime_type="application/json" if with_mime else None,
            thinking_config=_NO_THINKING,
        )
        resp = client.models.generate_content(model=GEMINI_MODEL, contents=prompt, config=cfg)
        return (resp.text or "").strip()

    # 最多重試 3 次（含 503 過載）；429 配額用盡 / Key 無效直接給友善訊息，不浪費重試
    for attempt in range(3):
        try:
            text = _call_gemini(with_mime=True)
            if not text:
                text = _call_gemini(with_mime=False)
            if text:
                return _flatten_channels(_parse_json_robust(text))
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


# ── 播放連結 ──────────────────────────────────────────────
# YouTube 走純搜尋網址：不需要任何 API、不吃配額、不用 OAuth。
# （YouTube Data API 的 search.list 一次要 100 units，每天總共才 10000 units，
#  等於全站一天只有約 100 次搜尋——拿來解析歌單完全不可行。）
# Apple Music 同一招（搜尋頁）：storefront 固定 tw（使用者以台灣為主）。
# 未來要掛聯盟分潤（Apple Performance Partners 的 &at= token）也是在這裡加。
PLAY_PLATFORMS = ("Spotify", "YouTube", "Apple Music")


def youtube_search_url(title: str, artist: str) -> str:
    return "https://www.youtube.com/results?search_query=" + quote(
        f"{title} {artist}".strip(), safe=""
    )


def apple_music_search_url(title: str, artist: str) -> str:
    return "https://music.apple.com/tw/search?term=" + quote(
        f"{title} {artist}".strip(), safe=""
    )


def play_link(track: dict, platform: str = "Spotify") -> tuple[str, str]:
    """回傳 (按鈕文字, 連結)。

    ⚠️ **選 Spotify 但這首在 Spotify 找不到時，一律退回 YouTube**。
    以前是給一個 Spotify 站內搜尋網址，但那首歌本來就不在 Spotify 上，點過去必然落空；
    YouTube 幾乎都找得到（涵蓋更廣，也收得到 LLM 把曲名與歌手配錯時的正確版本）。
    按鈕文字會跟著變成「▶ YouTube」，順便讓使用者一眼看出哪幾首不在 Spotify。
    Apple Music 走搜尋頁，跟有沒有 Spotify 結果無關，不需要 fallback。
    """
    if platform == "Apple Music":
        return "▶ Apple Music", apple_music_search_url(
            track.get("name", ""), track.get("artist", "")
        )
    if platform == "YouTube" or track.get("_no_spotify"):
        return "▶ YouTube", youtube_search_url(track.get("name", ""), track.get("artist", ""))
    return "▶ Spotify", track.get("url", "")


# 播放中繼（點擊計數）只允許轉導到這些網域。?goto= 是網址參數＝完全由攻擊者控制，
# 沒有白名單的話本站就是一個 open redirect（釣魚連結掛著我們的網域騙人點）。
ALLOWED_PLAY_HOSTS = frozenset({
    "open.spotify.com", "www.youtube.com", "music.youtube.com", "music.apple.com",
})


def is_allowed_play_url(url: str) -> bool:
    try:
        u = urlparse(url or "")
    except ValueError:
        return False
    return u.scheme == "https" and (u.hostname or "").lower() in ALLOWED_PLAY_HOSTS


# ── 名稱正規化（判斷「這首聽過沒」用） ─────────────────────
_PAREN_RE = re.compile(r"[（(\[【][^）)\]】]*[）)\]】]")
_QUALIFIER = (
    r"remaster(?:ed)?|live|acoustic|radio edit|single version|album version|"
    r"mono|stereo|demo|instrumental|remix|edit|version|deluxe|bonus|"
    r"re-?recorded|taylor'?s version"
)
# ⚠️ qualifier 兩側一定要有 \b：沒有詞界時 'Special Delivery' 含 live、'Demons' 含 demo、
# 'Meditation'／'Credits' 含 edit，正常歌名會被砍成半截
_DASH_QUALIFIER_RE = re.compile(rf"\s+-\s+[^-]*\b(?:{_QUALIFIER})\b.*$", re.IGNORECASE)
_FEAT_RE = re.compile(r"\s+(?:feat\.?|ft\.?|featuring)\s+.*$", re.IGNORECASE)
_PUNCT_RE = re.compile(r"[^\w\s]+")
_SPACE_RE = re.compile(r"\s+")


def _norm(s: str) -> str:
    return (s or "").strip().lower()


def _fold(s: str) -> str:
    """去掉重音符號（Beyoncé → beyonce），讓 LLM 的寫法跟 Spotify 的寫法對得起來。"""
    decomposed = unicodedata.normalize("NFKD", (s or "").strip().lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _norm_title(s: str) -> str:
    """歌名正規化：去掉版本後綴，讓 'Song (Remastered 2011)'、'Song - Live'、
    'Song feat. X' 跟 'Song' 算同一首。

    只比歌名會誤殺不同藝人的同名歌，所以正規化後一律搭配藝人組成 _track_key()。
    """
    t = _fold(s)
    t = _PAREN_RE.sub(" ", t)
    t = _DASH_QUALIFIER_RE.sub("", t)
    t = _FEAT_RE.sub("", t)
    t = _PUNCT_RE.sub(" ", t)
    return _SPACE_RE.sub(" ", t).strip()


def _primary_artist(artist: str) -> str:
    """合作曲以第一位藝人為主鍵。"""
    return (artist or "").split(",")[0].strip()


def _norm_artist(s: str) -> str:
    """藝人名正規化。保留單一空白——全部刪掉的話 'Yellowcard' 會等於 'Yellow Card'。"""
    t = _FEAT_RE.sub("", _fold(s))
    return _SPACE_RE.sub(" ", _PUNCT_RE.sub(" ", t)).strip()


def _artist_tokens(s: str) -> set[str]:
    return {tok for tok in _norm_artist(s).split(" ") if tok}


def _track_key_from(title: str, primary_artist: str) -> tuple[str, str]:
    """曲目比對鍵：(正規化歌名, 正規化主要藝人)。有結構化藝人清單時用這個。"""
    return (_norm_title(title), _norm_artist(primary_artist))


def _track_key(title: str, artist: str) -> tuple[str, str]:
    """只有一串藝人文字時的版本（歷史紀錄、LLM 原始輸出）。

    ⚠️ 逗號切分對 'Earth, Wind & Fire' 這種團名會切錯，所以只要拿得到 Spotify 的
    artists 陣列，一律改用 _track_key_from()。
    """
    return _track_key_from(title, _primary_artist(artist))


def _history_keys(history: list[dict] | None) -> set[tuple[str, str]]:
    """歷史紀錄的比對鍵。

    歷史裡的 artist 是逗號串接的字串，切逗號對「Tyler, The Creator」這種團名會切成
    'tyler'，而候選那邊有 artists 陣列、算出來是 'tyler the creator'——兩邊對不上，
    這些歌手的歷史去重就完全失效。兩種切法都放進來才擋得住。
    """
    keys: set[tuple[str, str]] = set()
    for h in history or []:
        title, artist = h.get("title", ""), h.get("artist", "")
        keys.add(_track_key(title, artist))
        keys.add(_track_key_from(title, artist))
    return keys


def _track_primary(t: dict) -> str:
    """曲目的主要藝人：優先用 Spotify 的 artists 陣列，退而求其次才切逗號。"""
    names = t.get("artist_names")
    if names:
        return names[0]
    return _primary_artist(t.get("artist") or "")


def _loose_match(a: str, b: str) -> bool:
    """兩個名字是不是指同一位藝人（容忍 'Tom Misch' vs 'Tom Misch & Yussef Dayes'）。

    比對以「詞」為單位而不是子字串——子字串會讓 'Sia' 命中 'Cassia'、'Rain' 命中 'Train'。
    """
    na, nb = _norm_artist(a), _norm_artist(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    ta, tb = _artist_tokens(a), _artist_tokens(b)
    if not ta or not tb:
        return False
    smaller, larger = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    if len(smaller) == 1 and len(next(iter(smaller))) < 3:
        return False   # 單字且過短（如樂團名 "A"）不足以判定
    return smaller <= larger


def resolution_matches(
    claim_title: str, claim_artist: str, got_title: str, got_artists: list[str]
) -> bool:
    """Spotify 搜尋回來的是不是 LLM 講的那首歌。

    嚴格搜尋（track: + artist: 欄位限定）命中時不需要這道檢查；模糊 fallback 搜尋
    才需要——它常常撈到「同一位藝人的另一首熱門歌」甚至完全不相干的老歌，
    照收進結果就等於推了一首使用者八成聽過的歌。
    """
    claims = [a.strip() for a in (claim_artist or "").split(",") if a.strip()]
    if not any(_loose_match(c, g) for c in claims for g in (got_artists or [])):
        return False
    ct, gt = _norm_title(claim_title), _norm_title(got_title)
    if not ct or not gt:
        return False
    if ct == gt:
        return True
    # 「包含」要加長度比例限制，否則 'Skyfall Reprise' 會被 'Skyfall' 收下、
    # 'Hello' 會被 'Hello Goodbye' 收下——那正是這道檢查要擋的「同歌手的另一首歌」
    shorter, longer = (ct, gt) if len(ct) <= len(gt) else (gt, ct)
    return shorter in longer and len(shorter) / len(longer) >= 0.7


# ── 後處理：驗證鏈 ────────────────────────────────────────
def _basic_dedupe(
    tracks: list[dict],
    history: list[dict] | None = None,
    num_songs: int | None = None,
    stats: dict | None = None,
) -> list[dict]:
    """同批去重 + 排除歷史 + 同藝人最多 MAX_TRACKS_PER_ARTIST 首。訪客模式走這條。

    傳入 stats 時順手計數刷掉的首數（dup_history / dup_batch / artist_capped），
    app.py 拿它組「為什麼湊不滿」的說明——少列任何一個原因都可能出現自相矛盾的訊息。
    搜不到的（_no_spotify）穩定排序到最後，而且排序在截斷**之前**：
    超額生成的餘裕優先留給可播放的曲目（與登入模式 spare「湊不滿才用」同一個語意），
    留下來的也不會佔清單開頭——沒封面又不能播，排最前面看起來像整個功能壞掉。"""
    history_keys = _history_keys(history)
    seen = set(history_keys)
    counts: dict[str, int] = {}
    out: list[dict] = []
    for t in tracks:
        title = t.get("name") or t.get("title") or ""
        key = _track_key_from(title, _track_primary(t))
        if key in seen:
            if stats is not None:
                bucket = "dup_history" if key in history_keys else "dup_batch"
                stats[bucket] = stats.get(bucket, 0) + 1
                stats["dup"] = stats.get("dup", 0) + 1
            continue
        primary = _norm_artist(_track_primary(t))
        if counts.get(primary, 0) >= MAX_TRACKS_PER_ARTIST:
            if stats is not None:
                stats["artist_capped"] = stats.get("artist_capped", 0) + 1
            continue
        seen.add(key)
        counts[primary] = counts.get(primary, 0) + 1
        out.append(t)
    out.sort(key=lambda t: bool(t.get("_no_spotify")))  # 穩定排序：兩組內部維持 LLM 順位
    if num_songs:
        out = out[:num_songs]
    return out


def curate_tracks(
    tracks: list[dict],
    history: list[dict] | None = None,
    profile: dict | None = None,
    new_ratio: int = 70,
    num_songs: int | None = None,
    spare_capped: bool = True,
) -> tuple[list[dict], dict]:
    """登入模式的驗證鏈，回傳 (曲目, 統計)。

    `spare_capped=False` 用在「搜尋本身失敗」時（例如撞到速率限制）：
    此時搜不到不代表歌是假的，補位卡不該再套 SPARE_MAX_RATIO 上限。

    順序：同批去重 → 排除聽過的曲目 → 分成「探索/熟悉」兩桶 → 探索桶套流行度天花板
    → 依「LLM 順位 + 新穎度」重排取額 → 不足時逐步放寬天花板（而不是回退熱門）。

    關鍵差異（相對改版前的後處理去重）：
      - 歌手排除改用 Spotify artist ID 比對，且在**所有比例**下對探索額度生效
        （以前只有 new_ratio == 100 才擋，70% 時的「新藝人」根本沒人檢查）
      - 曲目排除改用 (正規化歌名, 藝人) 配對，不再只比歌名——變體不再漏掉、同名不再誤殺
      - 探索額度多一道流行度天花板，擋掉「沒紀錄但幾乎一定聽過」的大熱門

    訪客模式（profile is None）改走 _basic_dedupe：歷史/同批去重＋同藝人上限、
    搜不到的排最後、刷掉的首數計進 stats（dup_history / dup_batch / artist_capped）。
    """
    stats = {
        "candidates": len(tracks), "dup": 0, "dup_history": 0, "dup_batch": 0,
        "known_track": 0, "pop_blocked": 0, "artist_capped": 0,
        "discovery_pool": 0, "familiar_pool": 0, "picked_new": 0,
        "picked_familiar": 0, "spare_used": 0, "ceiling": None, "avg_pop_new": None,
        # 天花板到底是靠哪個訊號在跑——三個都 0 代表整條過濾其實沒作用
        "pop_from_spotify": 0, "pop_from_fame": 0, "pop_unknown": 0,
    }
    if profile is None:
        picked_guest = _basic_dedupe(tracks, history, num_songs, stats=stats)
        stats["picked_familiar"] = len(picked_guest)
        return picked_guest, stats

    known_ids = set(profile.get("known_artist_ids") or ())
    known_names = {_norm_artist(a) for a in (profile.get("known_artist_names") or ())}
    known_names.discard("")
    known_keys = {tuple(k) for k in (profile.get("known_track_keys") or ())}

    target = num_songs or len(tracks)
    ceiling = POP_CEILING_STRICT if new_ratio >= 100 else POP_CEILING_DISCOVERY
    stats["ceiling"] = ceiling

    def _is_known_artist(t: dict) -> bool:
        names = {_norm_artist(a) for a in (t.get("artist_names") or (t.get("artist") or "").split(","))}
        return bool(set(t.get("artist_ids") or ()) & known_ids) or bool(names & known_names)

    def _pop(t: dict) -> int:
        """曲目的「多紅」分數 0-100：優先用 Spotify 的 popularity，
        沒有就用 LLM 自評的 fame（Spotify 已停止提供 popularity，見上方常數區）。"""
        p = t.get("popularity")
        if p is not None:
            stats["pop_from_spotify"] += 1
            return p
        f = _fame_score(t.get("fame"))
        if f is not None:
            stats["pop_from_fame"] += 1
            return f
        stats["pop_unknown"] += 1
        return UNKNOWN_POP

    history_keys = _history_keys(history)
    seen = set(history_keys)
    eff_pop: dict[int, int] = {}   # 每首歌的「多紅」分數，以原始索引為鍵（算一次就好）
    discovery: list[tuple[int, dict]] = []
    familiar: list[tuple[int, dict]] = []
    blocked: list[tuple[int, dict]] = []
    spare: list[tuple[int, dict]] = []

    for idx, t in enumerate(tracks):
        key = _track_key_from(t.get("name") or t.get("title") or "", _track_primary(t))
        if key in seen:
            # 分開計數：「推薦過了」和「同批重複」對使用者的意義完全不同，
            # 前者是湊不滿的主要原因之一，訊息裡要講得出來
            stats["dup_history" if key in history_keys else "dup_batch"] += 1
            stats["dup"] += 1
            continue
        seen.add(key)
        if t.get("_no_spotify"):
            spare.append((idx, t))   # 搜不到＝無從驗證，只有湊不滿時才用
            continue
        if key in known_keys:
            stats["known_track"] += 1
            continue
        eff_pop[idx] = _pop(t)
        if _is_known_artist(t):
            familiar.append((idx, t))
        elif eff_pop[idx] > ceiling:
            blocked.append((idx, t))
        else:
            discovery.append((idx, t))

    stats["discovery_pool"] = len(discovery)
    stats["familiar_pool"] = len(familiar)
    # ⚠️ 要在這裡記，不能等到取額之後——_take() 會把項目從桶子裡移除，
    # 到那時候桶子都空了，會誤判成「一首都沒解析成功」
    resolved_any = bool(discovery or familiar or blocked)

    span = max(1, len(tracks) - 1)

    def _score(item: tuple[int, dict]) -> float:
        idx, _ = item
        rank = 1 - idx / span                                  # LLM 自己的排序（越前面越好）
        novelty = 1 - eff_pop.get(idx, UNKNOWN_POP) / 100      # EPC：越冷門越好
        return (1 - NOVELTY_WEIGHT) * rank + NOVELTY_WEIGHT * novelty

    discovery.sort(key=_score, reverse=True)
    familiar.sort(key=_score, reverse=True)

    picked: list[tuple[int, dict]] = []
    counts: dict[str, int] = {}

    def _take(bucket: list[tuple[int, dict]], quota: int) -> int:
        taken = 0
        for item in list(bucket):
            if taken >= quota:
                break
            primary = _norm_artist(_track_primary(item[1]))
            if counts.get(primary, 0) >= MAX_TRACKS_PER_ARTIST:
                continue
            counts[primary] = counts.get(primary, 0) + 1
            bucket.remove(item)
            picked.append(item)
            taken += 1
        return taken

    num_new = round(target * new_ratio / 100)
    _take(discovery, num_new)
    _take(familiar, target - num_new)

    # 補足 1：探索額度不夠就逐步放寬天花板，把剛才擋下的候選由冷到熱取回。
    # 放寬有絕對上限——100% 模式最多只放寬到一般模式的水準，否則等於沒有天花板。
    relax_cap = POP_CEILING_DISCOVERY if new_ratio >= 100 else POP_CEILING_MAX_RELAX
    while len(picked) < target and blocked and stats["ceiling"] < relax_cap:
        stats["ceiling"] = min(stats["ceiling"] + POP_CEILING_RELAX_STEP, relax_cap)
        back = [it for it in blocked if eff_pop.get(it[0], UNKNOWN_POP) <= stats["ceiling"]]
        if not back:
            continue
        for it in back:
            blocked.remove(it)
        back.sort(key=_score, reverse=True)
        _take(back, target - len(picked))
        blocked.extend(back)   # _take 會把取用的移出 back，沒用到的放回去才不會少報 pop_blocked

    # 補足 2：非硬核模式才互相借額。100% 全新是使用者的明確要求，
    # 寧可少幾首也不塞熟悉藝人進去——那正是這次改版要解決的問題。
    if new_ratio < 100:
        _take(familiar, target - len(picked))
    _take(discovery, target - len(picked))

    # 補足 3：真的湊不滿，才拿搜不到的候選頂上（只有搜尋連結、沒有封面），且有比例上限。
    # ⚠️ 上限是用來擋「幻覺曲目」的。搜尋整批沒跑成功時（撞到速率限制、或連一首都沒解析成功）
    # 套上限只會讓 15 首的清單縮成 3 首，那不是保護使用者、是把東西藏起來。
    _spare_quota = target - len(picked)
    if spare_capped and resolved_any:
        _spare_quota = min(_spare_quota, max(1, int(target * SPARE_MAX_RATIO)))
    stats["spare_used"] = _take(spare, _spare_quota)
    stats["pop_blocked"] = len(blocked)

    # 呈現順序：能播的照 LLM 原始順序（新舊交錯），搜不到的一律墊底。
    # ⚠️ 不要只照原始索引排——搜不到的卡片沒有封面、只有搜尋按鈕，夾在最前面會讓
    # 整份清單第一眼看起來像壞掉的（實測 15 首裡 3 首搜不到剛好都排在最前面）。
    picked.sort(key=lambda it: (bool(it[1].get("_no_spotify")), it[0]))
    result = [t for _, t in picked]

    # 標記哪幾首是「出圈」的，讓 UI 畫得出標籤。附解釋能提高使用者對陌生推薦的
    # 接受度（Spotify 自家 BaRT 的實證），標籤是那個解釋最省版面的形式。
    # 訪客模式不設這個旗標——沒有已知清單，「出圈」對他們沒有意義。
    for t in result:
        t["_discovery"] = not t.get("_no_spotify") and not _is_known_artist(t)

    new_items = [
        (i, t) for i, t in picked if not t.get("_no_spotify") and not _is_known_artist(t)
    ]
    stats["picked_new"] = len(new_items)
    stats["picked_familiar"] = len(result) - len(new_items) - stats["spare_used"]
    pops = [eff_pop[i] for i, _ in new_items if i in eff_pop]
    stats["avg_pop_new"] = round(sum(pops) / len(pops), 1) if pops else None
    return result, stats
