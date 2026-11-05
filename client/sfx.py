"""音效：程序合成木质感音效，不引用任何外部素材。

四个音效全部用正弦波 + 噪声包络现场生成（一次性写进用户目录），
所以既没有版权问题，也不需要往安装包里塞二进制资源。

存放位置按优先级尝试：环境变量 ``YQLXQ_SFX_DIR`` → 用户数据目录 → 系统临时目录。
（后两个都写不进去时静音降级，不影响下棋。）
"""

from __future__ import annotations

import math
import os
import random
import struct
import sys
import tempfile
import wave
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, QStandardPaths, QUrl
from PySide6.QtMultimedia import QSoundEffect

SAMPLE_RATE = 44100
SFX_NAMES = ("move", "capture", "check", "win")


def candidate_dirs() -> list[Path]:
    dirs: list[Path] = []
    override = os.environ.get("YQLXQ_SFX_DIR")
    if override:
        dirs.append(Path(override))
    data = QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)
    if data:
        dirs.append(Path(data) / "sfx")
    else:
        home = Path.home()
        dirs.append(home / "AppData" / "Roaming" / "一起来下棋" / "sfx" if sys.platform == "win32" else home / ".一起来下棋" / "sfx")
    dirs.append(Path(tempfile.gettempdir()) / "yqlxq-sfx")
    return dirs


def _envelope(t: float, duration: float, attack: float = 0.004, decay: float = 0.6) -> float:
    if t < attack:
        return t / attack
    return math.exp(-(t - attack) / max(1e-6, decay * duration))


def _tone(freq: float, duration: float, amplitude: float = 0.7, decay: float = 0.35) -> list[float]:
    count = int(SAMPLE_RATE * duration)
    return [
        amplitude
        * math.sin(2 * math.pi * freq * i / SAMPLE_RATE)
        * _envelope(i / SAMPLE_RATE, duration, decay=decay)
        for i in range(count)
    ]


def _noise_burst(duration: float, amplitude: float = 0.5, decay: float = 0.05) -> list[float]:
    rng = random.Random(20240501)
    count = int(SAMPLE_RATE * duration)
    return [
        amplitude * rng.uniform(-1, 1) * _envelope(i / SAMPLE_RATE, duration, decay=decay)
        for i in range(count)
    ]


def _mix(*tracks: list[float]) -> list[float]:
    length = max(len(track) for track in tracks)
    result = [0.0] * length
    for track in tracks:
        for i, value in enumerate(track):
            result[i] += value
    return result


def _silence(duration: float) -> list[float]:
    return [0.0] * int(SAMPLE_RATE * duration)


def _write_wav(path: Path, samples: list[float]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frames = bytearray()
    for value in samples:
        clamped = max(-1.0, min(1.0, value))
        frames += struct.pack("<h", int(clamped * 32767))
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(bytes(frames))


def _build(name: str) -> list[float]:
    if name == "move":
        return _mix(_noise_burst(0.030, 0.45, decay=0.012), _tone(1800, 0.055, 0.30, decay=0.18))
    if name == "capture":
        return _mix(
            _noise_burst(0.050, 0.55, decay=0.020),
            _tone(420, 0.130, 0.55, decay=0.30),
            _tone(260, 0.150, 0.35, decay=0.35),
        )
    if name == "check":
        return _mix(
            _tone(880, 0.090, 0.42, decay=0.25) + _silence(0.02) + _tone(1320, 0.110, 0.38, decay=0.30)
        )
    if name == "win":
        track: list[float] = []
        for freq in (523.25, 659.25, 783.99):
            track += _tone(freq, 0.150, 0.40, decay=0.40)
        return _mix(track)
    raise ValueError(f"未知音效: {name}")


def ensure_sfx_files(folder: Optional[Path] = None) -> Path:
    """确保四个音效文件存在，返回可用目录；全写不进去时抛 OSError。"""
    targets = [folder] if folder is not None else candidate_dirs()
    last_error: Optional[OSError] = None
    for target in targets:
        try:
            target.mkdir(parents=True, exist_ok=True)
            for name in SFX_NAMES:
                path = target / f"{name}.wav"
                if not path.exists() or path.stat().st_size < 512:
                    _write_wav(path, _build(name))
            return target
        except OSError as exc:
            last_error = exc
            continue
    raise last_error or OSError("没有可写的音效目录")


class SoundBank(QObject):
    """四个音效的播放器。音量 0~1，可整体静音。"""

    def __init__(self, folder: Optional[Path] = None, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._enabled = True
        self._volume = 0.7
        self._effects: dict[str, QSoundEffect] = {}
        self.directory: Optional[Path] = None
        try:
            directory = ensure_sfx_files(folder)
        except OSError:
            return
        self.directory = directory
        for name in SFX_NAMES:
            path = directory / f"{name}.wav"
            if not path.exists():
                continue
            effect = QSoundEffect(self)
            effect.setSource(QUrl.fromLocalFile(str(path)))
            effect.setVolume(self._volume)
            self._effects[name] = effect

    @property
    def ready(self) -> bool:
        return bool(self._effects)

    def status(self) -> dict[str, dict]:
        return {
            name: {"loaded": effect.isLoaded(), "status": effect.status().name, "source": effect.source().toLocalFile()}
            for name, effect in self._effects.items()
        }

    def play(self, name: str) -> None:
        if not self._enabled:
            return
        effect = self._effects.get(name)
        if effect is not None:
            effect.play()

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled

    @property
    def enabled(self) -> bool:
        return self._enabled

    def set_volume(self, volume: float) -> None:
        self._volume = max(0.0, min(1.0, float(volume)))
        for effect in self._effects.values():
            effect.setVolume(self._volume)

    @property
    def volume(self) -> float:
        return self._volume
