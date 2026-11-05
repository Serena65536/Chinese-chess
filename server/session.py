"""联机房间会话：权威对局 + 读秒 + 断线暂停 + 重连 + 再来一局。

服务端是唯一的裁判：每一手都做三重校验（轮次、合法着法、没超时），
客户端只是把结果画出来。所以改客户端改不了棋局。
"""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, field
from typing import Optional

from xiangqi_core import Board, Color, Game, Move, Status, is_legal

from .clock import Clock, ClockConfig

#: 掉线宽容期：期间双方时钟都暂停，超时判掉线方负
GRACE_MS = 90_000
#: 空房间保留时长
ROOM_TTL_S = 30 * 60


class ProtocolError(Exception):
    """客户端消息不合法。"""


@dataclass
class Seat:
    index: int
    name: str
    token: str = field(default_factory=lambda: secrets.token_urlsafe(12))
    avatar: Optional[str] = None
    ws: object = None
    ready: bool = False
    connected: bool = True
    disconnected_at: Optional[float] = None

    def as_payload(self) -> dict:
        return {
            "seat": self.index,
            "name": self.name,
            "avatar": self.avatar,
            "ready": self.ready,
            "connected": self.connected,
        }


@dataclass
class Session:
    code: str
    config: ClockConfig = field(default_factory=ClockConfig)
    seats: list[Seat] = field(default_factory=list)
    game: Optional[Game] = None
    clock: Optional[Clock] = None
    phase: str = "waiting"  # waiting | playing | finished
    seq: int = 0
    red_seat: int = 0
    created_at: float = field(default_factory=time.monotonic)
    rematch_votes: set[int] = field(default_factory=set)
    draw_offer: Optional[int] = None
    last_seen: float = field(default_factory=time.monotonic)

    # ---------- 基础 ----------

    @property
    def full(self) -> bool:
        return len(self.seats) >= 2

    def seat_by_token(self, token: str) -> Optional[Seat]:
        return next((s for s in self.seats if s.token == token), None)

    def seat(self, index: int) -> Optional[Seat]:
        return next((s for s in self.seats if s.index == index), None)

    def turn_color(self) -> Color:
        assert self.game is not None
        return self.game.turn

    def turn_seat(self) -> int:
        return self.red_seat if self.turn_color() is Color.RED else 1 - self.red_seat

    def seat_color(self, seat: Seat) -> Color:
        return Color.RED if seat.index == self.red_seat else Color.BLACK

    def seats_payload(self) -> list[dict]:
        return [seat.as_payload() for seat in self.seats]

    # ---------- 房间 ----------

    def add_seat(self, name: str, avatar: Optional[str] = None) -> Seat:
        if self.full:
            raise ProtocolError("房间已满")
        seat = Seat(
            index=len(self.seats),
            name=name.strip() or f"玩家{len(self.seats) + 1}",
            avatar=avatar or None,
        )
        self.seats.append(seat)
        self.last_seen = time.monotonic()
        return seat

    def room_payload(self) -> dict:
        return {
            "code": self.code,
            "phase": self.phase,
            "seats": self.seats_payload(),
            "redSeat": self.red_seat,
            "clock": self.config.as_payload(),
        }

    # ---------- 开局 ----------

    def mark_ready(self, seat: Seat, now: float) -> Optional[dict]:
        if self.phase == "playing":
            raise ProtocolError("对局已经开始了")
        seat.ready = True
        self.last_seen = now
        if len(self.seats) == 2 and all(s.ready for s in self.seats):
            return self._start(now)
        return None

    def _start(self, now: float) -> dict:
        self.game = Game()
        self.clock = Clock(self.config)
        self.clock.begin(Color.RED, now)
        self.phase = "playing"
        self.seq = 0
        self.rematch_votes.clear()
        self.draw_offer = None
        for seat in self.seats:
            seat.ready = True
        return self.start_payload(now)

    def start_payload(self, now: float) -> dict:
        assert self.game is not None and self.clock is not None
        return {
            "fen": self.game.board.to_fen(),
            "redSeat": self.red_seat,
            "seats": self.seats_payload(),
            "clock": self.clock.snapshot(now),
            "seq": self.seq,
            "record": self.game.record_lines(),
        }

    # ---------- 走子 ----------

    def apply_move(self, seat: Seat, move: Move, now: float) -> dict:
        if self.phase != "playing" or self.game is None or self.clock is None:
            raise ProtocolError("对局还没开始")
        if self.clock.paused:
            raise ProtocolError("对手掉线中，对局暂停")
        if seat.index != self.turn_seat():
            raise ProtocolError("还没轮到你走")
        if not is_legal(self.game.board, move):
            raise ProtocolError("非法着法")

        timed_out, used = self.clock.charge(now)
        if timed_out:
            return self._finish(self.game.timeout(self.turn_color()), now, extra={"timedOut": True})

        outcome = self.game.play(move)
        self.seq += 1
        self.last_seen = now

        if outcome.finished:
            payload = {
                "seq": self.seq,
                "seat": seat.index,
                "move": move.as_dict(),
                "fen": self.game.board.to_fen(),
                "clock": self.clock.snapshot(now),
                "record": self.game.record_lines(),
                "status": self._status_payload(outcome),
            }
            return self._finish(outcome, now, move_payload=payload)

        # 先换表再取快照：否则扣完时还会把本步用时算进剩余时间里（扣两次）
        self.clock.switch_to(self.turn_color(), now)
        return {
            "seq": self.seq,
            "seat": seat.index,
            "move": move.as_dict(),
            "fen": self.game.board.to_fen(),
            "clock": self.clock.snapshot(now),
            "record": self.game.record_lines(),
            "status": self._status_payload(outcome),
        }

    def _status_payload(self, outcome) -> dict:  # noqa: ANN001
        return {
            "check": outcome.status is Status.CHECK,
            "finished": outcome.finished,
            "winner": self._winner_seat(outcome),
            "reason": outcome.reason,
            "text": outcome.text,
        }

    def _winner_seat(self, outcome) -> Optional[int]:  # noqa: ANN001
        if outcome.winner is None:
            return None
        return self.red_seat if outcome.winner is Color.RED else 1 - self.red_seat

    def _finish(self, outcome, now: float, *, extra: Optional[dict] = None, move_payload=None) -> dict:  # noqa: ANN001
        assert self.clock is not None
        # 先取快照再停表：停表后 remaining_for 会退化成 0，界面上会显示 00:00
        clock_snapshot = self.clock.snapshot(now)
        self.phase = "finished"
        self.clock.finish()
        payload = {
            "winner": self._winner_seat(outcome),
            "reason": outcome.reason,
            "text": outcome.text,
            "status": outcome.status.value,
            "clock": clock_snapshot,
        }
        if extra:
            payload.update(extra)
        if move_payload is not None:
            payload["lastMove"] = move_payload
        return payload

    # ---------- 计时 ----------

    def tick(self, now: float) -> Optional[dict]:
        """服务端定时检查：超时判负、掉线超宽容期判负。"""
        if self.phase != "playing" or self.game is None or self.clock is None:
            return None

        for seat in self.seats:
            if not seat.connected and seat.disconnected_at is not None:
                if (now - seat.disconnected_at) * 1000 > GRACE_MS:
                    loser = self.seat_color(seat)
                    outcome = self.game.timeout(loser)
                    return self._finish(outcome, now, extra={"dropped": seat.index})

        if self.clock.paused:
            return None

        if self.clock.remaining_ms(now) <= 0:
            outcome = self.game.timeout(self.turn_color())
            return self._finish(outcome, now, extra={"timedOut": True})
        return None

    def clock_payload(self, now: float) -> dict:
        assert self.clock is not None
        payload = self.clock.snapshot(now)
        payload.update({"seq": self.seq, "turnSeat": self.turn_seat()})
        return payload

    # ---------- 人工结局 ----------

    def resign(self, seat: Seat, now: float) -> dict:
        if self.phase == "finished" or self.game is None:
            raise ProtocolError("对局没在进行")
        outcome = self.game.resign(self.seat_color(seat))
        return self._finish(outcome, now)

    def offer_draw(self, seat: Seat) -> None:
        if self.phase != "playing":
            raise ProtocolError("对局没在进行")
        self.draw_offer = seat.index

    def answer_draw(self, seat: Seat, accept: bool, now: float) -> Optional[dict]:
        if self.draw_offer is None or self.draw_offer == seat.index:
            raise ProtocolError("没有待回应的和棋请求")
        offered_by = self.draw_offer
        self.draw_offer = None
        if not accept:
            return None
        return self._finish(self.game.agree_draw(), now, extra={"drawBy": offered_by})

    # ---------- 断线与重连 ----------

    def disconnect(self, seat: Seat, now: float) -> dict:
        seat.connected = False
        seat.disconnected_at = now
        if self.clock is not None and self.phase == "playing":
            self.clock.pause(now)
        return {"seat": seat.index, "graceMs": GRACE_MS}

    def reconnect(self, seat: Seat, now: float) -> dict:
        seat.connected = True
        seat.disconnected_at = None
        if self.clock is not None and self.phase == "playing":
            self.clock.resume(now)
        payload = {
            "seat": seat.index,
            "phase": self.phase,
            "room": self.room_payload(),
        }
        if self.phase == "playing":
            payload["game"] = self.start_payload(now)
        elif self.phase == "finished" and self.game is not None:
            payload["finished"] = self._status_payload(self.game.outcome)
        return payload

    # ---------- 再来一局 ----------

    def rematch(self, seat: Seat, now: float) -> Optional[dict]:
        if self.phase != "finished":
            raise ProtocolError("这一局还没结束")
        self.rematch_votes.add(seat.index)
        if len(self.rematch_votes) < 2:
            return None
        # 轮换先手
        self.red_seat = 1 - self.red_seat
        for s in self.seats:
            s.ready = False
        self.rematch_votes.clear()
        return self._start(now)


class RoomRegistry:
    def __init__(self) -> None:
        self.rooms: dict[str, Session] = {}

    def create(self, config: Optional[ClockConfig] = None) -> Session:
        for _ in range(64):
            code = f"{secrets.randbelow(1_000_000):06d}"
            if code not in self.rooms:
                session = Session(code=code, config=config or ClockConfig())
                self.rooms[code] = session
                return session
        raise RuntimeError("房间码分配失败")

    def get(self, code: str) -> Optional[Session]:
        return self.rooms.get(code.strip())

    def drop(self, session: Session) -> None:
        self.rooms.pop(session.code, None)

    def gc(self, now: float) -> list[str]:
        stale = [
            code
            for code, room in self.rooms.items()
            if not any(seat.connected for seat in room.seats) and now - room.last_seen > ROOM_TTL_S
        ]
        for code in stale:
            self.rooms.pop(code, None)
        return stale
