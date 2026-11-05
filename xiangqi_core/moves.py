"""伪合法着法生成（M0 阶段）。

"伪合法"= 遵守各棋子的走法规则与阻挡规则，但**暂不检查送将**。
M1 会在此之上加一层"走完这一步后自己不能处于被将军状态"的过滤。

规则细节（按常见中国象棋口径）：
- 马腿被挡则该方向不可走
- 象/相走"田"字，塞象眼不可走，且不得过河
- 炮吃子需且仅需一个炮架
- 兵/卒过河前只能向前，过河后可横走
- 士/仕、将/帅只能在九宫内按斜线/直线各一格
"""

from __future__ import annotations

from typing import Iterator

from .board import (
    HEIGHT,
    WIDTH,
    Board,
    Color,
    Kind,
    Move,
    Piece,
    inside,
    square_name,
)

ORTHOGONAL = ((1, 0), (-1, 0), (0, 1), (0, -1))
DIAGONAL = ((1, 1), (1, -1), (-1, 1), (-1, -1))

#: (dx, dy, 马腿 dx, 马腿 dy)
HORSE_STEPS = (
    (1, 2, 0, 1),
    (2, 1, 1, 0),
    (-1, 2, 0, 1),
    (-2, 1, -1, 0),
    (1, -2, 0, -1),
    (2, -1, 1, 0),
    (-1, -2, 0, -1),
    (-2, -1, -1, 0),
)

#: (dx, dy)
ELEPHANT_STEPS = ((2, 2), (2, -2), (-2, 2), (-2, -2))


def palace_bounds(color: Color) -> tuple[range, range]:
    """返回 (x 范围, y 范围)。"""
    if color is Color.RED:
        return range(3, 6), range(7, 10)
    return range(3, 6), range(0, 3)


def in_palace(x: int, y: int, color: Color) -> bool:
    xs, ys = palace_bounds(color)
    return x in xs and y in ys


def on_own_half(y: int, color: Color) -> bool:
    """是否在本方河界内（红方在下半，y 5..9）。"""
    return y >= 5 if color is Color.RED else y <= 4


def forward_dir(color: Color) -> int:
    """前进方向：红方向 y 减小方向走。"""
    return -1 if color is Color.RED else 1


def _add(
    board: Board,
    out: list[tuple[int, int]],
    x: int,
    y: int,
    piece: Piece,
) -> bool:
    """尝试把 (x, y) 加入可走点，返回该点是否被己方棋子占据（用于滑动棋子提前终止）。"""
    target = board.piece_at(x, y)
    if target is None:
        out.append((x, y))
        return False
    if target.color is not piece.color:
        out.append((x, y))
    return True


def _rook_moves(board: Board, x: int, y: int, piece: Piece) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for dx, dy in ORTHOGONAL:
        cx, cy = x + dx, y + dy
        while inside(cx, cy):
            if _add(board, out, cx, cy, piece):
                break
            cx += dx
            cy += dy
    return out


def _cannon_moves(board: Board, x: int, y: int, piece: Piece) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for dx, dy in ORTHOGONAL:
        cx, cy = x + dx, y + dy
        screen = False
        while inside(cx, cy):
            target = board.piece_at(cx, cy)
            if not screen:
                if target is None:
                    out.append((cx, cy))
                else:
                    screen = True  # 第一个子当炮架，之后才可吃
            else:
                if target is not None:
                    if target.color is not piece.color:
                        out.append((cx, cy))
                    break
            cx += dx
            cy += dy
    return out


def _horse_moves(board: Board, x: int, y: int, piece: Piece) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for dx, dy, lx, ly in HORSE_STEPS:
        if not inside(x + dx, y + dy):
            continue
        if board.piece_at(x + lx, y + ly) is not None:  # 蹇马腿
            continue
        _add(board, out, x + dx, y + dy, piece)
    return out


def _elephant_moves(board: Board, x: int, y: int, piece: Piece) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for dx, dy in ELEPHANT_STEPS:
        nx, ny = x + dx, y + dy
        if not inside(nx, ny):
            continue
        if not on_own_half(ny, piece.color):  # 象不过河
            continue
        if board.piece_at(x + dx // 2, y + dy // 2) is not None:  # 塞象眼
            continue
        _add(board, out, nx, ny, piece)
    return out


def _advisor_moves(board: Board, x: int, y: int, piece: Piece) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for dx, dy in DIAGONAL:
        nx, ny = x + dx, y + dy
        if inside(nx, ny) and in_palace(nx, ny, piece.color):
            _add(board, out, nx, ny, piece)
    return out


def _king_moves(board: Board, x: int, y: int, piece: Piece) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for dx, dy in ORTHOGONAL:
        nx, ny = x + dx, y + dy
        if inside(nx, ny) and in_palace(nx, ny, piece.color):
            _add(board, out, nx, ny, piece)
    # TODO(M1): 飞将（将帅照面）判定
    return out


def _pawn_moves(board: Board, x: int, y: int, piece: Piece) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    dy = forward_dir(piece.color)
    if inside(x, y + dy):
        _add(board, out, x, y + dy, piece)
    if not on_own_half(y, piece.color):  # 过河后可横走
        for dx in (-1, 1):
            if inside(x + dx, y):
                _add(board, out, x + dx, y, piece)
    return out


_GENERATORS = {
    Kind.ROOK: _rook_moves,
    Kind.CANNON: _cannon_moves,
    Kind.HORSE: _horse_moves,
    Kind.ELEPHANT: _elephant_moves,
    Kind.ADVISOR: _advisor_moves,
    Kind.KING: _king_moves,
    Kind.PAWN: _pawn_moves,
}


def generate_pseudo_moves(board: Board, src: tuple[int, int]) -> list[tuple[int, int]]:
    """给定格子上的棋子，返回它能走到的所有落点（未做送将过滤）。"""
    x, y = src
    piece = board.piece_at(x, y)
    if piece is None:
        return []
    return _GENERATORS[piece.kind](board, x, y, piece)


def moves_for_color(board: Board, color: Color) -> Iterator[Move]:
    for x, y, piece in board.pieces(color):
        for dst in generate_pseudo_moves(board, (x, y)):
            yield Move((x, y), dst)


def is_pseudo_legal(board: Board, move: Move) -> bool:
    piece = board.piece_at(*move.src)
    if piece is None or piece.color is not board.turn:
        return False
    return move.dst in generate_pseudo_moves(board, move.src)


def describe_targets(board: Board, src: tuple[int, int]) -> str:
    """调试用：把可走点打印成 ``"e4,f3"``。"""
    return ",".join(square_name(x, y) for x, y in generate_pseudo_moves(board, src))
