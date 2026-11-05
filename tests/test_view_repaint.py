"""回归测试：走子之后必须立刻重绘（不能等窗口缩放才刷新）。

对应 bug：点击走子后棋盘不更新，拖动窗口边框才刷新。
根因是重绘请求发给了 QGraphicsView 自身，而真正绘制场景的是它的 viewport()。
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from client.board_view import BoardView


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _click(view: BoardView, square: tuple[int, int]) -> None:
    point = view.mapFromScene(view.point_of(*square))
    for event_type in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease):
        event = QMouseEvent(
            event_type,
            QPointF(point),
            QPointF(point),
            Qt.LeftButton,
            Qt.LeftButton if event_type is QEvent.MouseButtonPress else Qt.NoButton,
            Qt.NoModifier,
        )
        if event_type is QEvent.MouseButtonPress:
            view.mousePressEvent(event)
        else:
            view.mouseReleaseEvent(event)


def _count_paints(view: BoardView) -> list[int]:
    """把 paint_board 包一层计数，paint 一次 +1。"""
    counter = [0]
    original = BoardView.paint_board

    def counting(self, painter):  # noqa: ANN001
        counter[0] += 1
        return original(self, painter)

    BoardView.paint_board = counting
    return counter


def test_move_repaints_immediately():
    app = _app()
    view = BoardView()
    view.moveRequested.connect(view.apply_move)  # 模拟主窗口的控制器
    view.resize(700, 800)
    view.show()
    app.processEvents()

    paints = _count_paints(view)
    try:
        paints[0] = 0

        # 点中红炮 (1,7)，应立刻高亮并重绘
        _click(view, (1, 7))
        app.processEvents()
        assert view.selected == (1, 7), "第一次点击没有选中棋子"
        assert paints[0] > 0, "选中棋子后没有重绘（画面会等到缩放窗口才更新）"

        paints[0] = 0
        # 走到 (4,7)，棋盘数据要变，画面也要立刻变
        _click(view, (4, 7))
        app.processEvents()
        assert view.board.piece_at(4, 7) is not None, "走子后棋盘数据没变"
        assert view.board.piece_at(1, 7) is None, "起点棋子没清空"
        assert paints[0] > 0, "走子后没有重绘（这就是用户看到的问题）"
    finally:
        BoardView.paint_board = original_paint_board


original_paint_board = BoardView.paint_board
