"""头像角标：圆形显示，没有头像时用昵称首字生成色块。"""

from __future__ import annotations

import hashlib
from typing import Optional

from PySide6.QtCore import QRectF, Qt, QUrl
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPen
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkProxy, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import QWidget

_FALLBACK_COLORS = ("#7a5230", "#3f6b57", "#5a4a7a", "#7a4a4a", "#4a5f7a", "#6b6b3f")


def fallback_color(name: str) -> QColor:
    digest = hashlib.md5(name.encode("utf-8")).digest()
    return QColor(_FALLBACK_COLORS[digest[0] % len(_FALLBACK_COLORS)])


class AvatarBadge(QWidget):
    def __init__(self, size: int = 52, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._size = size
        self._image: Optional[QImage] = None
        self._name = ""
        self.setFixedSize(size, size)
        self.setToolTip("")

    def set_name(self, name: str) -> None:
        self._name = name
        self.setToolTip(name)
        self.update()

    def set_image(self, image: Optional[QImage]) -> None:
        self._image = None if image is None or image.isNull() else image
        self.update()

    @property
    def has_image(self) -> bool:
        return self._image is not None

    def paintEvent(self, event) -> None:  # noqa: N802, ARG002
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        rect = QRectF(1, 1, self._size - 2, self._size - 2)

        path = QPainterPath()
        path.addEllipse(rect)

        if self._image is not None:
            painter.save()
            painter.setClipPath(path)
            side = min(self._image.width(), self._image.height())
            source = QRectF(
                (self._image.width() - side) / 2,
                (self._image.height() - side) / 2,
                side,
                side,
            )
            painter.drawImage(rect, self._image, source)
            painter.restore()
        else:
            painter.setClipPath(path)
            painter.setPen(Qt.NoPen)
            painter.setBrush(fallback_color(self._name or "?"))
            painter.drawEllipse(rect)
            painter.setClipping(False)
            painter.setPen(QPen(QColor("#f3e7cf")))
            font = QFont()
            font.setPixelSize(int(self._size * 0.44))
            font.setBold(True)
            painter.setFont(font)
            initial = (self._name or "?")[0]
            painter.drawText(rect, Qt.AlignCenter, initial)

        painter.setPen(QPen(QColor("#e0a040" if self._image is not None else "#55402c"), 2))
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(rect)


class AvatarLoader(QWidget):  # QWidget 只是为了拿父子关系，实际是个加载器
    """按 id 拉头像，内存里缓存，避免每帧都发请求。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setVisible(False)
        self._manager = QNetworkAccessManager(self)
        self._manager.setProxy(QNetworkProxy(QNetworkProxy.ProxyType.NoProxy))
        self._manager.finished.connect(self._on_finished)
        self._cache: dict[str, QImage] = {}
        self._pending: set[str] = set()
        self._base = ""
        self._listeners: list[tuple[str, "callable"]] = []

    def set_base_url(self, base: str) -> None:
        self._base = base.rstrip("/")

    def cached(self, avatar_id: Optional[str]) -> Optional[QImage]:
        return self._cache.get(avatar_id) if avatar_id else None

    def subscribe(self, avatar_id: Optional[str], callback) -> None:  # noqa: ANN001
        if not avatar_id:
            return
        if avatar_id in self._cache:
            callback(self._cache[avatar_id])
            return
        self._listeners.append((avatar_id, callback))
        self.fetch(avatar_id)

    def fetch(self, avatar_id: Optional[str]) -> None:
        if not avatar_id or not self._base or avatar_id in self._cache or avatar_id in self._pending:
            return
        self._pending.add(avatar_id)
        request = QNetworkRequest(QUrl(f"{self._base}/avatar/{avatar_id}"))
        self._manager.get(request)

    def _on_finished(self, reply: QNetworkReply) -> None:
        url = reply.url().toString()
        avatar_id = url.rsplit("/", 1)[-1]
        self._pending.discard(avatar_id)
        if reply.error() == QNetworkReply.NoError:
            image = QImage.fromData(reply.readAll())
            if not image.isNull():
                self._cache[avatar_id] = image
                for key, callback in list(self._listeners):
                    if key == avatar_id:
                        callback(image)
                        self._listeners.remove((key, callback))
        reply.deleteLater()
