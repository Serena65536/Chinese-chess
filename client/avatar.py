"""头像处理：裁剪成正方形、压到 256×256、编码成小文件。

为什么压这么小：头像要上传到服务器并展示给对手看，20~40KB 的东西传起来毫无压力，
而且服务端的上限是 256KB，压过之后留足了余量。
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Optional

import time
import traceback

from PySide6.QtCore import QBuffer, QIODevice, QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QImage,
    QImageReader,
    QImageWriter,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

AVATAR_SIZE = 256
_LOG_NAME = "avatar.log"


def log_line(message: str) -> None:
    """把头像相关的失败原因写进日志，出问题时能直接看文件。"""
    try:
        from . import config as appcfg

        path = appcfg.config_dir() / _LOG_NAME
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}\n")
    except Exception:  # noqa: BLE001 - 日志失败不能影响功能
        pass


def log_path():
    try:
        from . import config as appcfg

        return appcfg.config_dir() / _LOG_NAME
    except Exception:  # noqa: BLE001
        return None


def load_source_image(path: str) -> tuple[QImage | None, str]:
    """读取任意来源的图片，统一转成 32 位色。

    - 用 QImageReader 以便拿到具体错误（比如 CMYK JPEG、缺插件）
    - 顺手应用 EXIF 旋转，手机竖拍的照片不会躺倒
    - 转 RGB32：CMYK / 16 位 / 索引色的图不转成这个格式，后面编码会失败
    """
    reader = QImageReader(path)
    reader.setAutoTransform(True)
    image = reader.read()
    error = reader.errorString()
    if image.isNull():
        image = QImage(path)  # 再给 QImage 一次机会（有些格式 reader 不认但构造能读）
    if image.isNull():
        return None, error or "无法识别的图片格式"
    if image.format() not in (
        QImage.Format_ARGB32,
        QImage.Format_ARGB32_Premultiplied,
        QImage.Format_RGB32,
    ):
        image = image.convertToFormat(QImage.Format_ARGB32)
    return image, ""
#: 单张头像上传的目标体积：压到 96KB 以内，任何传输层都吃得下
AVATAR_TARGET_BYTES = 96 * 1024
#: 源图上限（手机原图一般 3~15MB，给到 40MB 足够，再大先让用户自己缩）
MAX_SOURCE_BYTES = 40 * 1024 * 1024


def _has_webp() -> bool:
    return b"webp" in QImageWriter.supportedImageFormats()


def _save(image: QImage, fmt: str, quality: int = -1) -> bytes:
    buffer = QBuffer()
    buffer.open(QIODevice.WriteOnly)
    ok = image.save(buffer, fmt, quality) if quality >= 0 else image.save(buffer, fmt)
    data = bytes(buffer.data()) if ok else b""
    buffer.close()
    return data


def _encode(image: QImage, quality: int) -> tuple[bytes, str]:
    if _has_webp():
        data = _save(image, "WEBP", quality)
        if data:
            return data, "webp"
    return _save(image, "PNG"), "png"


def compress_avatar(image: QImage, target: int = AVATAR_TARGET_BYTES) -> tuple[bytes, str]:
    """把 256×256 的头像压到 ``target`` 字节以内。

    先降质量（92→85→78→70），还不够就降尺寸（256→224→192→160→128→96）。
    这样无论用户选的原图多花哨（噪点、渐变、照片），都能落到目标体积，
    不会出现"图能选、传不上去"的情况。
    """
    if image.isNull():
        return b"", "png"

    best: tuple[bytes, str] = (b"", "png")
    base = image
    for size in (AVATAR_SIZE, 224, 192, 160, 128, 96):
        current = base if size == AVATAR_SIZE else base.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        for quality in (92, 85, 78, 70):
            data, suffix = _encode(current, quality)
            if not data:
                continue
            if not best[0] or len(data) < len(best[0]):
                best = (data, suffix)
            if len(data) <= target:
                return data, suffix
    return best


def encode_avatar(image: QImage) -> tuple[bytes, str]:
    """兼容老调用点：等于"压到目标体积以内"。"""
    return compress_avatar(image)


def square_crop(source: QImage, center: QPointF, zoom: float, size: int = AVATAR_SIZE) -> QImage:
    """按"中心点 + 缩放"从原图裁出正方形，并缩放成 ``size×size``。"""
    if source.isNull():
        return QImage()
    side = min(source.width(), source.height()) / max(1.0, zoom)
    x = max(0.0, min(source.width() - side, center.x() - side / 2))
    y = max(0.0, min(source.height() - side, center.y() - side / 2))
    target = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
    target.fill(Qt.transparent)
    painter = QPainter(target)
    painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.drawImage(QRectF(0, 0, size, size), source, QRectF(x, y, side, side))
    painter.end()
    return target


def store_avatar(data: bytes, suffix: str, folder: Path) -> Path:
    """落到本地头像目录，文件名用内容哈希（同图不会重复存）。"""
    folder.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha1(data).hexdigest()[:12]
    path = folder / f"me-{digest}.{suffix}"
    if not path.exists():
        path.write_bytes(data)
    return path


def load_avatar_file(path: Optional[str]) -> Optional[QImage]:
    if not path:
        return None
    image = QImage(path)
    return None if image.isNull() else image


class _CropView(QWidget):
    """正方形取景框：拖动平移、滚轮/滑块缩放。"""

    def __init__(self, image: QImage, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.image = image
        self.zoom = 1.0
        self.center = QPointF(image.width() / 2, image.height() / 2)
        self._drag_origin: Optional[QPointF] = None
        self.setMinimumSize(280, 280)
        self.setCursor(Qt.OpenHandCursor)

    def set_zoom(self, zoom: float) -> None:
        self.zoom = max(1.0, min(4.0, zoom))
        self.update()

    def _side(self) -> float:
        return min(self.image.width(), self.image.height()) / max(1.0, self.zoom)

    def _clamp(self) -> None:
        side = self._side()
        self.center.setX(max(side / 2, min(self.image.width() - side / 2, self.center.x())))
        self.center.setY(max(side / 2, min(self.image.height() - side / 2, self.center.y())))

    def render(self, size: int = AVATAR_SIZE) -> QImage:
        return square_crop(self.image, self.center, self.zoom, size)

    def paintEvent(self, event) -> None:  # noqa: N802, ARG002
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        side = min(self.width(), self.height())
        rect = QRectF((self.width() - side) / 2, (self.height() - side) / 2, side, side)

        painter.fillRect(self.rect(), QColor("#1b140f"))
        painter.drawImage(rect, self.render(int(side)))

        # 圆形遮罩：直观告诉用户"最后是圆的"
        path = QPainterPath()
        path.addEllipse(rect)
        painter.setBrush(QColor(0, 0, 0, 90))
        painter.setPen(Qt.NoPen)
        outer = QPainterPath()
        outer.addRect(rect)
        painter.drawPath(outer.subtracted(path))

        painter.setPen(QPen(QColor("#e0a040"), 2))
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(rect)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._drag_origin = event.position()
            self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag_origin is None:
            return
        delta = event.position() - self._drag_origin
        self._drag_origin = event.position()
        scale = min(self.width(), self.height()) / self._side()
        self.center -= QPointF(delta.x() / scale, delta.y() / scale)
        self._clamp()
        self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802, ARG002
        self._drag_origin = None
        self.setCursor(Qt.OpenHandCursor)

    def wheelEvent(self, event) -> None:  # noqa: N802
        step = 0.08 if event.angleDelta().y() > 0 else -0.08
        self.set_zoom(self.zoom + step)


class AvatarCropDialog(QDialog):
    """选图之后的裁剪对话框。"""

    def __init__(self, image: QImage, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("调整头像")
        self._view = _CropView(image, self)

        self._slider = QSlider(Qt.Horizontal, self)
        self._slider.setRange(100, 400)
        self._slider.setValue(100)
        self._slider.valueChanged.connect(lambda value: self._view.set_zoom(value / 100))
        self._view.set_zoom(1.0)

        hint = QLabel("拖动图片调整位置，滚轮或滑块缩放；头像会裁成圆形。")
        hint.setWordWrap(True)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.button(QDialogButtonBox.Ok).setText("确定")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self._view, 1)
        layout.addWidget(hint)
        layout.addWidget(self._slider)
        layout.addWidget(buttons)
        self.resize(360, 460)

    def result_image(self) -> QImage:
        return self._view.render(AVATAR_SIZE)
