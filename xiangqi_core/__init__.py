"""一起来下棋 · 棋规内核（纯 Python，零 Qt 依赖）。

分层：
- ``board``  —— 棋盘、FEN、走子/撤销
- ``moves``  —— 伪合法着法（各棋子怎么走）
- ``rules``  —— 合法着法（过滤送将、飞将）、被将军判定
- ``game``   —— 对局状态机（将死、困毙、三次重复、60 回合、长将判负）
"""

from .board import (
    INITIAL_FEN,
    Board,
    Color,
    Kind,
    Move,
    Piece,
    square_from_name,
    square_name,
)
from .game import HALF_MOVE_LIMIT, REPETITION_LIMIT, Entry, Game, Outcome, Status
from .moves import generate_pseudo_moves, is_pseudo_legal
from .rules import (
    has_legal_move,
    in_check,
    is_attacked,
    is_legal,
    king_square,
    kings_face,
    legal_moves,
    legal_moves_for_color,
    threatened_pieces,
)

__all__ = [
    "HALF_MOVE_LIMIT",
    "INITIAL_FEN",
    "REPETITION_LIMIT",
    "Board",
    "Color",
    "Entry",
    "Game",
    "Kind",
    "Move",
    "Outcome",
    "Piece",
    "Status",
    "generate_pseudo_moves",
    "has_legal_move",
    "in_check",
    "is_attacked",
    "is_legal",
    "is_pseudo_legal",
    "king_square",
    "kings_face",
    "legal_moves",
    "legal_moves_for_color",
    "square_from_name",
    "square_name",
    "threatened_pieces",
]

__version__ = "0.2.0-m1"
