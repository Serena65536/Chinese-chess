"""棋盘模型：坐标、棋子、FEN 读写、走子。

坐标约定
--------
- ``x`` 为纵线（列），0..8，对应 FEN 的 a..i
- ``y`` 为横线（行），0..9，**0 在最上方（黑方底线）**，与 FEN 文本行序一致
- 对外展示用 ``square_name(x, y)`` → ``"e4"`` 这种"列字母 + 距离底线的行号"

这样内部数据与 FEN 文本同向，画图时只需一次 y 翻转，避免两套坐标互相污染。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Iterable, Iterator, Optional

WIDTH = 9
HEIGHT = 10
FILES = "abcdefghi"
BOARD_SIZE = WIDTH * HEIGHT


class Color(IntEnum):
    RED = 0
    BLACK = 1

    @property
    def opponent(self) -> "Color":
        return Color.BLACK if self is Color.RED else Color.RED

    @property
    def is_red(self) -> bool:
        return self is Color.RED

    @property
    def label(self) -> str:
        return "红方" if self is Color.RED else "黑方"


class Kind(IntEnum):
    KING = 0
    ADVISOR = 1
    ELEPHANT = 2
    HORSE = 3
    ROOK = 4
    CANNON = 5
    PAWN = 6


_LETTER = {
    Kind.KING: "K",
    Kind.ADVISOR: "A",
    Kind.ELEPHANT: "E",
    Kind.HORSE: "H",
    Kind.ROOK: "R",
    Kind.CANNON: "C",
    Kind.PAWN: "P",
}
_KIND_FROM_LETTER = {letter: kind for kind, letter in _LETTER.items()}
#: 有些中国象棋记谱用 B/b 表示象（elephant），这里两种都认
_KIND_FROM_LETTER["B"] = Kind.ELEPHANT

GLYPHS: dict[Color, dict[Kind, str]] = {
    Color.RED: {
        Kind.KING: "帅",
        Kind.ADVISOR: "仕",
        Kind.ELEPHANT: "相",
        Kind.HORSE: "马",
        Kind.ROOK: "车",
        Kind.CANNON: "炮",
        Kind.PAWN: "兵",
    },
    Color.BLACK: {
        Kind.KING: "将",
        Kind.ADVISOR: "士",
        Kind.ELEPHANT: "象",
        Kind.HORSE: "马",
        Kind.ROOK: "车",
        Kind.CANNON: "炮",
        Kind.PAWN: "卒",
    },
}


@dataclass(frozen=True, slots=True)
class Piece:
    color: Color
    kind: Kind

    @property
    def letter(self) -> str:
        letter = _LETTER[self.kind]
        return letter if self.color is Color.RED else letter.lower()

    @property
    def glyph(self) -> str:
        return GLYPHS[self.color][self.kind]

    def __str__(self) -> str:
        return self.glyph


#: 标准起始局面。第 1 段为 10 行棋盘，第 2 段 ``w`` 表示红先。
INITIAL_FEN = (
    "rheakaehr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RHEAKAEHR w - - 0 1"
)


@dataclass(frozen=True, slots=True)
class Move:
    """一步棋。``src``/``dst`` 均为 ``(x, y)``。"""

    src: tuple[int, int]
    dst: tuple[int, int]

    def as_dict(self) -> dict[str, list[int]]:
        return {"from": list(self.src), "to": list(self.dst)}

    @classmethod
    def from_dict(cls, data: dict) -> "Move":
        return cls(tuple(data["from"]), tuple(data["to"]))  # type: ignore[arg-type]

    def __str__(self) -> str:
        return f"{square_name(*self.src)}-{square_name(*self.dst)}"


def index(x: int, y: int) -> int:
    return y * WIDTH + x


def inside(x: int, y: int) -> bool:
    return 0 <= x < WIDTH and 0 <= y < HEIGHT


def square_name(x: int, y: int) -> str:
    """``(4, 5)`` → ``"e4"``。行号以红方底线为 0，便于人读。"""
    return f"{FILES[x]}{HEIGHT - 1 - y}"


def square_from_name(name: str) -> tuple[int, int]:
    name = name.strip().lower()
    if len(name) < 2 or name[0] not in FILES:
        raise ValueError(f"不是合法坐标: {name!r}")
    x = FILES.index(name[0])
    y = HEIGHT - 1 - int(name[1:])
    if not inside(x, y):
        raise ValueError(f"坐标越界: {name!r}")
    return x, y


class Board:
    """9×10 棋盘。``squares`` 是长度 90 的列表，``None`` 表示空点。"""

    __slots__ = ("squares", "turn", "halfmove", "fullmove", "_king_cache")

    def __init__(
        self,
        squares: Optional[list[Optional[Piece]]] = None,
        turn: Color = Color.RED,
        halfmove: int = 0,
        fullmove: int = 1,
    ) -> None:
        self.squares: list[Optional[Piece]] = (
            list(squares) if squares is not None else [None] * BOARD_SIZE
        )
        if len(self.squares) != BOARD_SIZE:
            raise ValueError("squares 长度必须是 90")
        self.turn = turn
        self.halfmove = halfmove
        self.fullmove = fullmove
        self._king_cache: Optional[dict[Color, tuple[int, int]]] = None

    # ---------- 构造 ----------

    @classmethod
    def initial(cls) -> "Board":
        return cls.from_fen(INITIAL_FEN)

    @classmethod
    def from_fen(cls, fen: str) -> "Board":
        fields = fen.split()
        if not fields:
            raise ValueError("FEN 为空")
        rows = fields[0].split("/")
        if len(rows) != HEIGHT:
            raise ValueError(f"FEN 棋盘必须是 10 行，收到 {len(rows)} 行")

        squares: list[Optional[Piece]] = [None] * BOARD_SIZE
        for y, row in enumerate(rows):
            x = 0
            for ch in row:
                if ch.isdigit():
                    x += int(ch)
                    continue
                kind = _KIND_FROM_LETTER.get(ch.upper())
                if kind is None:
                    raise ValueError(f"无法识别的棋子字符: {ch!r}")
                if x >= WIDTH:
                    raise ValueError(f"第 {y + 1} 行超出 9 列")
                color = Color.RED if ch.isupper() else Color.BLACK
                squares[index(x, y)] = Piece(color, kind)
                x += 1
            if x != WIDTH:
                raise ValueError(f"第 {y + 1} 行宽度为 {x}，应为 9")

        turn = Color.BLACK
        if len(fields) > 1:
            token = fields[1].lower()
            if token in ("w", "r"):
                turn = Color.RED
            elif token in ("b",):
                turn = Color.BLACK
            else:
                raise ValueError(f"无法识别的走子方: {fields[1]!r}")

        halfmove = int(fields[4]) if len(fields) > 4 and fields[4].isdigit() else 0
        fullmove = int(fields[5]) if len(fields) > 5 and fields[5].isdigit() else 1
        return cls(squares, turn, halfmove, fullmove)

    def copy(self) -> "Board":
        return Board(self.squares, self.turn, self.halfmove, self.fullmove)

    # ---------- 访问 ----------

    def piece_at(self, x: int, y: int) -> Optional[Piece]:
        return self.squares[index(x, y)]

    def set_piece(self, x: int, y: int, piece: Optional[Piece]) -> None:
        self.squares[index(x, y)] = piece
        self._king_cache = None

    def pieces(self, color: Optional[Color] = None) -> Iterator[tuple[int, int, Piece]]:
        for pos, piece in enumerate(self.squares):
            if piece is None:
                continue
            if color is not None and piece.color is not color:
                continue
            yield pos % WIDTH, pos // WIDTH, piece

    def find_king(self, color: Color) -> Optional[tuple[int, int]]:
        if self._king_cache is None:
            self._king_cache = {}
        if color not in self._king_cache:
            self._king_cache[color] = next(
                ((x, y) for x, y, p in self.pieces(color) if p.kind is Kind.KING),
                None,  # type: ignore[arg-type]
            )
        return self._king_cache[color]

    # ---------- 走子 ----------

    def make(self, move: "Move") -> tuple[Optional[Piece], Color, int, int]:
        """走一步并返回撤销所需的现场快照（被吃的子、走子方、两个计数器）。

        与 :meth:`apply_move` 的区别：``make`` 保留全部撤销信息，供搜索/合法性判断
        高频使用；``apply_move`` 只返回被吃的子，用在不需要回退的场合。
        """
        piece = self.piece_at(*move.src)
        if piece is None:
            raise ValueError(f"{square_name(*move.src)} 上没有棋子")
        captured = self.squares[index(*move.dst)]
        snapshot = (captured, self.turn, self.halfmove, self.fullmove)
        self.squares[index(*move.dst)] = piece
        self.squares[index(*move.src)] = None
        self.halfmove = 0 if captured else self.halfmove + 1
        if self.turn is Color.BLACK:
            self.fullmove += 1
        self.turn = self.turn.opponent
        self._king_cache = None
        return snapshot

    def unmake(self, move: "Move", snapshot: tuple[Optional[Piece], Color, int, int]) -> None:
        captured, turn, halfmove, fullmove = snapshot
        piece = self.squares[index(*move.dst)]
        self.squares[index(*move.src)] = piece
        self.squares[index(*move.dst)] = captured
        self.turn = turn
        self.halfmove = halfmove
        self.fullmove = fullmove
        self._king_cache = None

    def apply_move(self, move: "Move") -> Optional[Piece]:
        """摆上棋盘的走子（不做合法性校验），返回被吃掉的子。"""
        captured, *_ = self.make(move)
        return captured

    def undo_move(self, move: Move, captured: Optional[Piece]) -> None:
        piece = self.squares[index(*move.dst)]
        if piece is None:
            raise ValueError("撤销的着法没有落点棋子")
        self.squares[index(*move.src)] = piece
        self.squares[index(*move.dst)] = captured
        self.turn = self.turn.opponent
        self._king_cache = None

    # ---------- 序列化 ----------

    def to_fen(self) -> str:
        rows: list[str] = []
        for y in range(HEIGHT):
            row = ""
            empty = 0
            for x in range(WIDTH):
                piece = self.piece_at(x, y)
                if piece is None:
                    empty += 1
                    continue
                if empty:
                    row += str(empty)
                    empty = 0
                row += piece.letter
            if empty:
                row += str(empty)
            rows.append(row)
        board_part = "/".join(rows)
        side = "w" if self.turn is Color.RED else "b"
        return f"{board_part} {side} - - {self.halfmove} {self.fullmove}"

    def position_key(self) -> str:
        """用于重复局面判定：只含局面与走子方。"""
        board_part, side, *_ = self.to_fen().split()
        return f"{board_part} {side}"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Board):
            return NotImplemented
        return self.position_key() == other.position_key()

    def __repr__(self) -> str:
        return f"<Board {self.to_fen()}>"
