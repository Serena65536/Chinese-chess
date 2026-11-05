"""程序绘制的美术资源：木纹棋盘 + 立体棋子。

设计要点（对应决策 D9）：
- 全部用 QPainter 画，不引用任何外部图片，天然没有版权问题
- 木纹用"底色渐变 + 固定种子的细纹曲线"生成，结果可复现
- 棋子用径向渐变做弧面高光、底部投影做厚度、内描边做年轮感
- 字体优先楷体，缺了逐级回退，绝不打包字体文件
"""

from __future__ import annotations

import random

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
)

from xiangqi_core import Color, Piece

# ---------- 调色板 ----------

WOOD_LIGHT = QColor("#EDCB95")
WOOD_DARK = QColor("#D6A868")
WOOD_GRAIN = QColor(120, 78, 38, 26)
FRAME_OUTER = QColor("#3E2614")
FRAME_INNER = QColor("#5A3A20")
LINE = QColor("#6B4423")
LINE_SOFT = QColor(107, 68, 35, 150)
RIVER_TEXT = QColor("#7B4A22")
MARKER = QColor(107, 68, 35, 170)

PIECE_FACE_HI = QColor("#FFF9EA")
PIECE_FACE_MID = QColor("#F0DCB6")
PIECE_FACE_LO = QColor("#D8BC8C")
PIECE_EDGE = QColor("#7A5230")
PIECE_RED_TEXT = QColor("#A8231B")
PIECE_BLACK_TEXT = QColor("#221F1C")
SELECTION = QColor("#E0A000")
TARGET_DOT = QColor(40, 120, 80, 190)
LAST_MOVE = QColor(210, 150, 20, 160)

_KAI_FAMILIES = ("KaiTi", "楷体", "STKaiti", "Kaiti SC", "SimKai", "FangSong", "Microsoft YaHei")
_font_cache: dict[int, QFont] = {}
_font_family: str | None = None
_wood_cache: dict[tuple[int, int], QPixmap] = {}
_fonts_loaded = False


def _load_system_font_files() -> None:  # 兼容旧调用，实际逻辑在 fonts.ensure_fonts
    """离屏渲染（截图取证、无头测试）时 Qt 找不到系统字体目录，这里手动挂载。

    正常跑 Windows 界面时 ``QFontDatabase.families()`` 本来就有内容，不会走这条路。
    """
    from .fonts import ensure_fonts

    ensure_fonts()


def piece_family() -> str:
    """挑一个可用的中文字体：楷体 > 仿宋 > 微软雅黑 > 系统默认。"""
    global _font_family
    if _font_family is None:
        from .fonts import family

        _font_family = family(_KAI_FAMILIES)
    return _font_family


def piece_font(pixel_size: int) -> QFont:
    font = _font_cache.get(pixel_size)
    if font is None:
        font = QFont(piece_family()) if piece_family() else QFont()
        font.setPixelSize(pixel_size)
        font.setBold(True)
        _font_cache[pixel_size] = font
    return font


# ---------- 木纹 ----------


def wood_pixmap(width: int, height: int, seed: int = 20240501) -> QPixmap:
    """生成一张木纹底（缓存，按尺寸复用）。"""
    key = (int(width), int(height))
    cached = _wood_cache.get(key)
    if cached is not None:
        return cached

    pixmap = QPixmap(key[0], key[1])
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)

    rect = QRectF(0, 0, key[0], key[1])
    base = QLinearGradient(rect.topLeft(), rect.bottomRight())
    base.setColorAt(0.0, WOOD_LIGHT)
    base.setColorAt(0.45, WOOD_LIGHT.lighter(103))
    base.setColorAt(1.0, WOOD_DARK)
    painter.fillRect(rect, base)

    rng = random.Random(seed)
    painter.setPen(Qt.NoPen)
    # 木纹：一组缓慢起伏的细长曲线，透明度极低，叠出"年轮"感
    for _ in range(int(key[1] / 3)):
        y0 = rng.uniform(0, key[1])
        path = QPainterPath()
        path.moveTo(0, y0)
        x = 0.0
        y = y0
        while x < key[0]:
            step = rng.uniform(key[0] / 12, key[0] / 5)
            x += step
            y += rng.uniform(-2.2, 2.2)
            path.quadTo(x - step / 2, y + rng.uniform(-6, 6), x, y)
        grain = QColor(WOOD_GRAIN)
        grain.setAlpha(rng.randint(10, 34))
        painter.setPen(QPen(grain, rng.uniform(0.8, 2.6)))
        painter.drawPath(path)

    painter.end()
    _wood_cache[key] = pixmap
    return pixmap


# ---------- 棋盘 ----------


def draw_board(
    painter: QPainter,
    frame: QRectF,
    grid: QRectF,
    cell: float,
    river_text: bool = True,
) -> None:
    """画外框 + 木纹 + 棋盘线。``grid`` 是九条纵线与十条横线构成的矩形。"""
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, True)

    # 外框
    painter.setPen(Qt.NoPen)
    painter.setBrush(FRAME_OUTER)
    painter.drawRoundedRect(frame.adjusted(-6, -6, 6, 6), 10, 10)
    painter.setBrush(FRAME_INNER)
    painter.drawRoundedRect(frame, 6, 6)

    # 木纹底
    painter.save()
    path = QPainterPath()
    path.addRoundedRect(frame.adjusted(4, 4, -4, -4), 4, 4)
    painter.setClipPath(path)
    painter.drawPixmap(frame.toRect().adjusted(4, 4, -4, -4), wood_pixmap(int(frame.width()), int(frame.height())))
    painter.restore()

    # 棋盘线
    pen = QPen(LINE, max(1.6, cell * 0.022))
    pen.setCapStyle(Qt.RoundCap)
    painter.setPen(pen)
    x0, y0 = grid.left(), grid.top()
    x1, y1 = grid.right(), grid.bottom()

    # 十条横线
    for row in range(10):
        y = y0 + row * cell
        painter.drawLine(QPointF(x0, y), QPointF(x1, y))
    # 九条纵线：最外两条贯通，中间七条在河界断开
    for col in range(9):
        x = x0 + col * cell
        if col in (0, 8):
            painter.drawLine(QPointF(x, y0), QPointF(x, y1))
        else:
            painter.drawLine(QPointF(x, y0), QPointF(x, y0 + 4 * cell))
            painter.drawLine(QPointF(x, y0 + 5 * cell), QPointF(x, y1))

    # 九宫斜线
    for base_y in (0, 7):
        painter.drawLine(
            QPointF(x0 + 3 * cell, y0 + base_y * cell),
            QPointF(x0 + 5 * cell, y0 + (base_y + 2) * cell),
        )
        painter.drawLine(
            QPointF(x0 + 5 * cell, y0 + base_y * cell),
            QPointF(x0 + 3 * cell, y0 + (base_y + 2) * cell),
        )

    # 兵/炮位的小十字标记
    painter.setPen(QPen(MARKER, max(1.2, cell * 0.016)))
    marks = [
        (0, 3), (2, 3), (4, 3), (6, 3), (8, 3),
        (0, 6), (2, 6), (4, 6), (6, 6), (8, 6),
        (1, 2), (7, 2), (1, 7), (7, 7),
    ]
    arm = cell * 0.09
    for col, row in marks:
        cx, cy = x0 + col * cell, y0 + row * cell
        painter.drawLine(QPointF(cx - arm, cy), QPointF(cx + arm, cy))
        painter.drawLine(QPointF(cx, cy - arm), QPointF(cx, cy + arm))

    if river_text:
        font = piece_font(int(cell * 0.42))
        painter.setFont(font)
        painter.setPen(QPen(RIVER_TEXT))
        mid_y = y0 + 4.5 * cell
        painter.drawText(
            QRectF(x0 + 1.2 * cell, mid_y - cell * 0.4, 2.6 * cell, cell * 0.8),
            Qt.AlignCenter,
            "楚 河",
        )
        painter.drawText(
            QRectF(x0 + 5.2 * cell, mid_y - cell * 0.4, 2.6 * cell, cell * 0.8),
            Qt.AlignCenter,
            "汉 界",
        )

    painter.restore()


# ---------- 棋子 ----------


def draw_piece(
    painter: QPainter,
    center: QPointF,
    radius: float,
    piece: Piece,
    *,
    selected: bool = False,
    faded: bool = False,
) -> None:
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, True)
    if faded:
        painter.setOpacity(0.45)

    cx, cy = center.x(), center.y()

    # 投影：三层同心椭圆模拟柔和阴影
    painter.setPen(Qt.NoPen)
    for i, alpha in enumerate((26, 18, 12)):
        painter.setBrush(QColor(40, 24, 8, alpha))
        off = radius * (0.10 + 0.03 * i)
        painter.drawEllipse(
            QRectF(cx - radius * 0.96, cy - radius * 0.94 + off, radius * 1.92, radius * 1.9)
        )

    # 底盘（厚度感）
    painter.setBrush(PIECE_FACE_LO)
    painter.setPen(QPen(PIECE_EDGE, max(1.4, radius * 0.05)))
    painter.drawEllipse(QPointF(cx, cy + radius * 0.045), radius, radius)

    # 面：径向渐变，光源在左上
    grad = QRadialGradient(
        QPointF(cx - radius * 0.34, cy - radius * 0.42),
        radius * 1.5,
    )
    grad.setColorAt(0.0, PIECE_FACE_HI)
    grad.setColorAt(0.55, PIECE_FACE_MID)
    grad.setColorAt(1.0, PIECE_FACE_LO)
    painter.setBrush(grad)
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(QPointF(cx, cy), radius * 0.97, radius * 0.97)

    # 内圈
    painter.setBrush(Qt.NoBrush)
    painter.setPen(QPen(PIECE_EDGE, max(1.0, radius * 0.035)))
    painter.drawEllipse(QPointF(cx, cy), radius * 0.80, radius * 0.80)

    # 字
    font = piece_font(int(radius * 1.16))
    painter.setFont(font)
    painter.setPen(QPen(PIECE_RED_TEXT if piece.color is Color.RED else PIECE_BLACK_TEXT))
    painter.drawText(
        QRectF(cx - radius, cy - radius * 0.94, radius * 2, radius * 1.9),
        Qt.AlignCenter,
        piece.glyph,
    )

    if selected:
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(SELECTION, max(2.0, radius * 0.10)))
        painter.drawEllipse(QPointF(cx, cy), radius * 1.04, radius * 1.04)

    painter.restore()


def draw_target_markers(
    painter: QPainter,
    points: list[QPointF],
    cell: float,
    occupied: list[bool],
) -> None:
    """合法落点提示：空点画实心小圆，可吃子画空心环。"""
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, True)
    for point, has_piece in zip(points, occupied):
        if has_piece:
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(QColor(TARGET_DOT), max(2.0, cell * 0.045)))
            r = cell * 0.40
            painter.drawEllipse(point, r, r)
        else:
            painter.setBrush(TARGET_DOT)
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(point, cell * 0.10, cell * 0.10)
    painter.restore()


def draw_last_move(
    painter: QPainter,
    src: QPointF,
    dst: QPointF,
    cell: float,
) -> None:
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setBrush(Qt.NoBrush)
    painter.setPen(QPen(LAST_MOVE, max(2.0, cell * 0.035)))
    painter.drawEllipse(src, cell * 0.42, cell * 0.42)
    painter.drawEllipse(dst, cell * 0.42, cell * 0.42)
    painter.restore()


def draw_check_ring(painter: QPainter, center: QPointF, cell: float) -> None:
    """被将军的将/帅外面套几圈红环（外圈淡、内圈实，做出"告警"的层次）。"""
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setBrush(Qt.NoBrush)
    for index, alpha in enumerate((36, 66, 120)):
        radius = cell * (0.50 + 0.045 * index)
        painter.setPen(QPen(QColor(214, 44, 32, alpha), max(1.8, cell * 0.030)))
        painter.drawEllipse(center, radius, radius)
    painter.setPen(QPen(QColor(198, 30, 22), max(2.6, cell * 0.048)))
    painter.drawEllipse(center, cell * 0.465, cell * 0.465)
    painter.restore()
