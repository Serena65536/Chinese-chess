"""补充测试：边界条件、牵制场景、make/unmake、状态文案。"""

from __future__ import annotations

import pytest

from xiangqi_core import (
    Board,
    Color,
    Game,
    Kind,
    Move,
    Piece,
    Status,
    legal_moves_for_color,
    square_from_name,
    threatened_pieces,
)


def board_of(*rows: str, side: str = "w") -> Board:
    assert len(rows) == 10, "要传 10 行"
    return Board.from_fen("/".join(rows) + f" {side} - - 0 1")


# ---------- make / unmake ----------


def test_make_and_unmake_restore_counters():
    board = Board.initial()
    before = (board.turn, board.halfmove, board.fullmove, board.to_fen())
    move = Move((1, 7), (4, 7))
    snapshot = board.make(move)
    assert board.turn is Color.BLACK
    assert board.halfmove == before[1] + 1
    board.unmake(move, snapshot)
    assert (board.turn, board.halfmove, board.fullmove, board.to_fen()) == before


def test_capture_resets_halfmove_counter():
    board = board_of("4k4", "9", "9", "9", "9", "9", "9", "9", "4R4", "4K4")
    board.halfmove = 30
    board.make(Move((4, 8), (4, 0)))  # 吃将只是为了测试计数器
    assert board.halfmove == 0


def test_copy_is_independent():
    board = Board.initial()
    clone = board.copy()
    clone.set_piece(0, 0, None)
    assert board.piece_at(0, 0) is not None
    assert clone.piece_at(0, 0) is None


# ---------- FEN 与坐标 ----------


def test_fen_accepts_b_for_elephant():
    board = Board.from_fen("4k4/9/9/9/9/9/9/9/9/2B1K4 w - - 0 1")
    piece = board.piece_at(2, 9)
    assert piece is not None
    assert piece.kind is Kind.ELEPHANT


@pytest.mark.parametrize("name", ["z9", "a99", "", "e"])
def test_square_from_name_rejects_garbage(name):
    with pytest.raises(ValueError):
        square_from_name(name)


# ---------- 合法着法 ----------


def test_legal_moves_for_color_counts_44_at_start():
    assert len(list(legal_moves_for_color(Board.initial(), Color.RED))) == 44


def test_is_illegal_to_ignore_check():
    # 红帅被黑车将军，红车跑去别处（不挡不将）是非法着法
    game = Game(board_of("4k4", "9", "9", "9", "9", "4r4", "9", "9", "9", "R3K4"))
    with pytest.raises(ValueError):
        game.play(Move((0, 9), (0, 8)))


def test_threatened_pieces_finds_attacked_horse():
    # 红车 (0,5) 顺着第 0 纵线威胁黑马 (0,2)
    board = board_of("4k4", "9", "h8", "9", "9", "R8", "9", "9", "9", "4K4")
    threatened = threatened_pieces(board, Color.BLACK)
    assert (0, 2) in threatened


# ---------- 60 回合边界 ----------


def test_sixty_move_boundary_not_yet():
    game = Game(board_of("4k4", "9", "9", "9", "9", "R8", "9", "9", "9", "5K3"))
    game.board.halfmove = 118
    game.play(Move((0, 5), (0, 4)))  # 119
    assert game.outcome.status is Status.ONGOING
    game.play(Move((4, 0), (3, 0)))  # 120 → 恰好触线
    assert game.outcome.status is Status.DRAW_60


# ---------- 重复局面边界 ----------


def test_repetition_not_triggered_before_third_time():
    game = Game()
    cycle = [
        Move((1, 9), (2, 7)),
        Move((1, 0), (2, 2)),
        Move((2, 7), (1, 9)),
        Move((2, 2), (1, 0)),
    ]
    for move in cycle:
        game.play(move)
    assert game.outcome.status is Status.ONGOING  # 只重复了两次
    for move in cycle:
        game.play(move)
    assert game.outcome.status is Status.DRAW_REPETITION


def test_undo_after_repetition_draw_reopens_game():
    game = Game()
    cycle = [
        Move((1, 9), (2, 7)),
        Move((1, 0), (2, 2)),
        Move((2, 7), (1, 9)),
        Move((2, 2), (1, 0)),
    ]
    for _ in range(2):
        for move in cycle:
            game.play(move)
    assert game.is_over is True
    game.undo()
    assert game.is_over is False


# ---------- 文案 ----------


def test_outcome_text_for_checkmate():
    game = Game(board_of("4k4", "R2R5", "9", "9", "9", "9", "9", "9", "9", "5K3"))
    outcome = game.play(Move((0, 1), (0, 0)))
    assert outcome.text.startswith("红方胜")


def test_outcome_text_for_draw():
    game = Game()
    outcome = game.agree_draw()
    assert outcome.text.startswith("和棋")


def test_outcome_text_for_check():
    game = Game(board_of("3k5", "9", "9", "9", "9", "4R4", "9", "9", "9", "5K3"))
    outcome = game.play(Move((4, 5), (3, 5)))
    assert outcome.text == "将军！"
