"""读秒时钟测试：保留时间 → 读秒 → 超时，以及暂停/恢复。"""

from __future__ import annotations

from server.clock import Clock, ClockConfig
from xiangqi_core import Color


def make_clock(base_ms: int = 60_000, byo_ms: int = 5_000) -> Clock:
    clock = Clock(ClockConfig(base_ms=base_ms, byo_ms=byo_ms))
    clock.begin(Color.RED, 0.0)
    return clock


def test_remaining_counts_down_only_for_turn():
    clock = make_clock()
    assert clock.remaining_ms(0.0) == 60_000
    assert clock.remaining_ms(2.5) == 57_500
    # 黑方还没轮走，时间不动
    assert clock.remaining_for(Color.BLACK, 2.5) == 60_000


def test_charge_deducts_used_time():
    clock = make_clock()
    timed_out, used = clock.charge(3.0)
    assert timed_out is False
    assert used == 3_000
    assert clock.base_left[Color.RED] == 57_000


def test_base_exhaustion_falls_into_byo():
    clock = make_clock(base_ms=3_000, byo_ms=1_000)
    # 用了 3.5 秒：保留时间 3 秒耗尽，多出的 0.5 秒从读秒里扣
    timed_out, _ = clock.charge(3.5)
    assert timed_out is False
    clock.switch_to(Color.BLACK, 3.5)
    # 黑方 3 秒保留还能用
    assert clock.remaining_ms(4.0) == 2_500


def test_byo_timeout():
    clock = make_clock(base_ms=3_000, byo_ms=1_000)
    # 用了 4.2 秒：3 秒保留 + 1 秒读秒都不够
    assert clock.remaining_ms(4.2) == 0
    timed_out, _ = clock.charge(4.2)
    assert timed_out is True


def test_pause_freezes_clock():
    clock = make_clock()
    clock.pause(1.0)
    assert clock.remaining_ms(30.0) == 59_000  # 暂停期间不动
    clock.resume(30.0)
    assert clock.remaining_ms(31.0) == 58_000


def test_snapshot_shape():
    clock = make_clock()
    snap = clock.snapshot(2.0)
    assert snap["turn"] == "RED"
    assert snap["phase"] == "base"
    assert snap["byoMs"] == 5_000
    assert snap["redMs"] == 58_000
    assert snap["blackMs"] == 60_000
    assert snap["paused"] is False


def test_snapshot_phase_becomes_byo():
    clock = make_clock(base_ms=1_000, byo_ms=5_000)
    snap = clock.snapshot(1.4)  # 保留时间用完，处于读秒中
    assert snap["phase"] == "byo"
    assert snap["redMs"] == 4_600
