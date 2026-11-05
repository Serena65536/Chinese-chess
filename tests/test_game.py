"""对局状态机测试：将死、困毙、三次重复、60 回合、长将判负、悔棋、人工结局。"""

from __future__ import annotations

import pytest

from xiangqi_core import Board, Color, Game, Move, Status


def board_of(*rows: str, side: str = "w") -> Board:
    assert len(rows) == 10, "要传 10 行"
    return Board.from_fen("/".join(rows) + f" {side} - - 0 1")


def new_game(*rows: str, side: str = "w") -> Game:
    return Game(board_of(*rows, side=side))


# ---------- 基本流程 ----------


def test_initial_game_is_ongoing():
    game = Game()
    assert game.outcome.status is Status.ONGOING
    assert game.is_over is False
    assert game.turn is Color.RED
    assert game.record_lines() == []


def test_play_flips_turn_and_records_move():
    game = Game()
    game.play(Move((1, 7), (4, 7)))  # 炮二平五的坐标版本
    assert game.turn is Color.BLACK
    assert len(game.entries) == 1
    assert game.record_lines() == ["1. 炮 b2-e2"]


def test_play_rejects_illegal_move():
    game = Game()
    with pytest.raises(ValueError):
        game.play(Move((1, 7), (1, 9)))  # 炮不能落在自己的马上面


def test_play_rejects_move_when_game_over():
    game = new_game("4k4", "R2R5", "9", "9", "9", "9", "9", "9", "9", "5K3")
    game.play(Move((0, 1), (0, 0)))  # 底线杀
    assert game.is_over is True
    with pytest.raises(ValueError):
        game.play(Move((4, 0), (4, 1)))


# ---------- 终局 ----------


def test_checkmate_by_rook():
    # 红车 (0,1) 平到底线将军，(3,1) 的车封住 (3,0) 与 (4,1)
    game = new_game("4k4", "R2R5", "9", "9", "9", "9", "9", "9", "9", "5K3")
    outcome = game.play(Move((0, 1), (0, 0)))
    assert outcome.status is Status.CHECKMATE
    assert outcome.winner is Color.RED
    assert game.is_over is True
    assert "将死" in outcome.text


def test_stalemate_is_loss_not_draw():
    # 红车 (4,3) 退到 (4,2)：黑将 (3,0) 的 (4,0)、(3,1) 都被控制，但将本身没被将军
    game = new_game("3k5", "2R6", "9", "4R4", "9", "9", "9", "9", "9", "4K4")
    outcome = game.play(Move((4, 3), (4, 2)))
    assert outcome.status is Status.STALEMATE
    assert outcome.winner is Color.RED
    assert "困毙" in outcome.reason


def test_check_status_after_checking_move():
    # 红车 (4,5) 平到 (3,5) 将军黑将 (3,0)
    game = new_game("3k5", "9", "9", "9", "9", "4R4", "9", "9", "9", "5K3")
    outcome = game.play(Move((4, 5), (3, 5)))
    assert outcome.status is Status.CHECK
    assert outcome.text == "将军！"


def test_repetition_draw():
    game = Game()
    cycle = [
        Move((1, 9), (2, 7)),  # 红马
        Move((1, 0), (2, 2)),  # 黑马
        Move((2, 7), (1, 9)),
        Move((2, 2), (1, 0)),
    ]
    for _ in range(2):
        for move in cycle:
            game.play(move)
    assert game.outcome.status is Status.DRAW_REPETITION
    assert game.outcome.is_draw is True
    assert game.outcome.winner is None


def test_perpetual_check_loses():
    # 红车在 (4,2)/(3,2) 之间来回，每步都将军 → 长将判负
    game = new_game("3k5", "9", "4R4", "9", "9", "9", "9", "9", "9", "5K3")
    cycle = [
        Move((4, 2), (3, 2)),
        Move((3, 0), (4, 0)),
        Move((3, 2), (4, 2)),
        Move((4, 0), (3, 0)),
    ]
    for _ in range(2):
        for move in cycle:
            game.play(move)
    assert game.outcome.status is Status.LOSS_PERPETUAL
    assert game.outcome.winner is Color.BLACK
    assert "长将" in game.outcome.reason


def test_sixty_move_rule():
    game = new_game("3k5", "9", "9", "9", "9", "R8", "9", "9", "9", "5K3")
    game.board.halfmove = 119
    game.play(Move((0, 5), (0, 4)))  # 无吃子的闲着
    assert game.outcome.status is Status.DRAW_60
    assert game.outcome.is_draw is True


# ---------- 人工结局 ----------


def test_resign():
    game = Game()
    outcome = game.resign(Color.RED)
    assert outcome.status is Status.RESIGN
    assert outcome.winner is Color.BLACK
    assert "红方认输" in outcome.reason
    assert game.is_over is True


def test_agree_draw():
    game = Game()
    outcome = game.agree_draw()
    assert outcome.status is Status.DRAW_AGREED
    assert outcome.is_draw is True
    assert outcome.winner is None


def test_timeout():
    game = Game()
    outcome = game.timeout(Color.BLACK)
    assert outcome.status is Status.TIMEOUT
    assert outcome.winner is Color.RED


# ---------- 悔棋与重置 ----------


def test_undo_restores_position_and_status():
    game = Game()
    before = game.board.position_key()
    game.play(Move((1, 7), (4, 7)))
    assert game.undo() is True
    assert game.board.position_key() == before
    assert game.turn is Color.RED
    assert game.outcome.status is Status.ONGOING
    assert game.record_lines() == []


def test_undo_after_checkmate_reopens_game():
    game = new_game("4k4", "R2R5", "9", "9", "9", "9", "9", "9", "9", "5K3")
    game.play(Move((0, 1), (0, 0)))
    assert game.is_over is True
    game.undo()
    assert game.is_over is False
    assert game.turn is Color.RED


def test_undo_when_empty_returns_false():
    assert Game().undo() is False


def test_reset_clears_everything():
    game = Game()
    game.play(Move((1, 7), (4, 7)))
    game.resign(Color.BLACK)
    game.reset()
    assert game.entries == []
    assert game.outcome.status is Status.ONGOING
    assert game.turn is Color.RED


# ---------- 其它 ----------


def test_legal_targets_empty_after_game_over():
    game = new_game("4k4", "R2R5", "9", "9", "9", "9", "9", "9", "9", "5K3")
    game.play(Move((0, 1), (0, 0)))
    assert game.legal_targets((0, 0)) == []


def test_record_lines_numbering():
    game = Game()
    game.play(Move((1, 7), (4, 7)))
    game.play(Move((1, 0), (2, 2)))
    lines = game.record_lines()
    assert lines[0].startswith("1.")
    assert lines[1].startswith("2.")
    assert len(lines) == 2
