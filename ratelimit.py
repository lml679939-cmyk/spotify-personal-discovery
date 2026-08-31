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
MAX_BUCKETS = 5000     # 記憶體上限（每桶最多 DAILY_MAX 個時間戳，滿載約 6 MB）

# ── 全站閘門（第二道防線）──────────────────────────────
# 上面的 per-browser 額度擋的是「隨手亂點」，清 cookie／無痕／腳本都能繞——那是它的
# 設計取捨，不是 bug。缺的是**最壞情況的天花板**：Gemini Key 與 Spotify Client ID
# 全站共用同一份配額，沒有總量上限的話，一個腳本可以在幾分鐘內把當日配額燒光，
# 並讓 Spotify 回 429（實測 Retry-After 是 6 小時）——**對所有使用者**。
#
# 這道閘門不區分是誰，只問「全站這一小時／這一天已經生成幾次」。繞不掉，因為
# 它根本不看使用者身分。代價是尖峰時真實使用者也可能被擋——所以數字要訂在
# 「真實流量碰不到、但攻擊者跑不遠」之間：
#   HOURLY 150 ＝ 課堂演示（30 人各 5 次）仍在範圍內，但把「幾分鐘燒光」
#                 變成「至少要跑好幾個小時」，中間有時間發現。
#   DAILY  400 ＝ per-browser 上限是 40，等於容納 10 位重度使用者；
#                 遠高於個人專案的真實流量，仍為共用配額留下天花板。
# ⚠️ 這兩個數字應該跟著實際的 Gemini RPD 配額調——配額若低於 400 次生成所需的
#    請求數，DAILY 就該往下調到配額之內，讓使用者看到誠實的「今天用完了」，
#    而不是撞上 Gemini 的 429。
GLOBAL_HOURLY_MAX = 150
GLOBAL_DAILY_MAX = 400
HOUR_SEC = 3600

_BUCKETS: dict[str, list[float]] = {}
_GLOBAL: list[float] = []          # 全站生成的時間戳（≤ GLOBAL_DAILY_MAX 筆，記憶體可忽略）
_LOCK = threading.Lock()           # ⚠️ 非 reentrant：_*_locked() 系列一律假設鎖已持有


def _fresh(times: list[float], now: float) -> list[float]:
    """只保留還在窗內的時間戳。順便就是過期清理。"""
    return [t for t in times if now - t < WINDOW_SEC]


def _evict(now: float) -> None:
    """把桶子數壓回上限內。**呼叫端必須已持有 _LOCK。**

    ⚠️ 舊版是「滿了就 `_BUCKETS.clear()`」，那是可以被利用的：攻擊者只要換 cookie
    造出 MAX_BUCKETS 個新桶（成本近乎零），就能把**全體使用者**的冷卻與每日額度
    一次歸零，而且可以反覆做——等於節流可以被外部關掉。淘汰必須是有選擇性的。

    ⚠️ **淘汰一個桶＝把額度還給那個瀏覽器，所以排序規則本身就是安全決策。**
    直覺的 LRU（丟最久沒動的）在這裡是**錯的**：洪水攻擊送進來的全是新桶，
    LRU 會優先踢掉累積最久、最接近上限的老使用者——正好踢錯人。
    正確的損失函數是「這個桶目前握有多少額度」：

      ① 整桶都已過期的先丟——本來就不再具約束力，零損失。
         正常流量下這一步就夠了（窗長 24 小時，過期桶會不斷累積）。
      ② 還是超過，才丟**有效時間戳最少**的桶（同數量再比誰最久沒動）。
         洪水攻擊的桶各只有 1 筆，會第一批被丟掉——而攻擊者本來就在換 cookie、
         丟不丟對他沒差；真正累積了 30、40 次的使用者則留到最後。
    """
    if len(_BUCKETS) < MAX_BUCKETS:
        return

    # 一次算好所有桶的有效時間戳，① ② 共用（避免掃兩遍）
    fresh = {k: _fresh(times, now) for k, times in _BUCKETS.items()}

    for k, times in fresh.items():          # ① 整桶過期
        if not times:
            del _BUCKETS[k]
    if len(_BUCKETS) < MAX_BUCKETS:
        return

    # ② 留 MAX_BUCKETS - 1 個位子（-1 是給呼叫端這次要新增的那個桶）
    doomed = sorted(_BUCKETS, key=lambda k: (len(fresh[k]), max(fresh[k])))
    for k in doomed[: len(_BUCKETS) - MAX_BUCKETS + 1]:
        del _BUCKETS[k]


def _status_locked(key: str, now: float) -> tuple[bool, int, int]:
    """這個瀏覽器的狀態 → (可否生成, 還要等幾秒, 窗內還剩幾次)。**呼叫端須持有 _LOCK。**"""
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


def _consume_locked(key: str, now: float) -> tuple[bool, int, int]:
    """扣一次這個瀏覽器的額度。擋下來時**不會**記錄。**呼叫端須持有 _LOCK。**"""
    _evict(now)

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


def _global_locked(now: float) -> tuple[str, int]:
    """全站閘門 → (擋下的原因, 還要等幾秒)；沒被擋回 ("", 0)。**呼叫端須持有 _LOCK。**

    等待秒數＝「最舊的那一筆掉出窗外還要多久」＝下一個名額何時釋出，所以是準確值
    而不是安慰用的估計。日窗與小時窗共用同一份時間戳，日窗滿時先報日窗（比較嚴重）。
    """
    global _GLOBAL
    _GLOBAL = [t for t in _GLOBAL if now - t < WINDOW_SEC]   # 順手做過期清理

    if len(_GLOBAL) >= GLOBAL_DAILY_MAX:
        return "global_day", int(WINDOW_SEC - (now - _GLOBAL[0])) + 1

    hour = [t for t in _GLOBAL if now - t < HOUR_SEC]
    if len(hour) >= GLOBAL_HOURLY_MAX:
        return "global_hour", int(HOUR_SEC - (now - hour[0])) + 1

    return "", 0


def status(key: str, now: float) -> tuple[bool, int, int]:
    """唯讀查詢**這個瀏覽器**的額度 → (可否生成, 還要等幾秒, 窗內還剩幾次)。

    ⚠️ 不含全站閘門。UI 請用 peek()、實際放行請用 acquire()。
    """
    with _LOCK:
        return _status_locked(key, now)


def consume(key: str, now: float) -> tuple[bool, int, int]:
    """只扣**這個瀏覽器**的額度。回傳值同 status()。

    ⚠️ 不含全站閘門——生成流程請一律走 acquire()，不要直接用這個，
    否則 GLOBAL_* 的上限等於沒有。保留它是因為它是被測試釘住的原始語意。
    """
    with _LOCK:
        return _consume_locked(key, now)


def peek(key: str, now: float) -> tuple[bool, str, int, int]:
    """唯讀查詢整條閘門 → (可否生成, 擋下的原因, 還要等幾秒, 這個瀏覽器還剩幾次)。

    原因："" ／ "global_day" ／ "global_hour" ／ "daily" ／ "cooldown"。
    給 UI 決定按鈕文字與 disabled 用；真正放行一律走 acquire()。
    """
    with _LOCK:
        ok, wait, left = _status_locked(key, now)
        why, g_wait = _global_locked(now)
        if why:
            return False, why, g_wait, left
        if ok:
            return True, "", 0, left
        return False, ("daily" if left == 0 else "cooldown"), wait, left


def acquire(key: str, now: float) -> tuple[bool, str, int, int]:
    """整條生成閘門：全站額度 ＋ 這個瀏覽器的冷卻/每日上限。回傳值同 peek()。

    ⚠️ **兩道關卡必須在同一個鎖內判定，而且要先看全站、通過才扣個人額度。**
    分成兩次呼叫的話會出現兩種都很難查的錯：被全站擋下卻扣掉了使用者的個人額度
    （他什麼都沒拿到卻少一次），或是先扣了全站名額才發現使用者還在冷卻中
    （名額被浪費掉、全站計數虛高）。這裡的順序保證「有扣就一定有生成」。
    """
    with _LOCK:
        why, g_wait = _global_locked(now)
        if why:
            _, _, left = _status_locked(key, now)
            return False, why, g_wait, left

        ok, wait, left = _consume_locked(key, now)
        if not ok:
            return False, ("daily" if left == 0 else "cooldown"), wait, left

        _GLOBAL.append(now)
        return True, "", 0, left


def reset() -> None:
    """只給測試用。"""
    with _LOCK:
        _BUCKETS.clear()
        _GLOBAL.clear()
