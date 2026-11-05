"""设置对话框：头像、昵称、服务器、背景图、音量，一次改完一起生效。"""

from __future__ import annotations

import traceback
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from . import config as appcfg
from .server_addr import parse_address
from .avatar import (
    AvatarCropDialog,
    compress_avatar,
    load_source_image,
    log_line,
    log_path,
    store_avatar,
)
from .avatar_widget import AvatarBadge


class SettingsDialog(QDialog):
    def __init__(
        self,
        cfg: dict,
        avatar_image: Optional[QImage],
        avatar_folder: Path,
        play_preview: Optional[Callable[[], None]] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("设置")
        self._cfg = cfg
        self._avatar_folder = avatar_folder
        self._avatar_image = avatar_image
        self._avatar_bytes: Optional[bytes] = None
        self._avatar_suffix: Optional[str] = None
        self._avatar_file: Optional[str] = appcfg.get(cfg, "avatar.file")
        self._background: Optional[str] = appcfg.get(cfg, "look.background")
        self._play_preview = play_preview

        layout = QVBoxLayout(self)
        layout.addWidget(self._build_identity())
        layout.addWidget(self._build_online())
        layout.addWidget(self._build_look())
        layout.addWidget(self._build_audio())

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.button(QDialogButtonBox.Ok).setText("确定")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.resize(460, 560)

    # ---------- 身份 ----------

    def _build_identity(self) -> QGroupBox:
        box = QGroupBox("身份")
        row = QHBoxLayout(box)

        self.avatar_badge = AvatarBadge(72)
        self.avatar_badge.set_name(str(appcfg.get(self._cfg, "nickname", "玩家")))
        self.avatar_badge.set_image(self._avatar_image)
        row.addWidget(self.avatar_badge)

        column = QVBoxLayout()
        self.nickname_edit = QLineEdit(str(appcfg.get(self._cfg, "nickname", "玩家")))
        self.nickname_edit.textChanged.connect(self.avatar_badge.set_name)
        column.addWidget(QLabel("昵称（对手会看到）"))
        column.addWidget(self.nickname_edit)

        pick = QPushButton("选择头像…")
        pick.clicked.connect(self._pick_avatar)
        column.addWidget(pick)
        self.avatar_size_label = QLabel("原图多大都行，保存时会自动裁成方形并压到 100KB 以内")
        self.avatar_size_label.setStyleSheet("color:#7a6a58; font-size:11px;")
        self.avatar_size_label.setWordWrap(True)
        column.addWidget(self.avatar_size_label)
        row.addLayout(column, 1)
        return box

    def _pick_avatar(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择头像", "", "图片 (*.png *.jpg *.jpeg *.webp *.bmp *.jfif)"
        )
        if not path:
            return
        log_line(f"选择头像: {path}")
        try:
            self._apply_avatar_file(path)
        except Exception as exc:  # noqa: BLE001 - 任何异常都要让用户看见，不能静默失败
            log_line("设置头像异常:\n" + traceback.format_exc())
            QMessageBox.critical(
                self,
                "设置头像失败",
                f"{type(exc).__name__}: {exc}\n\n日志文件:\n{log_path()}",
            )

    def _apply_avatar_file(self, path: str) -> None:
        image, error = load_source_image(path)
        if image is None:
            log_line(f"读取失败: {error}")
            QMessageBox.warning(self, "打不开", f"这张图读不出来：{error}\n\n换成 PNG/JPG 再试一次。")
            return
        if image.width() < 64 or image.height() < 64:
            QMessageBox.warning(self, "图太小", "头像至少要有 64×64，不然放大后会糊。")
            return
        if image.width() * image.height() > 80_000_000:
            QMessageBox.warning(self, "图太大", "这张图分辨率太大了，先缩小一点再试。")
            return

        dialog = AvatarCropDialog(image, self)
        if dialog.exec() != QDialog.Accepted:
            return
        cropped = dialog.result_image()
        data, suffix = compress_avatar(cropped)
        if not data:
            log_line("编码失败：压缩结果为空")
            QMessageBox.warning(self, "处理失败", "这张图编码不出来，换一张试试。")
            return

        stored = ""
        try:
            stored_path = store_avatar(data, suffix, self._avatar_folder)
            stored = str(stored_path)
            self._avatar_file = stored
        except OSError as exc:
            # 存不下也不影响本次使用，只是重启后要重新选
            self._avatar_file = None
            log_line(f"本地保存失败: {exc}")

        self._avatar_image = cropped
        self._avatar_bytes = data
        self._avatar_suffix = suffix
        self.avatar_badge.set_image(cropped)
        hint = f"已压缩到 {len(data) / 1024:.0f}KB（{suffix.upper()}，256×256），上传和显示都用这张"
        if not stored:
            hint += "\n注意：本地保存失败，重启程序后需要重新选择这张图。"
        self.avatar_size_label.setText(hint)
        log_line(f"成功: {len(data)} 字节 {suffix} 落盘={stored or '失败'}")

    # ---------- 联机 ----------

    def _build_online(self) -> QGroupBox:
        box = QGroupBox("联机")
        form = QFormLayout(box)
        saved = appcfg.get(self._cfg, "server.address")
        if not saved:
            saved = f"{appcfg.get(self._cfg, 'server.host', '127.0.0.1')}:{appcfg.get(self._cfg, 'server.port', 8765)}"
        self.server_edit = QLineEdit(str(saved))
        self.server_edit.setToolTip(
            "三种写法都认：\n"
            "  192.168.1.20:8765        局域网直连\n"
            "  wss://abc.trycloudflare.com   Cloudflare 隧道（自动用 443）\n"
            "  https://chess.example.com     域名隧道"
        )
        self.server_edit.setPlaceholderText("192.168.1.20:8765 或 wss://xxx.trycloudflare.com")
        form.addRow("服务器地址", self.server_edit)
        return box

    # ---------- 外观 ----------

    def _build_look(self) -> QGroupBox:
        box = QGroupBox("外观")
        form = QFormLayout(box)

        row = QHBoxLayout()
        self.background_label = QLabel()
        self.background_label.setText(self._background_name())
        pick = QPushButton("选择…")
        pick.clicked.connect(self._pick_background)
        clear = QPushButton("清除")
        clear.clicked.connect(self._clear_background)
        row.addWidget(self.background_label, 1)
        row.addWidget(pick)
        row.addWidget(clear)
        form.addRow("对局背景图", row)

        self.darken_slider = QSlider(Qt.Horizontal)
        self.darken_slider.setRange(0, 90)
        self.darken_slider.setValue(int(appcfg.get(self._cfg, "look.darken", 55)))
        self.darken_value = QLabel(f"{self.darken_slider.value()}%")
        self.darken_slider.valueChanged.connect(lambda v: self.darken_value.setText(f"{v}%"))
        darken_row = QHBoxLayout()
        darken_row.addWidget(self.darken_slider, 1)
        darken_row.addWidget(self.darken_value)
        form.addRow("背景暗化", darken_row)
        return box

    def _background_name(self) -> str:
        return Path(self._background).name if self._background else "（未设置）"

    def _pick_background(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择对局背景图", "", "图片 (*.png *.jpg *.jpeg *.webp *.bmp)"
        )
        if not path:
            return
        self._background = path
        self.background_label.setText(self._background_name())

    def _clear_background(self) -> None:
        self._background = None
        self.background_label.setText(self._background_name())

    # ---------- 声音 ----------

    def _build_audio(self) -> QGroupBox:
        box = QGroupBox("声音")
        form = QFormLayout(box)

        self.bgm_slider = QSlider(Qt.Horizontal)
        self.bgm_slider.setRange(0, 100)
        self.bgm_slider.setValue(int(float(appcfg.get(self._cfg, "audio.bgm_volume", 0.65)) * 100))
        form.addRow("背景音乐音量", self.bgm_slider)

        sfx_row = QHBoxLayout()
        self.sfx_slider = QSlider(Qt.Horizontal)
        self.sfx_slider.setRange(0, 100)
        self.sfx_slider.setValue(int(float(appcfg.get(self._cfg, "audio.sfx_volume", 0.7)) * 100))
        self.sfx_enabled = QCheckBox("开启音效")
        self.sfx_enabled.setChecked(bool(appcfg.get(self._cfg, "audio.sfx_enabled", True)))
        preview = QPushButton("试听")
        preview.clicked.connect(self._preview)
        sfx_row.addWidget(self.sfx_slider, 1)
        sfx_row.addWidget(self.sfx_enabled)
        sfx_row.addWidget(preview)
        form.addRow("音效音量", sfx_row)
        return box

    def _preview(self) -> None:
        if self._play_preview is not None:
            self._play_preview()

    # ---------- 结果 ----------

    def accept(self) -> None:
        """确定前先校验服务器地址，别把错的存进去。"""
        try:
            parse_address(self.server_edit.text())
        except ValueError as exc:
            QMessageBox.warning(self, "服务器地址不对", f"{exc}\n\n例子：192.168.1.20:8765 或 wss://abc.trycloudflare.com")
            return
        super().accept()

    def values(self) -> dict:
        parsed = parse_address(self.server_edit.text())
        return {
            "nickname": self.nickname_edit.text().strip() or "玩家",
            "server": {"address": self.server_edit.text().strip(), "host": parsed.host, "port": parsed.port},
            "look": {"background": self._background, "darken": self.darken_slider.value()},
            "audio": {
                "bgm_volume": self.bgm_slider.value() / 100,
                "sfx_volume": self.sfx_slider.value() / 100,
                "sfx_enabled": self.sfx_enabled.isChecked(),
            },
            "avatar_bytes": self._avatar_bytes,
            "avatar_suffix": self._avatar_suffix,
            "avatar_image": self._avatar_image,
            "avatar_file": self._avatar_file,
        }
