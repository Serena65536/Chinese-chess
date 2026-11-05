"""首次启动的欢迎/引导页：三步说清"怎么下、怎么联机、怎么个性化"。"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from .version import __app_name__, __version__

STEPS = (
    ("1", "先自己下一盘", "直接点棋子就能走，红黑轮流。规则（将军、将死、困毙、60 回合、长将）都已内置。"),
    ("2", "想联机？先有服务器", "让朋友开「一起来下棋-服务端」，或者你自己开；然后在「设置」里填他的地址，形如 192.168.1.20:8765。"),
    ("3", "把界面变成你的", "「设置」里可以换头像、换背景图、调背景音乐和音效音量。头像对手也能看到。"),
)


class OnboardingDialog(QDialog):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"欢迎使用 {__app_name__}")
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        title = QLabel(f"{__app_name__} v{__version__}")
        title.setStyleSheet("font-size: 22px; font-weight: 700;")
        layout.addWidget(title)

        subtitle = QLabel("电脑端中国象棋，两个人远程对战，没有电脑对手。")
        subtitle.setStyleSheet("color:#6b6459;")
        layout.addWidget(subtitle)

        for number, head, body in STEPS:
            block = QWidget(self)
            block_layout = QVBoxLayout(block)
            block_layout.setContentsMargins(0, 0, 0, 0)
            block_layout.setSpacing(2)
            head_label = QLabel(f"{number}. {head}")
            head_label.setStyleSheet("font-size: 14px; font-weight: 600;")
            body_label = QLabel(body)
            body_label.setWordWrap(True)
            body_label.setStyleSheet("color:#4a453d;")
            block_layout.addWidget(head_label)
            block_layout.addWidget(body_label)
            layout.addWidget(block)

        self.hide_next_time = QCheckBox("以后不再显示")
        self.hide_next_time.setChecked(True)
        layout.addWidget(self.hide_next_time)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok, self)
        buttons.button(QDialogButtonBox.Ok).setText("开始下棋")
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

        self.setMinimumWidth(460)
