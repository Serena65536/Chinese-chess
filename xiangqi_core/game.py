"""对局状态机：走子、终局判定、循环判罚（长将 / 三次重复 / 60 回合）。

口径（对应决策 D5「实用完整版」）：
- 将死：判负
- 困毙（无子可动但未被将军）：**判负**，不是和棋——这是象棋与国际象棋最容易搞混的一条
- 三次重复局面：若其中一方每一步都在将军（长将），长将方判负；否则判和
- 60 回合（120 个半回合）无吃子：判和
- 长捉 / 长打：只做检测并给提示，不自动判罚（避免误判引发争议）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from .board import Board, Color, Kind, Move, Piece, square_name
from .rules import has_legal_move, in_check, is_legal, legal_moves, threatened_pieces

#: 同一局面出现几次判和/判负
REPETITION_LIMIT = 3
#: 自然限着：60 回合 = 120 个半回合无吃子
HALF_MOVE_LIMIT = 120


class Status(Enum):
    ONGOING = "ongoing"
    CHECK = "check"
    CHECKMATE = "checkmate"
    STALEMATE = "stalemate"
    DRAW_REPETITION = "draw_repetition"
    DRAW_60 = "draw_60"
    LOSS_PERPETUAL = "loss_perpetual"
    RESIGN = "resign"
    DRAW_AGREED = "draw_agreed"
    TIMEOUT = "timeout"


_FINISHED = {
    Status.CHECKMATE,
    Status.STALEMATE,
    Status.DRAW_REPETITION,
    Status.DRAW_60,
    Status.LOSS_PERPETUAL,
    Status.RESIGN,
    Status.DRAW_AGREED,
    Status.TIMEOUT,
}


@dataclass
class Outcome:
    status: Status
    winner: Optional[Color] = None
    reason: str = ""
    hint: Optional[str] = None

    @property
    def finished(self) -> bool:
        return self.status in _FINISHED

    @property
    def is_draw(self) -> bool:
        return self.status in (Status.DRAW_REPETITION, Status.DRAW_60, Status.DRAW_AGREED)

    @property
    def text(self) -> str:
        if self.status is Status.CHECK:
            return "将军！"
        if self.status is Status.ONGOING:
            return ""
        if self.is_draw:
            return f"和棋 · {self.reason}"
        if self.winner is not None:
            return f"{self.winner.label}胜 · {self.reason}"
        return self.reason


@dataclass
class Entry:
    """一步棋的完整记录，撤销与判罚都靠它。"""

    move: Move
    piece: Piece
    mover: Color
    captured: Optional[Piece]
    snapshot: tuple
    gave_check: bool
    key: str
    threatens: frozenset[tuple[int, int]] = field(default_factory=frozenset)

    def line(self, index: int) -> str:
        capture = f"×{self.captured.glyph}" if self.captured else ""
        check = " 将" if self.gave_check else ""
        return f"{index}. {self.piece.glyph} {square_name(*self.move.src)}-{square_name(*self.move.dst)}{capture}{check}"


class Game:
    def __init__(self, board: Optional[Board] = None) -> None:
        self.board = board or Board.initial()
        self.entries: list[Entry] = []
        self.keys: list[str] = [self.board.position_key()]
        self.outcome = self._live_outcome()

    # ---------- 查询 ----------

    @property
    def turn(self) -> Color:
        return self.board.turn

    @property
    def is_over(self) -> bool:
        return self.outcome.finished

    def legal_targets(self, src: tuple[int, int]) -> list[tuple[int, int]]:
        if self.is_over:
            return []
        return legal_moves(self.board, src)

    def record_lines(self) -> list[str]:
        return [entry.line(i + 1) for i, entry in enumerate(self.entries)]

    # ---------- 走子 ----------

    def play(self, move: Move) -> Outcome:
        if self.is_over:
            raise ValueError("对局已结束")
        if not is_legal(self.board, move):
            raise ValueError(f"非法着法: {move}")

        piece = self.board.piece_at(*move.src)
        assert piece is not None
        mover = self.board.turn
        snapshot = self.board.make(move)
        gave_check = in_check(self.board, self.board.turn)
        threats = threatened_pieces(self.board, self.board.turn)

        entry = Entry(
            move=move,
            piece=piece,
            mover=mover,
            captured=snapshot[0],
            snapshot=snapshot,
            gave_check=gave_check,
            key=self.board.position_key(),
            threatens=frozenset(threats),
        )
        self.entries.append(entry)
        self.keys.append(entry.key)

        self.outcome = self._evaluate(entry)
        return self.outcome

    def undo(self) -> bool:
        if not self.entries:
            return False
        entry = self.entries.pop()
        self.board.unmake(entry.move, entry.snapshot)
        self.keys.pop()
        self.outcome = self._live_outcome()
        return True

    def reset(self) -> None:
        self.board = Board.initial()
        self.entries.clear()
        self.keys = [self.board.position_key()]
        self.outcome = self._live_outcome()

    def set_outcome(self, status, winner=None, reason: str = "", hint: str | None = None) -> None:  # noqa: ANN001
        """直接写入结局（联机模式下结局由服务端裁定，客户端只负责显示）。"""
        if isinstance(status, str):
            try:
                status = Status(status)
            except ValueError:
                status = Status.ONGOING
        self.outcome = Outcome(status=status, winner=winner, reason=reason, hint=hint)

    # ---------- 人工结局 ----------

    def resign(self, color: Color) -> Outcome:
        self.outcome = Outcome(Status.RESIGN, winner=color.opponent, reason=f"{color.label}认输")
        return self.outcome

    def agree_draw(self) -> Outcome:
        self.outcome = Outcome(Status.DRAW_AGREED, reason="双方同意和棋")
        return self.outcome

    def timeout(self, color: Color) -> Outcome:
        self.outcome = Outcome(Status.TIMEOUT, winner=color.opponent, reason=f"{color.label}超时")
        return self.outcome

    # ---------- 判定 ----------

    def _live_outcome(self) -> Outcome:
        if in_check(self.board, self.board.turn):
            return Outcome(Status.CHECK, reason="将军")
        return Outcome(Status.ONGOING)

    def _evaluate(self, entry: Entry) -> Outcome:
        opponent = self.board.turn

        if not has_legal_move(self.board):
            if in_check(self.board, opponent):
                return Outcome(Status.CHECKMATE, winner=entry.mover, reason="将死")
            return Outcome(Status.STALEMATE, winner=entry.mover, reason="困毙，无子可动")

        repetition = self._repetition_outcome()
        if repetition is not None:
            return repetition

        if self.board.halfmove >= HALF_MOVE_LIMIT:
            return Outcome(Status.DRAW_60, reason="60 回合无吃子")

        if entry.gave_check:
            return Outcome(Status.CHECK, reason="将军")
        return Outcome(Status.ONGOING)

    def _repetition_outcome(self) -> Optional[Outcome]:
        key = self.keys[-1]
        occurrences = [i for i, item in enumerate(self.keys) if item == key]
        if len(occurrences) < REPETITION_LIMIT:
            return None

        start = occurrences[-REPETITION_LIMIT]
        cycle = self.entries[start:]
        loser = self._perpetual_checker(cycle)
        if loser is not None:
            return Outcome(
                Status.LOSS_PERPETUAL,
                winner=loser.opponent,
                reason=f"{loser.label}长将，判负",
            )

        return Outcome(
            Status.DRAW_REPETITION,
            reason="三次重复局面",
            hint=self._chase_hint(cycle),
        )

    @staticmethod
    def _perpetual_checker(cycle: list[Entry]) -> Optional[Color]:
        """返回"每一步都在将军"的那一方（若只有一方如此）。"""
        result: Optional[Color] = None
        for color in (Color.RED, Color.BLACK):
            moves = [e for e in cycle if e.mover is color]
            if len(moves) >= 2 and all(e.gave_check for e in moves):
                if result is not None:  # 双方都在长将，按和棋处理
                    return None
                result = color
        return result

    def _chase_hint(self, cycle: list[Entry]) -> Optional[str]:
        """长捉只提示：看某一方是否在循环里一直盯着同一批子。"""
        for color in (Color.RED, Color.BLACK):
            moves = [e for e in cycle if e.mover is color and e.threatens]
            if len(moves) < 2:
                continue
            common = set(moves[0].threatens)
            for entry in moves[1:]:
                common &= set(entry.threatens)
            if not common:
                continue
            target = next(iter(sorted(common)))
            piece = self.board.piece_at(*target)
            name = piece.glyph if piece else "子"
            return (
                f"长捉提示：{color.label}反复威胁{name}（{square_name(*target)}），"
                "系统不自动判罚，请双方协商。"
            )
        return None
