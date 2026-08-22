"""固定情境驗收跑分（訪客模式 S1–S5）——演算法改動前後都跑同一組，結果才可比。

用法：
    python eval_bench.py                     # 跑全部情境
    python eval_bench.py --only S1 S4        # 只跑指定情境
    python eval_bench.py --no-repair         # 關閉幻覺補救（量「改動前」的對照）
    python eval_bench.py --tag before-xxx    # 給這輪取個標籤（進檔名與 JSON）

需要 .env 內有 GEMINI_API_KEY / SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET。
機器指標自動算並存進 eval_runs/*.json；跑完照畫面提示把人工三題填進 EVAL.md。

與 app.py 的刻意差異（解讀數字時要記得）：
  - 不做補生成（refill）——湊不滿本身就是要量的訊號，這裡照實記錄
  - 搜尋是循序不是 8 執行緒並行——省共用配額，時間數字會比線上慢
  - S6（登入模式）不在這裡：要使用者 token，照 EVAL.md 的說明手動跑
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from spotipy.oauth2 import SpotifyClientCredentials
from spotipy.cache_handler import MemoryCacheHandler

from recommend import (
    GUEST_OVERGEN_FACTOR,
    _loose_match,
    _track_key,
    curate_tracks,
    get_recommendations,
)
from spotify_api import (
    REPAIR_MAX_PER_BATCH,
    _sp,
    repair_cache_info,
    repair_hallucinated_track,
    search_cache_info,
    search_track,
)

# Windows 主控台預設 cp950，印到 🛠/✗ 這類非 cp950 字元會 UnicodeEncodeError 整個中斷
# （連結尾的 JSON 都來不及存）。驗收工具就是要在這台 Windows 機器上反覆跑，強制走 UTF-8。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

NUM_SONGS = 15

# ⚠️ 情境輸入逐字固定——改了任何一個字，跨輪比較就失效。要換題就開新的情境 ID。
SCENARIOS = [
    {
        "id": "S1", "name": "深夜放空（華語限定）",
        "context": "文字描述：凌晨一點，剛加完班回到家，只想放空",
        "languages": ["華語"], "genres": None, "fav_artists": None, "user_traits": "",
        "check": "lang_cjk",   # 語言遵守：曲名+歌手含 CJK 的比例
    },
    {
        "id": "S2", "name": "雨天通勤（曲風限定）",
        "context": "文字描述：下雨的早晨，捷運通勤中",
        "languages": None, "genres": ["Jazz", "Lo-fi"], "fav_artists": None, "user_traits": "",
        "check": None,         # 曲風遵守無法自動驗，靠人工契合度
    },
    {
        "id": "S3", "name": "健身（全不限）",
        "context": "文字描述：健身房重訓，需要節奏強的",
        "languages": None, "genres": None, "fav_artists": None, "user_traits": "",
        "check": None,
    },
    {
        "id": "S4", "name": "指定歌手",
        "context": "文字描述：週末下午散步",
        "languages": None, "genres": None,
        "fav_artists": ["陳綺貞", "落日飛車"], "user_traits": "",
        "check": "fav_share",  # 指定歌手佔比（承諾是至少一半）
    },
    {
        "id": "S5", "name": "投射推論",
        "context": "",
        "languages": None, "genres": None, "fav_artists": None,
        "user_traits": (
            "- 投射問題「☕ 你現在桌上有什麼東西？」\n"
            "  使用者回答：冷掉的咖啡、待簽的文件、一顆維他命\n"
            "  （請從這個回答推測使用者的當下狀態、生活風格、潛在心情）"
        ),
        "check": None,
    },
]

_CJK_RE = re.compile(r"[一-鿿]")


def _make_client():
    auth = SpotifyClientCredentials(
        client_id=os.getenv("SPOTIFY_CLIENT_ID"),
        client_secret=os.getenv("SPOTIFY_CLIENT_SECRET"),
        cache_handler=MemoryCacheHandler(),   # 不落地 .cache 檔，與正式碼同一條紀律
    )
    return _sp(auth.get_access_token(as_dict=False))


def run_scenario(sc: dict, sp, api_key: str, repair: bool) -> dict:
    t0 = time.perf_counter()
    result = get_recommendations(
        api_key, None, sc["context"],
        min(max(NUM_SONGS + 2, int(NUM_SONGS * GUEST_OVERGEN_FACTOR)), 40),
        user_traits=sc["user_traits"],
        languages=sc["languages"], genres=sc["genres"],
        fav_artists=sc["fav_artists"],
    )
    gemini_s = time.perf_counter() - t0

    raw = result.get("recommendations", [])
    seen, unique = set(), []
    for rec in raw:
        k = _track_key(rec.get("title", ""), rec.get("artist", ""))
        if k not in seen:
            seen.add(k)
            unique.append(rec)

    t0 = time.perf_counter()
    cards, misses, repaired, budget = [], 0, 0, REPAIR_MAX_PER_BATCH
    exclude: set = set()
    for rec in unique:
        card = search_track(rec["title"], rec["artist"], sp=sp)
        if card is None:
            misses += 1
            if repair and budget > 0:
                try:
                    card = repair_hallucinated_track(
                        rec["title"], rec["artist"], exclude, sp=sp
                    )
                except Exception as e:   # 與 app.py 同一態度：單首補救失敗不中斷整批
                    print(f"  [repair 失敗] {rec['artist']}: {e}", flush=True)
                    card = None
                if card is not None:
                    repaired += 1
                    budget -= 1
        if card is None:
            card = {"name": rec["title"], "artist": rec["artist"], "album": "",
                    "url": "", "uri": None, "cover": "", "_no_spotify": True}
        card["reason"] = rec.get("reason", "")
        card["fame"] = rec.get("fame")
        card["_eval_claimed_artist"] = rec.get("artist", "")
        exclude.add(_track_key(card["name"], card["artist"]))
        cards.append(card)
    search_s = time.perf_counter() - t0

    found, stats = curate_tracks(cards, history=None, profile=None, num_songs=NUM_SONGS)
    playable = [t for t in found if not t.get("_no_spotify")]

    m = {
        "scenario": sc["id"], "name": sc["name"],
        "candidates": len(raw), "unique": len(unique),
        "search_miss": misses, "repaired": repaired,
        "final": len(found), "playable": len(playable),
        "dead_cards": len(found) - len(playable),
        "short_of_target": max(0, NUM_SONGS - len(found)),
        "dup_batch": stats["dup_batch"], "artist_capped": stats["artist_capped"],
        "pop_blocked": stats["pop_blocked"],
        "fame_low_share": round(
            sum(1 for t in found if isinstance(t.get("fame"), int) and t["fame"] <= 2)
            / max(1, len(found)), 2),
        "gemini_s": round(gemini_s, 1), "search_s": round(search_s, 1),
    }
    if sc["check"] == "lang_cjk":
        m["lang_conform"] = round(
            sum(1 for t in playable if _CJK_RE.search(t["name"] + t["artist"]))
            / max(1, len(playable)), 2)
    if sc["check"] == "fav_share":
        favs = sc["fav_artists"]
        m["fav_share"] = round(
            sum(1 for t in found
                if any(_loose_match(f, t.get("_eval_claimed_artist", "")) or
                       _loose_match(f, t.get("artist", "")) for f in favs))
            / max(1, len(found)), 2)
    m["tracks"] = [
        {"name": t["name"], "artist": t["artist"],
         "fame": t.get("fame"), "repaired": bool(t.get("_repaired")),
         "dead": bool(t.get("_no_spotify"))}
        for t in found
    ]
    return m


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", default=None)
    ap.add_argument("--no-repair", action="store_true")
    ap.add_argument("--tag", default="")
    args = ap.parse_args()

    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY")
    if not (api_key and os.getenv("SPOTIFY_CLIENT_ID") and os.getenv("SPOTIFY_CLIENT_SECRET")):
        sys.exit("需要 .env 內的 GEMINI_API_KEY / SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET")
    sp = _make_client()

    todo = [s for s in SCENARIOS if not args.only or s["id"] in args.only]
    runs = []
    for sc in todo:
        print(f"\n=== {sc['id']} {sc['name']} ===", flush=True)
        m = run_scenario(sc, sp, api_key, repair=not args.no_repair)
        runs.append(m)
        for i, t in enumerate(m["tracks"], 1):
            mark = "🛠" if t["repaired"] else ("✗" if t["dead"] else " ")
            print(f"  {i:2d}.{mark} {t['name']} — {t['artist']} (fame={t['fame']})")
        keys = ("playable", "search_miss", "repaired", "dead_cards", "short_of_target",
                "pop_blocked", "fame_low_share", "lang_conform", "fav_share",
                "gemini_s", "search_s")
        print("  " + "  ".join(f"{k}={m[k]}" for k in keys if k in m))

    out = {
        "when": datetime.now().isoformat(timespec="seconds"),
        "tag": args.tag, "repair": not args.no_repair, "num_songs": NUM_SONGS,
        "runs": runs,
        "search_cache": search_cache_info(), "repair_cache": repair_cache_info(),
    }
    Path("eval_runs").mkdir(exist_ok=True)
    fname = f"eval_runs/{datetime.now():%Y%m%d-%H%M}{'_' + args.tag if args.tag else ''}.json"
    Path(fname).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"\n已存 {fname}")
    print("\n─── 人工三題（每情境，填進 EVAL.md）───")
    print("① 認得幾首（0-15）　② 契合情境嗎（1-5）　③ 有幾首想真的點開")
    print("S6（登入模式）：照 EVAL.md 的固定輸入在 app 內手動跑，出圈指標抄結果頁那行 caption")


if __name__ == "__main__":
    main()
