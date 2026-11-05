"""媒体：BGM 播放器（带音量淡入）、音效、背景图处理。

BGM 用 QMediaPlayer + QAudioOutput；音效走 QSoundEffect（低延迟，与 BGM 音量独立）。
音量淡入 Qt 没有现成组件，这里用 QTimer 分步逼近，逻辑简单且可测。
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Optional

from PySide6.QtCore import QObject, QRectF, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QImage, QPainter, QPixmap
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import QGraphicsBlurEffect, QGraphicsPixmapItem, QGraphicsScene

AUDIO_SUFFIXES = {".mp3", ".ogg", ".wav", ".flac"}


class BgmPlayer(QObject):
    """极简播放列表播放器：顺序 / 单曲 / 随你后续扩展随机。"""

    errorRaised = Signal(str)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._player = QMediaPlayer(self)
        self._output = QAudioOutput(self)
        self._player.setAudioOutput(self._output)

        self._playlist: list[Path] = []
        self._index = 0
        self._volume = 0.65
        self._output.setVolume(self._volume)

        self._fade_timer = QTimer(self)
        self._fade_timer.setInterval(30)
        self._fade_timer.timeout.connect(self._fade_step)
        self._fade_from = 0.0
        self._fade_to = 0.0
        self._fade_span = 1.0
        self._fade_elapsed = 0.0

        self._player.mediaStatusChanged.connect(self._on_status)
        self._player.errorOccurred.connect(self._on_error)

    # ---------- 播放列表 ----------

    def set_playlist(self, paths: Iterable[Path | str]) -> None:
        self._playlist = [Path(p) for p in paths if Path(p).suffix.lower() in AUDIO_SUFFIXES]
        self._index = 0

    @property
    def playlist(self) -> list[Path]:
        return list(self._playlist)

    # ---------- 播放控制 ----------

    def play(self, path: Optional[Path | str] = None, *, fade_in_ms: int = 0) -> None:
        if path is not None:
            self._player.setSource(QUrl.fromLocalFile(str(path)))
        elif self._player.source().isEmpty() and self._playlist:
            self._player.setSource(QUrl.fromLocalFile(str(self._playlist[self._index])))
        if fade_in_ms > 0:
            self._output.setVolume(0.0)
            self.fade_to(self._volume, fade_in_ms)
        else:
            self._output.setVolume(self._volume)
        self._player.play()

    def pause(self) -> None:
        self._player.pause()

    def stop(self) -> None:
        self._player.stop()
        self._fade_timer.stop()

    def next_track(self) -> None:
        if not self._playlist:
            return
        self._index = (self._index + 1) % len(self._playlist)
        self.play(self._playlist[self._index])

    def _on_status(self, status: QMediaPlayer.MediaStatus) -> None:
        if status == QMediaPlayer.EndOfMedia and len(self._playlist) > 1:
            self.next_track()

    def _on_error(self, error: QMediaPlayer.Error, message: str) -> None:
        if error == QMediaPlayer.NoError:
            return
        self.errorRaised.emit(f"音频播放失败：{message or error.name}")
        if len(self._playlist) > 1:
            self.next_track()

    # ---------- 音量 ----------

    @property
    def volume(self) -> float:
        return self._output.volume()

    def set_volume(self, value: float) -> None:
        self._volume = max(0.0, min(1.0, float(value)))
        self._output.setVolume(self._volume)

    def fade_to(self, target: float, duration_ms: int = 800) -> None:
        self._fade_from = self.volume
        self._fade_to = max(0.0, min(1.0, float(target)))
        self._fade_span = max(1.0, duration_ms / 1000.0)
        self._fade_elapsed = 0.0
        self._fade_timer.start()

    def _fade_step(self) -> None:
        self._fade_elapsed += self._fade_timer.interval() / 1000.0
        ratio = min(1.0, self._fade_elapsed / self._fade_span)
        self._output.setVolume(self._fade_from + (self._fade_to - self._fade_from) * ratio)
        if ratio >= 1.0:
            self._fade_timer.stop()
            self._output.setVolume(self._fade_to)

    # ---------- 状态查询（spike 与测试用） ----------

    @property
    def state(self) -> QMediaPlayer.PlaybackState:
        return self._player.playbackState()

    @property
    def position_ms(self) -> int:
        return self._player.position()

    @property
    def duration_ms(self) -> int:
        return self._player.duration()


def blur_image(image: QImage, radius: float = 12.0) -> QImage:
    """用 QGraphicsBlurEffect 做一次模糊（背景虚化用）。"""
    if image.isNull() or radius <= 0:
        return image
    pixmap = QPixmap.fromImage(image)
    scene = QGraphicsScene()
    item = QGraphicsPixmapItem(pixmap)
    effect = QGraphicsBlurEffect()
    effect.setBlurRadius(radius)
    item.setGraphicsEffect(effect)
    scene.addItem(item)
    target = QImage(image.size(), QImage.Format_ARGB32_Premultiplied)
    target.fill(Qt.transparent)
    painter = QPainter(target)
    scene.render(painter, QRectF(target.rect()), QRectF(pixmap.rect()))
    painter.end()
    return target
