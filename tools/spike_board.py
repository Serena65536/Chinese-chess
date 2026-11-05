"""spike ① ③：棋盘渲染 + 窗口缩放不变形 + 背景图暗化后可读。

跑法（在仓库根目录）：
    .venv\\Scripts\\python.exe tools\\spike_board.py

产物：docs/m0/shots/*.png 与终端里的数值报告。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, QRadialGradient  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from client.app import MainWindow  # noqa: E402
from client.board_view import GRID_H, GRID_W, MARGIN  # noqa: E402

SHOTS = ROOT / "docs" / "m0" / "shots"
SIZES = [(760, 880, "board-760x880"), (1280, 1500, "board-1280x1500"), (520, 900, "board-520x900")]


def find_test_photo() -> QImage | None:
    """找一张真实照片测试背景（只在本机读，不随程序分发）。"""
    candidates = [
        Path(os.environ.get("SystemRoot", r"C:\Windows")) / "Web" / "Wallpaper",
    ]
    for folder in candidates:
        if not folder.exists():
            continue
        for ext in ("*.jpg", "*.jpeg", "*.png"):
            found = sorted(folder.rglob(ext))
            if found:
                return QImage(str(found[0]))
    return None


def make_test_photo(width: int = 1600, height: int = 1000) -> QImage:
    """没有可用照片时合成一张"像照片"的图：天空渐变 + 山 + 太阳。"""
    image = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    sky = QLinearGradient(0, 0, 0, height)
    sky.setColorAt(0.0, QColor("#0B2545"))
    sky.setColorAt(0.55, QColor("#3E6B8E"))
    sky.setColorAt(1.0, QColor("#C9A26B"))
    painter.fillRect(image.rect(), sky)

    sun = QRadialGradient(width * 0.72, height * 0.34, height * 0.35)
    sun.setColorAt(0.0, QColor(255, 226, 168, 230))
    sun.setColorAt(1.0, QColor(255, 226, 168, 0))
    painter.setPen(Qt.NoPen)
    painter.setBrush(sun)
    painter.drawEllipse(int(width * 0.72 - height * 0.35), int(height * 0.34 - height * 0.35), int(height * 0.7), int(height * 0.7))

    painter.setBrush(QColor("#243447"))
    painter.drawPolygon(
        [
            (0, int(height * 0.72)),
            (int(width * 0.22), int(height * 0.52)),
            (int(width * 0.42), int(height * 0.74)),
            (int(width * 0.62), int(height * 0.56)),
            (int(width), int(height * 0.78)),
            (int(width), height),
            (0, height),
        ]
    )
    painter.setBrush(QColor("#15202B"))
    painter.drawPolygon(
        [
            (0, int(height * 0.85)),
            (int(width * 0.3), int(height * 0.7)),
            (int(width * 0.55), int(height * 0.88)),
            (int(width * 0.8), int(height * 0.78)),
            (int(width), int(height * 0.9)),
            (int(width), height),
            (0, height),
        ]
    )
    painter.end()
    return image


def main() -> int:
    SHOTS.mkdir(parents=True, exist_ok=True)
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()

    report: dict = {"sizes": [], "background": {}, "selection": {}}

    for width, height, name in SIZES:
        window.resize(width, height)
        app.processEvents()
        window.view.fit()
        app.processEvents()
        view = window.view
        transform = view.transform()
        board_rect = view.mapFromScene(QRectF(MARGIN, MARGIN, GRID_W, GRID_H)).boundingRect()
        scene_px = view.mapFromScene(QRectF(0, 0, view.sceneRect().width(), view.sceneRect().height())).boundingRect()
        viewport = view.viewport().rect()
        cell_px = board_rect.width() / 8.0
        aspect = board_rect.width() / board_rect.height() if board_rect.height() else 0
        report["sizes"].append(
            {
                "window": [width, height],
                "transform_m11": round(transform.m11(), 4),
                "transform_m22": round(transform.m22(), 4),
                "uniform_scale": abs(transform.m11() - transform.m22()) < 1e-6,
                "board_px": [round(board_rect.width(), 1), round(board_rect.height(), 1)],
                "cell_px": round(cell_px, 2),
                "aspect": round(aspect, 5),
                "aspect_ok": abs(aspect - 8 / 9) < 1e-3,
                "viewport": [viewport.width(), viewport.height()],
                "scene_px": [scene_px.x(), scene_px.y(), scene_px.width(), scene_px.height()],
                "scene_fits": viewport.contains(scene_px),
            }
        )
        window.grab().save(str(SHOTS / f"{name}.png"))

    # 背景图 + 暗化
    photo = find_test_photo()
    source = "系统壁纸" if photo is not None else "程序合成图"
    if photo is None:
        photo = make_test_photo()
    window.resize(900, 1040)
    window.view.set_background(photo, 55)
    app.processEvents()
    window.grab().save(str(SHOTS / "board-background-dark55.png"))
    report["background"] = {"source": source, "image_size": [photo.width(), photo.height()]}

    # 选中棋子 + 合法落点提示（用真实的伪合法着法，不写死）
    from xiangqi_core import generate_pseudo_moves

    cannon = (1, 7)
    hints = generate_pseudo_moves(window.view.board, cannon)
    window.view.set_selection(cannon, hints)
    app.processEvents()
    window.grab().save(str(SHOTS / "board-selection-cannon.png"))
    report["selection"] = {"piece": "炮 (b2)", "hint_points": len(hints)}

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
