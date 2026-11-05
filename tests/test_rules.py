"""合法着法判定：自杀检测、飞将、被将军、终局基础。

FEN 行序自上而下（y=0 是黑方底线），与 xiangqi_core 内部一致。
"""

from __future__ import annotations

import pytest

from xiangqi_core import (
    Board,
    Color,
    Move,
    has_legal_move,
    in_check,
    is_attacked,
    is_legal,
    kings_face,
    legal_moves,
)


def board_of(*rows: str, side: str = "w") -> Board:
    assert len(rows) == 10, "要传 10 行"
    return Board.from_fen("/".join(rows) + f" {side} - - 0 1")


# ---------- 起始局面 ----------


def test_initial_red_has_44_legal_moves():
    board = Board.initial()
    total = sum(len(legal_moves(board, (x, y))) for x, y, p in board.pieces(Color.RED))
    assert total == 44


def test_initial_black_has_44_legal_moves():
    board = Board.from_fen(Board.initial().to_fen().replace(" w ", " b ", 1))
    total = sum(len(legal_moves(board, (x, y))) for x, y, p in board.pieces(Color.BLACK))
    assert total == 44


def test_legal_moves_ignores_wrong_turn():
    board = Board.initial()
    assert legal_moves(board, (1, 0)) == []  # 黑马，但轮红走


# ---------- 将帅照面（飞将） ----------


def test_kings_face_detected():
    board = board_of("4k4", "9", "9", "9", "9", "9", "9", "9", "9", "4K4")
    assert kings_face(board) is True
    assert in_check(board, Color.RED) is True


def test_kings_face_blocked_by_piece():
    board = board_of("4k4", "9", "9", "9", "9", "4R4", "9", "9", "9", "4K4")
    assert kings_face(board) is False


def test_moving_blocker_that_exposes_kings_is_illegal():
    # 红车 (4,5) 挡在两将之间；横走会让将帅照面 → 非法
    board = board_of("4k4", "9", "9", "9", "9", "4R4", "9", "9", "9", "4K4")
    targets = legal_moves(board, (4, 5))
    assert (5, 5) not in targets
    assert (3, 5) not in targets
    assert (4, 4) in targets  # 沿纵线走仍然挡着，合法


# ---------- 被将军 ----------


@pytest.mark.parametrize(
    "rows,expected",
    [
        (("3k5", "9", "4r4", "9", "9", "9", "9", "9", "9", "4K4"), True),  # 黑车直将
        (("3k5", "9", "9", "9", "9", "9", "9", "9", "9", "4K4"), False),  # 无威胁
        (("3k5", "9", "4c4", "9", "9", "4P4", "9", "9", "9", "4K4"), True),  # 炮架在 (4,5)
    ],
)
def test_in_check_by_rook_and_cannon(rows, expected):
    board = board_of(*rows)
    assert in_check(board, Color.RED) is expected


def test_in_check_by_horse():
    # 黑马 (3,7) 攻击红帅 (4,9)，马腿 (3,8) 是空的
    board = board_of("3k5", "9", "9", "9", "9", "9", "9", "3h5", "9", "4K4")
    assert in_check(board, Color.RED) is True


def test_horse_check_blocked_by_leg():
    board = board_of("3k5", "9", "9", "9", "9", "9", "9", "3h5", "3P5", "4K4")
    assert in_check(board, Color.RED) is False


def test_is_attacked_by_pawn():
    board = board_of("3k5", "9", "9", "9", "9", "9", "4p4", "9", "9", "4K4")
    assert is_attacked(board, (4, 7), Color.BLACK) is True  # 黑卒向前一格的位置
    assert is_attacked(board, (3, 6), Color.BLACK) is True  # 过河后可横吃
    assert is_attacked(board, (4, 5), Color.BLACK) is False


# ---------- 送将过滤 ----------


def test_pinned_rook_cannot_leave_file():
    # 红车 (4,5) 被黑车 (4,0) 牵制，只能沿纵线走
    board = board_of("3kr4", "9", "9", "9", "9", "4R4", "9", "9", "9", "4K4")
    targets = legal_moves(board, (4, 5))
    assert (5, 5) not in targets
    assert (0, 5) not in targets
    assert (4, 4) in targets


def test_king_cannot_move_into_attack():
    # 黑车 (5,0) 控制第 5 纵线；红帅 (4,9) 不能走到 (5,9)。
    # 中间放个红兵挡将帅照面，否则 (3,9) 会因为"飞将"被判非法，测不到本意。
    board = board_of("4kr3", "9", "9", "9", "9", "4P4", "9", "9", "9", "4K4")
    targets = legal_moves(board, (4, 9))
    assert (5, 9) not in targets
    assert (3, 9) in targets
    assert (4, 8) in targets


def test_pinned_advisor_cannot_move():
    # 红仕 (4,8) 正挡在黑车 (4,0) 与红帅 (4,9) 之间，走任何一个斜格都会送将
    board = board_of("3kr4", "9", "9", "9", "9", "9", "9", "9", "4A4", "4K4")
    assert legal_moves(board, (4, 8)) == []


def test_is_legal_rejects_pseudo_but_suicidal_move():
    board = board_of("3kr4", "9", "9", "9", "9", "4R4", "9", "9", "9", "4K4")
    assert is_legal(board, Move((4, 5), (5, 5))) is False
    assert is_legal(board, Move((4, 5), (4, 4))) is True


# ---------- 终局基础 ----------


def test_checkmate_has_no_legal_move():
    # 双车底线杀：黑将 (4,0) 被 (0,0) 的车将军，(4,2) 的车封住 (4,1)
    board = board_of("R3k4", "9", "4R4", "9", "9", "9", "9", "9", "9", "5K3", side="b")
    assert has_legal_move(board) is False
    assert in_check(board, Color.BLACK) is True


def test_stalemate_has_no_legal_move_but_not_in_check():
    # 黑将 (3,0)：(4,0) 被 (4,2) 的车控制，(3,1) 被 (2,1) 的车控制，但将本身没被攻击
    board = board_of("3k5", "2R6", "4R4", "9", "9", "9", "9", "9", "9", "4K4", side="b")
    assert has_legal_move(board) is False
    assert in_check(board, Color.BLACK) is False


def test_has_legal_move_true_at_start():
    assert has_legal_move(Board.initial()) is True
