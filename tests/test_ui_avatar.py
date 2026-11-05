"""界面层：头像角标、双方信息栏、设置应用到视图。"""

from __future__ import annotations

import os
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("YQLXQ_CONFIG_DIR", os.path.join(tempfile.gettempdir(), "yqlxq-test-config"))
os.environ.setdefault("YQLXQ_SFX_DIR", os.path.join(tempfile.gettempdir(), "yqlxq-sfx-test"))

from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from client.app import MainWindow
from client.avatar_widget import AvatarBadge, fallback_color

# QWidget 必须先有 QApplication，否则 Qt 会直接 abort（不是 Python 异常，pytest 抓不到）
_APP = QApplication.instance() or QApplication([])


def _window() -> MainWindow:
    app = _APP
    window = MainWindow()
    window.show_result_dialogs = False
    app.processEvents()
    return window


def test_badge_falls_back_to_initial_and_color():
    badge = AvatarBadge(48)
    badge.set_name("老王")
    assert badge.has_image is False
    assert badge.toolTip() == "老王"
    assert fallback_color("老王").isValid()


def test_badge_accepts_image():
    image = QImage(32, 32, QImage.Format_ARGB32)
    image.fill(QColor("#336699"))
    badge = AvatarBadge(48)
    badge.set_image(image)
    assert badge.has_image is True


def test_players_box_updates_with_seats():
    window = _window()
    try:
        window._set_players(
            [
                {"seat": 0, "name": "红方", "avatar": None},
                {"seat": 1, "name": "黑方", "avatar": None},
            ]
        )
        assert window.players_box.isVisible() is False or window.players_box.isVisibleTo(window)
        assert window.my_name_label.text() in ("红方", "黑方")
        assert window.opponent_name_label.text() in ("红方", "黑方")
        assert window.my_name_label.text() != window.opponent_name_label.text()

        window._set_players([{"seat": 0, "name": "只有我", "avatar": None}])
        assert window.players_box.isVisible() is False
    finally:
        window.close()


def test_apply_look_and_audio():
    window = _window()
    try:
        window._apply_look({"background": None, "darken": 30})
        assert window.view.background_darken == 30
        assert window.view.background_image is None

        window._apply_audio({"bgm_volume": 0.4, "sfx_volume": 0.2, "sfx_enabled": False})
        assert abs(window.bgm.volume - 0.4) < 1e-6
        assert abs(window.sounds.volume - 0.2) < 1e-6
        assert window.sounds.enabled is False
        assert window.sound_action.isChecked() is False
    finally:
        window.close()


def test_apply_settings_sets_avatar_and_config():
    """把设置页的返回值应用到主窗口（等价于点「确定」）。"""
    from PySide6.QtCore import QBuffer, QIODevice

    window = _window()
    try:
        image = QImage(256, 256, QImage.Format_ARGB32)
        image.fill(QColor("#8e3b2f"))
        buffer = QBuffer()
        buffer.open(QIODevice.WriteOnly)
        image.save(buffer, "PNG")
        data = bytes(buffer.data())

        window._apply_settings(  # noqa: SLF001
            {
                "nickname": "老李",
                "server": {"address": "192.168.1.9:9100", "host": "192.168.1.9", "port": 9100},
                "look": {"background": None, "darken": 66},
                "audio": {"bgm_volume": 0.5, "sfx_volume": 0.6, "sfx_enabled": True},
                "avatar_bytes": data,
                "avatar_suffix": "png",
                "avatar_image": image,
                "avatar_file": None,
            }
        )

        assert window.my_badge.has_image is True
        assert window.nickname == "老李"
        assert window.server_address == "192.168.1.9:9100"
        assert window.view.background_darken == 66
        assert window._avatar_bytes == data  # noqa: SLF001
        assert window._avatar_id is None  # 换了头像要重新上传  # noqa: SLF001
    finally:
        window.close()
