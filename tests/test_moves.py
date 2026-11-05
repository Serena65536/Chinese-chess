"""伪合法着法测试：每个棋子的关键规则各守一条。

FEN 行序自上而下（y=0 是黑方底线，y=9 是红方底线）。
"""

from __future__ import annotations

from xiangqi_core import Board, Color, Move, generate_pseudo_moves, is_pseudo_legal


def board_of(*rows: str, side: str = "w") -> Board:
    assert len(rows) == 10, "要传 10 行"
    return Board.from_fen("/".join(rows) + f" {side} - - 0 1")


def targets(board: Board, square: tuple[int, int]) -> set[tuple[int, int]]:
    return set(generate_pseudo_moves(board, square))


def test_initial_position_move_count_is_44():
    """中国象棋起始局面双方各有 44 个着法，这是标准数字，兜住大方向。"""
    board = Board.initial()
    for color in (Color.RED, Color.BLACK):
        if color is Color.BLACK:
            board = Board.from_fen(board.to_fen().replace(" w ", " b ", 1))
        total = sum(
            len(generate_pseudo_moves(board, (x, y))) for x, y, _ in board.pieces(color)
        )
        assert total == 44, f"{color.label} 着法数应为 44，实际 {total}"


def test_rook_slides_until_blocked():
    board = board_of("4k4", "9", "9", "9", "9", "9", "R8", "9", "9", "4K4")
    moves = targets(board, (0, 6))
    assert (8, 6) in moves  # 向右到底
    assert (0, 0) in moves  # 向上到底
    assert (0, 9) in moves  # 向下到底
    assert (0, 6) not in moves  # 原位置不在落点里


def test_rook_cannot_pass_through_piece():
    board = board_of("4k4", "9", "9", "9", "9", "9", "R1R6", "9", "9", "4K4")
    moves = targets(board, (0, 6))
    assert (1, 6) in moves  # 紧邻的空点可以走
    assert (2, 6) not in moves  # 己方车占位，不能落
    assert (3, 6) not in moves  # 更不能穿过


def test_cannon_needs_screen_to_capture():
    # 红炮 (1,7)；黑卒 (1,3) 当炮架；黑车 (1,1) 被隔打
    board = board_of("4k4", "1r7", "9", "1p7", "9", "9", "9", "1C7", "9", "4K4")
    moves = targets(board, (1, 7))
    assert (1, 1) in moves  # 隔一个炮架可以吃
    assert (1, 3) not in moves  # 炮架本身不能落
    assert (1, 2) not in moves  # 炮架之后、目标之前的空点不能落


def test_cannon_cannot_capture_without_screen():
    board = board_of("4k4", "1r7", "9", "9", "9", "9", "9", "1C7", "9", "4K4")
    moves = targets(board, (1, 7))
    assert (1, 1) not in moves  # 中间无炮架，吃不到
    assert (1, 2) in moves  # 但可以走到它前面


def test_horse_leg_blocked_vertical():
    # 马 (2,7)，马腿 (2,6) 被黑卒占住 → (1,5)、(3,5) 都走不了
    board = board_of("4k4", "9", "9", "9", "9", "9", "2p6", "2H6", "9", "4K4")
    moves = targets(board, (2, 7))
    assert (1, 5) not in moves
    assert (3, 5) not in moves
    assert (0, 6) in moves  # 另一条腿没挡，正常可走


def test_elephant_cannot_cross_river():
    # 红相 (2,5) 贴着河界，往前两个方向都过河，必须被拦
    board = board_of("4k4", "9", "9", "9", "9", "2B6", "9", "9", "9", "4K4")
    moves = targets(board, (2, 5))
    assert moves == {(0, 7), (4, 7)}


def test_elephant_eye_blocked():
    # 象眼 (1,6) 放一个黑卒，红相就不能走 (0,7)
    board = board_of("4k4", "9", "9", "9", "9", "2B6", "1p7", "9", "9", "4K4")
    moves = targets(board, (2, 5))
    assert (0, 7) not in moves
    assert (4, 7) in moves  # 另一条象眼没堵


def test_advisor_stays_in_palace():
    board = board_of("4k4", "9", "9", "9", "9", "9", "9", "9", "9", "3AK4")
    assert targets(board, (3, 9)) == {(4, 8)}


def test_king_stays_in_palace():
    board = board_of("4k4", "9", "9", "9", "9", "9", "9", "9", "9", "4K4")
    assert targets(board, (4, 9)) == {(4, 8), (3, 9), (5, 9)}


def test_pawn_before_river_moves_only_forward():
    board = Board.initial()
    assert targets(board, (0, 6)) == {(0, 5)}


def test_pawn_after_river_can_move_sideways():
    # 红兵过了河，(0,4) → 可前进到 (0,3)，也可横走到 (1,4)
    board = board_of("4k4", "9", "9", "9", "P8", "9", "9", "9", "9", "4K4")
    moves = targets(board, (0, 4))
    assert moves == {(0, 3), (1, 4)}


def test_black_pawn_moves_downward():
    from xiangqi_core import Kind, Piece

    board = board_of("4k4", "9", "9", "9", "9", "9", "9", "9", "9", "4K4", side="b")
    board.set_piece(0, 2, Piece(Color.BLACK, Kind.PAWN))  # 黑卒在己方半场 (0,2)
    assert targets(board, (0, 2)) == {(0, 3)}


def test_is_pseudo_legal_respects_turn():
    board = Board.initial()
    assert is_pseudo_legal(board, Move((1, 7), (4, 7))) is True
    assert is_pseudo_legal(board, Move((1, 0), (2, 2))) is False  # 轮红走，黑马不能动
