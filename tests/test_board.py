"""棋盘模型测试：FEN 往返、坐标、走子。"""

from __future__ import annotations

import pytest

from xiangqi_core import INITIAL_FEN, Board, Color, Kind, Move, Piece, square_from_name, square_name


def test_initial_position_has_32_pieces():
    board = Board.initial()
    red = list(board.pieces(Color.RED))
    black = list(board.pieces(Color.BLACK))
    assert len(red) == 16
    assert len(black) == 16


def test_initial_fen_roundtrip():
    board = Board.initial()
    assert board.to_fen() == INITIAL_FEN
    assert Board.from_fen(board.to_fen()) == board


def test_square_names():
    assert square_name(0, 9) == "a0"
    assert square_name(4, 9) == "e0"
    assert square_name(8, 0) == "i9"
    assert square_from_name("e4") == (4, 5)
    assert square_from_name("a0") == (0, 9)


def test_kings_are_on_expected_squares():
    board = Board.initial()
    assert board.find_king(Color.RED) == (4, 9)
    assert board.find_king(Color.BLACK) == (4, 0)


def test_apply_move_captures_and_flips_turn():
    board = Board.from_fen("4k4/9/9/9/9/9/9/9/4R4/4K4 w - - 0 1")
    red_rook = board.piece_at(4, 8)
    assert red_rook == Piece(Color.RED, Kind.ROOK)

    captured = board.apply_move(Move((4, 8), (4, 0)))
    assert captured == Piece(Color.BLACK, Kind.KING)
    assert board.piece_at(4, 0) == red_rook
    assert board.piece_at(4, 8) is None
    assert board.turn is Color.BLACK


def test_undo_move_restores_position():
    board = Board.initial()
    before = board.position_key()
    move = Move((1, 7), (4, 7))
    captured = board.apply_move(move)
    board.undo_move(move, captured)
    assert board.position_key() == before
    assert board.turn is Color.RED


def test_fen_rejects_bad_input():
    with pytest.raises(ValueError):
        Board.from_fen("9/9/9 w")
    with pytest.raises(ValueError):
        Board.from_fen("9/9/9/9/9/9/9/9/9/9/9 w")
    with pytest.raises(ValueError):
        Board.from_fen("XXXX/9/9/9/9/9/9/9/9/4K4 w")


def test_position_key_ignores_counters():
    board = Board.initial()
    board.halfmove = 7
    board.fullmove = 12
    assert board.position_key().count(" ") == 1
