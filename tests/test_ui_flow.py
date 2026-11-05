"""界面层测试：走子 → 侧栏/记谱/锁定是否跟着变。"""

from __future__ import annotations

import os
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("YQLXQ_CONFIG_DIR", os.path.join(tempfile.gettempdir(), "yqlxq-test-config"))
os.environ.setdefault("YQLXQ_SFX_DIR", os.path.join(tempfile.gettempdir(), "yqlxq-sfx-test"))

from PySide6.QtWidgets import QApplication

from client.app import MainWindow
from xiangqi_core import Board, Color, Game, Move


def _window() -> MainWindow:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.show_result_dialogs = False
    window.view.animate_moves = False
    window.resize(900, 820)
    window.show()
    app.processEvents()
    return window


def test_playing_move_updates_panel_and_record():
    window = _window()
    try:
        assert window.play_move(Move((1, 7), (4, 7))) is True
        assert window.move_list.count() == 1
        assert window.game.turn is Color.BLACK
        assert "黑方" in window.turn_label.text()
        assert window.move_list.item(0).text() == "1. 炮 b2-e2"
    finally:
        window.close()


def test_illegal_move_is_rejected_and_record_stays_empty():
    window = _window()
    try:
        assert window.play_move(Move((1, 7), (1, 9))) is False
        assert window.move_list.count() == 0
        assert window.game.turn is Color.RED
    finally:
        window.close()


def test_check_highlights_king():
    window = _window()
    try:
        window.load_game(Game(Board.from_fen("3k5/9/9/9/9/4R4/9/9/9/5K3 w - - 0 1")))
        assert window.play_move(Move((4, 5), (3, 5))) is True
        assert window.view.check_square == (3, 0)
        assert window.info_label.text() == "将军！"
    finally:
        window.close()


def test_checkmate_locks_board_and_buttons():
    window = _window()
    try:
        window.load_game(Game(Board.from_fen("4k4/R2R5/9/9/9/9/9/9/9/5K3 w - - 0 1")))
        assert window.play_move(Move((0, 1), (0, 0))) is True
        assert window.game.is_over is True
        assert window.view.locked is True
        assert window.resign_button.isEnabled() is False
        assert window.draw_button.isEnabled() is False
        assert "将死" in window.info_label.text()
        # 终局后再点棋盘不应再有反应
        assert window.play_move(Move((4, 0), (3, 0))) is False
    finally:
        window.close()
