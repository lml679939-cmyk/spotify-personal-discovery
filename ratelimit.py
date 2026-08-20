"""生成請求的節流。

⚠️ 這道防線擋的是「意外」與「隨手亂點」，**不是**有決心的攻擊者。
桶子是用瀏覽器識別碼分的，清 cookie／無痕視窗／自己寫腳本都能繞過。
真正擋得住的做法（登入驗證、WAF、IP 信譽）Streamlit Cloud 免費方案都沒有。

為什麼還是要做：本站是公開網址，用的是**站方自備的 Gemini Key**（所有人共用同一份
免費配額）與**同一組 Spotify Client ID**（所有人共用同一份速率限制）。一次 15 首的
生成 ≈ 1–2 個 Gemini 請求 + 上百個 Spotify 請求。沒有任何節流的話，一個人按住生成鍵
連點就能把當日配額耗光、並讓 Spotify 回 429（實測 Retry-After 是 6 小時）——
**對所有使用者**。冷卻與每日上限能把這件事從「一分鐘內做得到」變成「要刻意繞」。

純邏輯模組：不 import streamlit，時間一律由呼叫端傳入，可直接被 pytest import。
"""

import threading

COOLDOWN_SEC = 20      # 同一個瀏覽器兩次生成之間的最短間隔（一次生成本來就要 8–10 秒）
DAILY_MAX = 40         # 同一個瀏覽器在滾動 24 小時窗內的生成次數上限
WINDOW_SEC = 24 * 3600
MAX_BUCKETS = 5000     # 記憶體上限：滿了就整批丟掉重建（同 _SEARCH_CACHE 的策略）

_BUCKETS: dict[str, list[float]] = {}
_LOCK = threading.Lock()


def _fresh(times: list[float], now: float) -> list[float]:
    """只保留還在窗內的時間戳。順便就是過期清理。"""
    return [t for t in times if now - t < WINDOW_SEC]


def status(key: str, now: float) -> tuple[bool, int, int]:
    """唯讀查詢，給 UI 決定按鈕要不要 disable。

    回傳 (可否生成, 還要等幾秒, 這個窗內還剩幾次)。
    """
    with _LOCK:
        times = _fresh(_BUCKETS.get(key, []), now)

    remaining = max(0, DAILY_MAX - len(times))
    if remaining == 0:
        return False, 0, 0

    if times:
        elapsed = now - max(times)
        if elapsed < COOLDOWN_SEC:
            # 無條件進位：剩 0.2 秒時顯示「還要等 1 秒」比「還要等 0 秒」誠實
            return False, int(COOLDOWN_SEC - elapsed) + 1, remaining

    return True, 0, remaining


def consume(key: str, now: float) -> tuple[bool, int, int]:
    """實際扣一次額度。回傳值同 status()——擋下來時**不會**記錄這一次。

    ⚠️ 呼叫端要在真的要送出生成之前呼叫這個，不要只靠 status()：
    status() 是唯讀的，兩者之間使用者可能已經多點了幾下。
    """
    with _LOCK:
        if len(_BUCKETS) >= MAX_BUCKETS:
            _BUCKETS.clear()

        times = _fresh(_BUCKETS.get(key, []), now)
        remaining = max(0, DAILY_MAX - len(times))

        if remaining == 0:
            _BUCKETS[key] = times
            return False, 0, 0

        if times:
            elapsed = now - max(times)
            if elapsed < COOLDOWN_SEC:
                _BUCKETS[key] = times
                return False, int(COOLDOWN_SEC - elapsed) + 1, remaining

        times.append(now)
        _BUCKETS[key] = times
        return True, 0, max(0, DAILY_MAX - len(times))


def reset() -> None:
    """只給測試用。"""
    with _LOCK:
        _BUCKETS.clear()
