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
