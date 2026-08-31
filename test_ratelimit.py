"""ratelimit.py 的單元測試（純邏輯，時間由參數傳入，不會真的等）。

執行：python -m pytest test_ratelimit.py -q
"""

import pytest

import ratelimit
from ratelimit import COOLDOWN_SEC, DAILY_MAX, WINDOW_SEC


@pytest.fixture(autouse=True)
def _clean():
    ratelimit.reset()
    yield
    ratelimit.reset()


T0 = 1_000_000.0   # 任意起點；模組不碰真實時鐘


def test_first_call_is_allowed():
    ok, wait, left = ratelimit.consume("k", T0)
    assert ok and wait == 0
    assert left == DAILY_MAX - 1


def test_second_call_within_cooldown_is_blocked():
    ratelimit.consume("k", T0)
    ok, wait, _ = ratelimit.consume("k", T0 + 1)
    assert not ok
    assert 0 < wait <= COOLDOWN_SEC


def test_blocked_call_does_not_consume_quota():
    """被冷卻擋下來的那次不能扣額度，否則猛點就能把自己的每日上限點光。"""
    ratelimit.consume("k", T0)
    for i in range(5):
        ratelimit.consume("k", T0 + 1 + i)
    _, _, left = ratelimit.status("k", T0 + COOLDOWN_SEC + 1)
    assert left == DAILY_MAX - 1, "只有第一次成功的呼叫該被記錄"


def test_allowed_again_after_cooldown():
    ratelimit.consume("k", T0)
    ok, _, _ = ratelimit.consume("k", T0 + COOLDOWN_SEC + 1)
    assert ok


def test_daily_cap_is_enforced():
    now = T0
    for _ in range(DAILY_MAX):
        ok, _, _ = ratelimit.consume("k", now)
        assert ok
        now += COOLDOWN_SEC + 1
    ok, wait, left = ratelimit.consume("k", now)
    assert not ok and left == 0
    assert wait == 0, "額度用完不是冷卻，不該叫使用者等幾秒"


def _exhaust(key: str, start: float = T0) -> float:
    """把額度用完，回傳最後一次的時間戳。"""
    now = start
    last = now
    for _ in range(DAILY_MAX):
        ratelimit.consume(key, now)
        last = now
        now += COOLDOWN_SEC + 1
    assert not ratelimit.consume(key, now)[0]
    return last


def test_quota_fully_recovers_once_the_whole_window_has_passed():
    last = _exhaust("k")
    ok, _, left = ratelimit.consume("k", last + WINDOW_SEC + 1)
    assert ok and left == DAILY_MAX - 1


def test_quota_recovers_gradually_not_as_a_cliff():
    """滾動窗＝逐格釋放，不是到點整批清零。

    ⚠️ 這條刻意釘住，因為很容易誤以為「過 24 小時就全部恢復」。實際上額度是跟著
    每一次呼叫各自滿 24 小時才回來，所以用完之後只會一格一格放行。
    """
    last = _exhaust("k")
    step = COOLDOWN_SEC + 1          # 當初就是以這個間隔用掉的

    # 額度是「每一次呼叫各自滿 24 小時」才回來，所以釋放速率＝當初的消耗速率
    assert ratelimit.status("k", T0 + WINDOW_SEC + 1)[2] == 1, "只有最早那一次過期"
    assert ratelimit.status("k", T0 + step + WINDOW_SEC + 1)[2] == 2
    assert ratelimit.status("k", T0 + 2 * step + WINDOW_SEC + 1)[2] == 3

    # 要等最後一次也滿 24 小時，額度才全部回來
    assert ratelimit.status("k", last + WINDOW_SEC + 1)[2] == DAILY_MAX


def test_buckets_are_isolated_per_key():
    """一個人用完額度不能影響到別人——這是這個設計最要命的失敗模式。"""
    now = T0
    for _ in range(DAILY_MAX):
        ratelimit.consume("victim_neighbour", now)
        now += COOLDOWN_SEC + 1
    assert not ratelimit.consume("victim_neighbour", now)[0]
    ok, _, left = ratelimit.consume("someone_else", now)
    assert ok and left == DAILY_MAX - 1


def test_status_is_read_only():
    ratelimit.consume("k", T0)
    before = ratelimit.status("k", T0 + COOLDOWN_SEC + 1)
    for _ in range(3):
        ratelimit.status("k", T0 + COOLDOWN_SEC + 1)
    assert ratelimit.status("k", T0 + COOLDOWN_SEC + 1) == before


def test_status_matches_consume_decision():
    ratelimit.consume("k", T0)
    for t in (T0 + 1, T0 + COOLDOWN_SEC // 2, T0 + COOLDOWN_SEC + 5):
        assert ratelimit.status("k", t)[0] == ratelimit.consume("k", t)[0]
        ratelimit.reset()
        ratelimit.consume("k", T0)


def test_wait_is_rounded_up_never_zero_while_blocked():
    """剩 0.2 秒時顯示「還要等 0 秒」會讓使用者以為壞了。"""
    ratelimit.consume("k", T0)
    ok, wait, _ = ratelimit.status("k", T0 + COOLDOWN_SEC - 0.2)
    assert not ok and wait >= 1


def test_bucket_store_is_bounded():
    for i in range(ratelimit.MAX_BUCKETS + 10):
        ratelimit.consume(f"k{i}", T0)
    assert len(ratelimit._BUCKETS) <= ratelimit.MAX_BUCKETS


def test_expired_timestamps_are_pruned_not_accumulated():
    now = T0
    for i in range(10):
        ratelimit.consume("k", now)
        now += WINDOW_SEC + 1     # 每次都跨過整個窗
    assert len(ratelimit._BUCKETS["k"]) == 1, "舊時間戳應該被清掉，不是無限成長"


# ── 桶子淘汰（High-3 迴歸）────────────────────────────────
# 舊版滿了就 _BUCKETS.clear()：換 cookie 造 MAX_BUCKETS 個新桶就能把全體使用者的
# 額度一次歸零、且可反覆做＝節流可以被外部關掉。以下三條釘住新的淘汰規則。

def _flood(n: int, at: float, prefix: str = "flood") -> None:
    for i in range(n):
        ratelimit.consume(f"{prefix}{i}", at)


def test_flooding_cannot_reset_an_exhausted_bucket():
    """核心安全性質：灌爆桶子表不能把「已用完額度的人」洗回可用。"""
    last = _exhaust("victim")
    flood_t = last + 1
    _flood(ratelimit.MAX_BUCKETS + 10, flood_t)

    assert "victim" in ratelimit._BUCKETS, "額度最滿的桶必須活到最後"
    ok, _, left = ratelimit.consume("victim", flood_t + COOLDOWN_SEC + 1)
    assert not ok and left == 0, "洪水攻擊後受害者仍應被擋著"
    assert len(ratelimit._BUCKETS) <= ratelimit.MAX_BUCKETS


def test_eviction_drops_fully_expired_buckets_first():
    """① 整桶過期的先丟，且丟完就該收手——不必犧牲任何還有效的桶。"""
    ratelimit.consume("stale", T0)
    later = T0 + WINDOW_SEC + 1            # stale 的唯一時間戳已過期
    _flood(ratelimit.MAX_BUCKETS, later, prefix="live")

    assert "stale" not in ratelimit._BUCKETS
    survivors = sum(1 for i in range(ratelimit.MAX_BUCKETS)
                    if f"live{i}" in ratelimit._BUCKETS)
    assert survivors == ratelimit.MAX_BUCKETS, "過期桶就夠賠了，不該連坐有效的桶"


def test_eviction_drops_the_bucket_holding_least_quota_first():
    """② 依「目前握有多少額度」淘汰，不是 LRU。

    ⚠️ LRU 在這裡是錯的：洪水送進來的全是新桶，LRU 會優先踢掉累積最久、
    最接近上限的老使用者＝正好踢錯人。
    """
    now = T0
    for _ in range(5):                      # heavy：握有 5 格額度
        ratelimit.consume("heavy", now)
        now += COOLDOWN_SEC + 1
    ratelimit.consume("light", now)         # light：只握有 1 格
    _flood(ratelimit.MAX_BUCKETS, now + 1)

    assert "heavy" in ratelimit._BUCKETS
    assert "light" not in ratelimit._BUCKETS


# ── 全站閘門（HIGH-2）──────────────────────────────────
# per-browser 額度擋隨手亂點，全站閘門擋「最壞情況」。兩道關卡的**順序**是這一段的重點：
# 被全站擋下不能扣個人額度，被個人冷卻擋下也不能浪費全站名額。

from ratelimit import GLOBAL_DAILY_MAX, GLOBAL_HOURLY_MAX, HOUR_SEC


def _fill_global(n: int, at: float, prefix: str = "g") -> None:
    """用 n 個不同的瀏覽器各生成一次，把全站計數推到 n。"""
    for i in range(n):
        ok, why, _, _ = ratelimit.acquire(f"{prefix}{i}", at)
        assert ok, f"第 {i} 次不該被擋（why={why}）"


def test_global_hourly_cap_blocks_a_brand_new_browser():
    """全站閘門不看身分——換 cookie 也繞不掉，這正是它存在的理由。"""
    _fill_global(GLOBAL_HOURLY_MAX, T0)
    ok, why, wait, _ = ratelimit.acquire("a_totally_fresh_browser", T0)
    assert not ok and why == "global_hour"
    assert wait > 0


def test_global_block_does_not_burn_personal_quota():
    """被全站擋下的人什麼都沒拿到，不能扣他的個人額度。"""
    _fill_global(GLOBAL_HOURLY_MAX, T0)
    ok, why, _, left = ratelimit.acquire("victim", T0)
    assert not ok and why == "global_hour"
    assert left == DAILY_MAX, "全站忙碌不該消耗使用者自己的額度"
    assert ratelimit.status("victim", T0)[2] == DAILY_MAX


def test_cooldown_block_does_not_waste_a_global_slot():
    """反向：使用者還在冷卻中，不能先把全站名額扣掉（會讓全站計數虛高）。"""
    assert ratelimit.acquire("u", T0)[0]
    assert len(ratelimit._GLOBAL) == 1
    ok, why, _, _ = ratelimit.acquire("u", T0 + 1)
    assert not ok and why == "cooldown"
    assert len(ratelimit._GLOBAL) == 1, "被冷卻擋下不該佔用全站名額"


def test_global_daily_cap_is_enforced():
    step = HOUR_SEC / 100          # 每小時 100 次，不會先撞到 HOURLY 上限
    for i in range(GLOBAL_DAILY_MAX):
        assert ratelimit.acquire(f"d{i}", T0 + i * step)[0]
    last = T0 + (GLOBAL_DAILY_MAX - 1) * step
    ok, why, wait, _ = ratelimit.acquire("one_too_many", last)
    assert not ok and why == "global_day"
    assert wait > HOUR_SEC, "日窗的等待應該是小時級，不是幾秒"


def test_global_wait_points_at_the_next_free_slot():
    """等待秒數＝最舊那筆掉出窗外還要多久，是準確值而不是安慰用的估計。"""
    _fill_global(GLOBAL_HOURLY_MAX, T0)
    _, why, wait, _ = ratelimit.peek("x", T0 + 10)
    assert why == "global_hour"
    assert wait == HOUR_SEC - 10 + 1
    # 名額釋出後就該放行
    assert ratelimit.acquire("x", T0 + HOUR_SEC + 1)[0]


def test_peek_agrees_with_acquire():
    """UI 顯示的狀態必須和實際放行的判定一致，否則按鈕會說謊。"""
    _fill_global(GLOBAL_HOURLY_MAX, T0)
    for key, when in (("fresh", T0), ("fresh", T0 + HOUR_SEC + 1)):
        p_ok, p_why, _, _ = ratelimit.peek(key, when)
        a_ok, a_why, _, _ = ratelimit.acquire(key, when)
        assert (p_ok, p_why) == (a_ok, a_why)


def test_consume_still_bypasses_the_global_gate_by_design():
    """consume() 刻意維持「只看個人額度」的原始語意（被 16 條測試釘住）。

    ⚠️ 所以生成流程一定要走 acquire()——這條測試存在是為了讓人看到差別，
    不是鼓勵使用 consume()。
    """
    _fill_global(GLOBAL_HOURLY_MAX, T0)
    assert not ratelimit.acquire("z", T0)[0]
    assert ratelimit.consume("z", T0)[0], "consume() 不看全站閘門"


def test_reset_clears_the_global_counter():
    _fill_global(10, T0)
    ratelimit.reset()
    assert ratelimit._GLOBAL == []
