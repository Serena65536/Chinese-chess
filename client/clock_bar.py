"""计时条：显示双方剩余时间，读秒阶段变成 30 秒倒数。

服务端每秒推一次权威时间，客户端在两次推送之间用本地时钟插值，
这样数字是平滑跳动的，不会一秒一顿。
"""

from __future__ import annotations

import time
from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from xiangqi_core import Color

ACTIVE_STYLE = "color: #ffd479; font-size: 17px; font-weight: 700;"
IDLE_STYLE = "color: #9a8b74; font-size: 15px;"
DANGER_STYLE = "color: #ff6b5e; font-size: 17px; font-weight: 700;"


class _Row(QFrame):
    def __init__(self, title: str) -> None:
        super().__init__()
        self.setStyleSheet("background: #1b140f; border-radius: 6px;")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 5, 10, 5)
        self.name_label = QLabel(title)
        self.name_label.setStyleSheet(IDLE_STYLE)
        self.time_label = QLabel("--:--")
        self.time_label.setStyleSheet(IDLE_STYLE)
        self.time_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(self.name_label)
        layout.addStretch(1)
        layout.addWidget(self.time_label)

    def update_view(self, name: str, text: str, style: str) -> None:
        self.name_label.setText(name)
        self.time_label.setText(text)
        self.name_label.setStyleSheet(style)
        self.time_label.setStyleSheet(style)


class ClockBar(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.black_row = _Row("黑方")
        self.red_row = _Row("红方")
        layout.addWidget(self.black_row)  # 对手在上
        layout.addWidget(self.red_row)

        self._snapshot: dict = {}
        self._received_at = 0.0
        self._names = {"RED": "红方", "BLACK": "黑方"}
        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._refresh)
        self._timer.start()

    # ---------- 外部接口 ----------

    def set_names(self, red: str, black: str) -> None:
        self._names = {"RED": red or "红方", "BLACK": black or "黑方"}

    def apply(self, snapshot: dict) -> None:
        self._snapshot = dict(snapshot or {})
        self._received_at = time.monotonic()
        self._refresh()

    def reset(self) -> None:
        self._snapshot = {}
        self._refresh()

    # ---------- 渲染 ----------

    def _remaining(self, key: str) -> int:
        if not self._snapshot:
            return 0
        base = int(self._snapshot.get(f"{key.lower()}Ms", 0))
        if self._snapshot.get("paused"):
            return base
        if self._snapshot.get("turn") != key:
            return base
        drift = int((time.monotonic() - self._received_at) * 1000)
        return max(0, base - drift)

    @staticmethod
    def _format(ms: int) -> str:
        ms = max(0, ms)
        if ms < 10_000:  # 最后 10 秒显示到 0.1 秒，够紧张
            return f"00:{ms / 1000:04.1f}"
        total = ms // 1000
        return f"{total // 60:02d}:{total % 60:02d}"

    def _row_text(self, key: str) -> tuple[str, str]:
        if not self._snapshot:
            return "--:--", IDLE_STYLE
        remaining = self._remaining(key)
        turn = self._snapshot.get("turn")
        phase = self._snapshot.get("phase")
        paused = bool(self._snapshot.get("paused"))
        if key == turn and phase == "byo":
            text = f"读秒 {max(0, remaining) / 1000:04.1f}"
        else:
            text = self._format(remaining)
        if key == turn and not paused:
            style = DANGER_STYLE if remaining <= 10_000 else ACTIVE_STYLE
        else:
            style = IDLE_STYLE
        if paused and key == turn:
            text += " ⏸"
        return text, style

    def _refresh(self) -> None:
        for key, row in (("RED", self.red_row), ("BLACK", self.black_row)):
            text, style = self._row_text(key)
            row.update_view(self._names.get(key, key), text, style)
