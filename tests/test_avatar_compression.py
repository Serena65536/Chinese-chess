"""头像压缩测试：无论原图多花哨，都要压到目标体积以内。

这条是为了修"选了普通照片却传不上去"的问题——根因是 WebSocket 单帧上限装不下
base64 后的图。现在客户端负责把体积压到 96KB 以内，服务端上限放到 512KB。
"""

from __future__ import annotations

import os
import random

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QImage, QPainter

from client.avatar import AVATAR_SIZE, AVATAR_TARGET_BYTES, compress_avatar, square_crop


def mosaic(size: int = AVATAR_SIZE) -> QImage:
    """彩色噪点图：压缩率最差的极端情况（照片一般比它好压）。"""
    image = QImage(size, size, QImage.Format_ARGB32)
    painter = QPainter(image)
    rng = random.Random(7)
    for y in range(size):
        for x in range(0, size, 2):
            painter.setPen(QColor(rng.randrange(256), rng.randrange(256), rng.randrange(256)))
            painter.drawPoint(x, y)
    painter.end()
    return image


def test_noisy_avatar_fits_target():
    data, suffix = compress_avatar(mosaic())
    assert data, "压缩结果不能为空"
    assert len(data) <= AVATAR_TARGET_BYTES, f"{len(data)} 字节超过了目标 {AVATAR_TARGET_BYTES}"
    assert data[:4] in (b"RIFF", b"\x89PNG")


def test_large_source_photo_fits_target():
    """4000×3000 的原图 → 裁成 256 → 压到目标以内。"""
    big = mosaic(1600)
    cropped = square_crop(big, QPointF(800, 800), 1.0, AVATAR_SIZE)
    data, suffix = compress_avatar(cropped)
    assert len(data) <= AVATAR_TARGET_BYTES
    assert suffix in ("webp", "png")


def test_gradient_avatar_fits_target():
    image = QImage(AVATAR_SIZE, AVATAR_SIZE, QImage.Format_ARGB32)
    painter = QPainter(image)
    for y in range(AVATAR_SIZE):
        painter.setPen(QColor(y, 120, 255 - y))
        painter.drawLine(0, y, AVATAR_SIZE, y)
    painter.end()
    data, _ = compress_avatar(image)
    assert len(data) <= AVATAR_TARGET_BYTES


def test_compress_handles_empty_image():
    data, suffix = compress_avatar(QImage())
    assert data == b""
    assert suffix == "png"


def test_base64_stays_under_ws_frame_limit():
    """上传走的 JSON 文本不能撑爆服务端 4MB 的单帧上限（含 base64 膨胀）。"""
    import base64
    import json

    data, _ = compress_avatar(mosaic())
    frame = json.dumps(
        {"type": "avatar_upload", "data": base64.b64encode(data).decode()},
        ensure_ascii=False,
    ).encode("utf-8")
    assert len(frame) < 512 * 1024, f"单帧 {len(frame)} 字节，太大了"
