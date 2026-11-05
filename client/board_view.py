"""棋盘视图：固定逻辑坐标渲染 + 走子动画 + 将军高亮。

坐标策略同 M0：场景固定 ``SCENE_W × SCENE_H``，窗口变化只调 ``fitInView(KeepAspectRatio)``。

M1 新增：
- 走子补间动画（棋子从起点滑到终点，期间目标点先不画，避免"闪现"）
- 被将军时给将/帅套一圈红环
- 输入锁：动画中或对局结束后不再接受点击
"""

from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import QEasingCurve, QPointF, QRectF, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QGraphicsItem, QGraphicsScene, QGraphicsView

from xiangqi_core import Board, Color, Kind, Move, Piece, generate_pseudo_moves

from . import artwork

CELL = 100.0
MARGIN = 94.0
GRID_W = 8 * CELL
GRID_H = 9 * CELL
SCENE_W = GRID_W + 2 * MARGIN
SCENE_H = GRID_H + 2 * MARGIN
PIECE_RADIUS = CELL * 0.42
MOVE_ANIM_MS = 170


class BoardItem(QGraphicsItem):
    def __init__(self, view: "BoardView") -> None:
        super().__init__()
        self._view = view

    def boundingRect(self) -> QRectF:  # noqa: N802
        return QRectF(0, 0, SCENE_W, SCENE_H)

    def paint(self, painter: QPainter, option, widget=None) -> None:  # noqa: ARG002
        self._view.paint_board(painter)


class BoardView(QGraphicsView):
    squareClicked = Signal(int, int)
    moveRequested = Signal(object)

    def __init__(self, board: Optional[Board] = None, parent=None) -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self._scene.setSceneRect(0, 0, SCENE_W, SCENE_H)
        self.setScene(self._scene)
        self._item = BoardItem(self)
        self._scene.addItem(self._item)

        self.setFrameShape(QGraphicsView.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setRenderHints(
            QPainter.Antialiasing | QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform
        )
        self.setBackgroundBrush(QColor("#2B2119"))
        self.setMinimumSize(360, 420)

        self.board = board or Board.initial()
        self.selected: Optional[tuple[int, int]] = None
        self.targets: list[tuple[int, int]] = []
        self.last_move: Optional[Move] = None
        self.flipped = False
        self.background_image: Optional[QImage] = None
        self.background_darken = 55
        self.check_square: Optional[tuple[int, int]] = None
        self.locked = False
        self.animate_moves = True

        #: 有 game 时用它算合法着法（会过滤送将）；没有就退回伪合法，方便单独调试
        self.legal_provider: Optional[Callable[[tuple[int, int]], list[tuple[int, int]]]] = None

        self._anim_move: Optional[Move] = None
        self._anim_piece: Optional[Piece] = None
        self._anim_t = 0.0
        self._animation = QVariantAnimation(self)
        self._animation.setStartValue(0.0)
        self._animation.setEndValue(1.0)
        self._animation.setDuration(MOVE_ANIM_MS)
        self._animation.setEasingCurve(QEasingCurve.OutCubic)
        self._animation.valueChanged.connect(self._on_anim_tick)
        self._animation.finished.connect(self._on_anim_done)

    # ---------- 坐标换算 ----------

    def display_pos(self, x: int, y: int) -> tuple[int, int]:
        return (8 - x, 9 - y) if self.flipped else (x, y)

    def point_of(self, x: int, y: int) -> QPointF:
        col, row = self.display_pos(x, y)
        return QPointF(MARGIN + col * CELL, MARGIN + row * CELL)

    def square_at(self, point: QPointF, tolerance: float = CELL * 0.55) -> Optional[tuple[int, int]]:
        col = round((point.x() - MARGIN) / CELL)
        row = round((point.y() - MARGIN) / CELL)
        if not (0 <= col <= 8 and 0 <= row <= 9):
            return None
        cx = MARGIN + col * CELL
        cy = MARGIN + row * CELL
        if abs(point.x() - cx) > tolerance or abs(point.y() - cy) > tolerance:
            return None
        return (8 - col, 9 - row) if self.flipped else (col, row)

    # ---------- 状态 ----------

    def _refresh(self) -> None:
        """重绘请求必须打在 viewport 上（QGraphicsView 自己 update() 只重画边框）。"""
        self._item.update()
        self.viewport().update()

    def set_board(self, board: Board) -> None:
        self.board = board
        self.selected = None
        self.targets = []
        self.last_move = None
        self.check_square = None
        self.locked = False
        self._cancel_animation()
        self._refresh()

    def set_selection(
        self,
        square: Optional[tuple[int, int]],
        targets: Optional[list[tuple[int, int]]] = None,
    ) -> None:
        self.selected = square
        self.targets = targets or []
        self._refresh()

    def set_background(self, image: Optional[QImage], darken: Optional[int] = None) -> None:
        self.background_image = image
        if darken is not None:
            self.background_darken = max(0, min(100, darken))
        self.viewport().update()

    def set_flipped(self, flipped: bool) -> None:
        self.flipped = flipped
        self._refresh()

    def set_check(self, square: Optional[tuple[int, int]]) -> None:
        self.check_square = square
        self._refresh()

    def set_locked(self, locked: bool) -> None:
        self.locked = locked
        if locked:
            self.set_selection(None, [])

    def legal_targets(self, square: tuple[int, int]) -> list[tuple[int, int]]:
        if self.legal_provider is not None:
            return self.legal_provider(square)
        return generate_pseudo_moves(self.board, square)

    # ---------- 走子动画 ----------

    def animate_move(self, move: Move, piece: Piece, duration_ms: int = MOVE_ANIM_MS) -> None:
        self.last_move = move
        self.set_selection(None, [])
        if duration_ms <= 0 or not self.animate_moves:
            self._cancel_animation()
            self._refresh()
            return
        self._cancel_animation()
        self._anim_move = move
        self._anim_piece = piece
        self._anim_t = 0.0
        self._animation.setDuration(duration_ms)
        self._animation.start()

    @property
    def is_animating(self) -> bool:
        return self._anim_move is not None

    def _cancel_animation(self) -> None:
        if self._animation.state() != QVariantAnimation.Stopped:
            self._animation.stop()
        self._anim_move = None
        self._anim_piece = None
        self._anim_t = 0.0

    def _on_anim_tick(self, value) -> None:  # noqa: ANN001
        self._anim_t = float(value)
        self._refresh()

    def _on_anim_done(self) -> None:
        self._anim_move = None
        self._anim_piece = None
        self._anim_t = 0.0
        self._refresh()

    def paint_board(self, painter: QPainter) -> None:
        frame = QRectF(
            MARGIN - CELL * 0.30,
            MARGIN - CELL * 0.30,
            GRID_W + CELL * 0.60,
            GRID_H + CELL * 0.60,
        )
        grid = QRectF(MARGIN, MARGIN, GRID_W, GRID_H)
        artwork.draw_board(painter, frame, grid, CELL)

        if self.last_move is not None:
            artwork.draw_last_move(
                painter, self.point_of(*self.last_move.src), self.point_of(*self.last_move.dst), CELL
            )

        if self.check_square is not None:
            artwork.draw_check_ring(painter, self.point_of(*self.check_square), CELL)

        if self.targets:
            points = [self.point_of(x, y) for x, y in self.targets]
            occupied = [self.board.piece_at(x, y) is not None for x, y in self.targets]
            artwork.draw_target_markers(painter, points, CELL, occupied)

        moving_dst = self._anim_move.dst if self._anim_move else None
        for x, y, piece in self.board.pieces():
            if moving_dst is not None and (x, y) == moving_dst:
                continue  # 动画期间先不画落点，避免"棋子先闪现到位再滑回来"
            artwork.draw_piece(
                painter, self.point_of(x, y), PIECE_RADIUS, piece, selected=self.selected == (x, y)
            )

        if self._anim_move is not None and self._anim_piece is not None:
            start = self.point_of(*self._anim_move.src)
            end = self.point_of(*self._anim_move.dst)
            t = self._anim_t
            current = QPointF(
                start.x() + (end.x() - start.x()) * t,
                start.y() + (end.y() - start.y()) * t,
            )
            artwork.draw_piece(painter, current, PIECE_RADIUS, self._anim_piece)

    # ---------- 背景 ----------

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:  # noqa: N802
        painter.save()
        painter.fillRect(rect, QColor("#2B2119"))
        if self.background_image is not None and not self.background_image.isNull():
            target = QRectF(0, 0, SCENE_W, SCENE_H)
            scaled = QPixmap.fromImage(self.background_image).scaled(
                int(target.width()), int(target.height()), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
            )
            src = QRectF(
                (scaled.width() - target.width()) / 2,
                (scaled.height() - target.height()) / 2,
                target.width(),
                target.height(),
            )
            painter.drawPixmap(target, scaled, src)
            alpha = int(255 * self.background_darken / 100)
            if alpha:
                painter.fillRect(target, QColor(0, 0, 0, alpha))
        painter.restore()

    # ---------- 交互 ----------

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.fit()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self.fit()

    def fit(self) -> None:
        self.fitInView(self._scene.sceneRect(), Qt.KeepAspectRatio)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.LeftButton or self.locked or self.is_animating:
            return
        point = self.mapToScene(event.position().toPoint())
        square = self.square_at(point)
        if square is None:
            self.set_selection(None, [])
            return

        piece = self.board.piece_at(*square)
        if piece is not None and piece.color is self.board.turn:
            self.set_selection(square, self.legal_targets(square))
        elif self.selected is not None and square in self.targets:
            self.moveRequested.emit(Move(self.selected, square))
        else:
            self.set_selection(None, [])
        self.squareClicked.emit(*square)

    # ---------- 兼容旧调用 ----------

    def apply_move(self, move: Move) -> Optional[Piece]:
        piece = self.board.piece_at(*move.src)
        captured = self.board.apply_move(move)
        self.last_move = move
        self.set_selection(None, [])
        if piece is not None:
            self.animate_move(move, piece)
        return captured
