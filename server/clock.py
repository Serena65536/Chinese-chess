"""读秒时钟（服务端权威）。

口径（决策 D8）：每方 30 分钟保留时间，用完后每步限 30 秒，超时立即判负。

时间只在"轮到该方"时流动；掉线时整体暂停（双方都不扣时），恢复后继续。
所有时间戳都用 ``time.monotonic()``，不受系统改时间影响。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from xiangqi_core import Color


class Phase(str, Enum):
    BASE = "base"
    BYO = "byo"


@dataclass(frozen=True)
class ClockConfig:
    base_ms: int = 30 * 60 * 1000
    byo_ms: int = 30 * 1000

    def as_payload(self) -> dict:
        return {"baseMs": self.base_ms, "byoMs": self.byo_ms}


class Clock:
    def __init__(self, config: Optional[ClockConfig] = None) -> None:
        self.config = config or ClockConfig()
        self.base_left: dict[Color, int] = {
            Color.RED: self.config.base_ms,
            Color.BLACK: self.config.base_ms,
        }
        self.turn: Color = Color.RED
        self.started_at: Optional[float] = None
        self.paused_at: Optional[float] = None
        self.finished = False

    # ---------- 生命周期 ----------

    def begin(self, turn: Color, now: float) -> None:
        self.turn = turn
        self.started_at = now
        self.paused_at = None
        self.finished = False

    def switch_to(self, turn: Color, now: float) -> None:
        self.turn = turn
        self.started_at = now

    def finish(self) -> None:
        self.finished = True

    @property
    def paused(self) -> bool:
        return self.paused_at is not None

    def pause(self, now: float) -> None:
        if self.paused_at is None and not self.finished:
            self.paused_at = now

    def resume(self, now: float) -> None:
        if self.paused_at is None:
            return
        tidle = now - self.paused_at
        if self.started_at is not None:
            self.started_at += tidle
        self.paused_at = None

    # ---------- 计量 ----------

    def elapsed_ms(self, now: float) -> int:
        if self.started_at is None or self.finished:
            return 0
        end = self.paused_at if self.paused_at is not None else now
        return max(0, int((end - self.started_at) * 1000))

    def phase(self, now: float) -> Phase:
        return Phase.BASE if self.remaining_ms(now) > 0 and self.base_left[self.turn] > 0 else Phase.BYO

    def remaining_ms(self, now: float) -> int:
        """轮走方当前还剩多少毫秒（已经进入读秒时返回读秒剩余）。"""
        left = self.base_left[self.turn] - self.elapsed_ms(now)
        if left > 0:
            return left
        return max(0, self.config.byo_ms + left)

    def remaining_for(self, color: Color, now: float) -> int:
        if self.finished:
            return 0 if self.base_left[color] <= 0 else self.base_left[color]
        if color is self.turn:
            return self.remaining_ms(now)
        return max(0, self.base_left[color])

    def snapshot(self, now: float) -> dict:
        left = self.base_left[self.turn] - self.elapsed_ms(now)
        red = self.remaining_for(Color.RED, now)
        black = self.remaining_for(Color.BLACK, now)
        return {
            "redMs": int(red),
            "blackMs": int(black),
            "turn": self.turn.name,
            "phase": Phase.BASE.value if left > 0 else Phase.BYO.value,
            "byoMs": self.config.byo_ms,
            "baseMs": self.config.base_ms,
            "paused": self.paused,
        }

    # ---------- 结算 ----------

    def charge(self, now: float) -> tuple[bool, int]:
        """轮走方落子后结算。返回 (是否超时, 本步用时毫秒)。"""
        elapsed = self.elapsed_ms(now)
        left = self.base_left[self.turn] - elapsed
        if left > 0:
            self.base_left[self.turn] = left
            return False, elapsed

        # 保留时间用尽，进入读秒：本步余下的时间从 30 秒里扣
        self.base_left[self.turn] = 0
        overflow = -left
        if overflow >= self.config.byo_ms:
            return True, elapsed
        return False, elapsed
