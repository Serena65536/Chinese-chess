"""合法着法判定：在伪合法着法之上加"走完不能让自己被将军"。

中国象棋跟国际象棋的两处关键差异，这里都处理了：
1. **将帅照面**（飞将）本身就算"被将"——所以把将帅之间清空是非法着法。
2. 困毙（无子可动但没被将军）在象棋里判**负**，不是和棋。判定放在 game.py。
"""

from __future__ import annotations

from typing import Iterator, Optional

from .board import Board, Color, Kind, Move, Piece
from .moves import generate_pseudo_moves


def king_square(board: Board, color: Color) -> Optional[tuple[int, int]]:
    return board.find_king(color)


def kings_face(board: Board) -> bool:
    """将帅是否照面（同一纵线且中间无子）。"""
    red = board.find_king(Color.RED)
    black = board.find_king(Color.BLACK)
    if red is None or black is None:
        return False
    if red[0] != black[0]:
        return False
    x = red[0]
    low, high = sorted((red[1], black[1]))
    for y in range(low + 1, high):
        if board.piece_at(x, y) is not None:
            return False
    return True


def is_attacked(board: Board, square: tuple[int, int], by_color: Color) -> bool:
    """``square`` 是否被 ``by_color`` 的任一棋子攻击（兵力覆盖，不考虑对方是否送将）。"""
    for x, y, _piece in board.pieces(by_color):
        if square in generate_pseudo_moves(board, (x, y)):
            return True
    return False


def in_check(board: Board, color: Color) -> bool:
    """该方是否处于被将军状态（含将帅照面）。"""
    square = board.find_king(color)
    if square is None:
        return False
    if kings_face(board):
        return True
    return is_attacked(board, square, color.opponent)


def move_leaves_king_safe(board: Board, move: Move) -> bool:
    """假设性走一步，判断走子方是否安全（走完不被将军）。"""
    piece = board.piece_at(*move.src)
    if piece is None:
        return False
    snapshot = board.make(move)
    try:
        return not in_check(board, piece.color)
    finally:
        board.unmake(move, snapshot)


def legal_moves(board: Board, src: tuple[int, int]) -> list[tuple[int, int]]:
    """某格棋子的全部合法落点（已过滤送将、飞将与吃将）。"""
    piece = board.piece_at(*src)
    if piece is None or piece.color is not board.turn:
        return []
    result: list[tuple[int, int]] = []
    for dst in generate_pseudo_moves(board, src):
        target = board.piece_at(*dst)
        if target is not None and target.kind is Kind.KING:
            continue  # 不能吃将，胜负由将死判定
        if move_leaves_king_safe(board, Move(src, dst)):
            result.append(dst)
    return result


def legal_moves_for_color(board: Board, color: Color) -> Iterator[Move]:
    for x, y, piece in board.pieces(color):
        if piece.color is not color:
            continue
        for dst in legal_moves(board, (x, y)):
            yield Move((x, y), dst)


def has_legal_move(board: Board) -> bool:
    """轮走方是否还有棋可走（终局判定的核心）。"""
    for x, y, piece in board.pieces(board.turn):
        for dst in generate_pseudo_moves(board, (x, y)):
            target = board.piece_at(*dst)
            if target is not None and target.kind is Kind.KING:
                continue
            if move_leaves_king_safe(board, Move((x, y), dst)):
                return True
    return False


def is_legal(board: Board, move: Move) -> bool:
    piece = board.piece_at(*move.src)
    if piece is None or piece.color is not board.turn:
        return False
    if move.dst not in generate_pseudo_moves(board, move.src):
        return False
    target = board.piece_at(*move.dst)
    if target is not None and target.kind is Kind.KING:
        return False
    return move_leaves_king_safe(board, move)


def attacked_squares(board: Board, color: Color) -> set[tuple[int, int]]:
    """该方所有棋子能攻击到的格子（长捉提示用）。"""
    squares: set[tuple[int, int]] = set()
    for x, y, _piece in board.pieces(color):
        squares.update(generate_pseudo_moves(board, (x, y)))
    return squares


def threatened_pieces(board: Board, color: Color) -> set[tuple[int, int]]:
    """``color`` 一方的、正被对手威胁的棋子位置（长捉提示用）。"""
    attacked = attacked_squares(board, color.opponent)
    return {(x, y) for x, y, piece in board.pieces(color) if piece.kind is not Kind.KING and (x, y) in attacked}
