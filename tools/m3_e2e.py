"""M3 取证：两个客户端互看头像 + 设置页 + 裁剪对话框 + 配置持久化。

产物：docs/m3/shots/*.png 与 docs/m3/report.json
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Callable

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("YQLXQ_SFX_DIR", str(ROOT / "build" / "sfx"))
os.environ.setdefault("YQLXQ_CONFIG_DIR", str(ROOT / "build" / "m3_config"))

from aiohttp import web  # noqa: E402
from PySide6.QtCore import QTimer, Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont, QImage, QLinearGradient, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from client import config as appcfg  # noqa: E402
from client.app import MainWindow  # noqa: E402
from client.avatar import AvatarCropDialog, encode_avatar, store_avatar  # noqa: E402
from client.settings_dialog import SettingsDialog  # noqa: E402
from server.main import create_app  # noqa: E402

SHOTS = ROOT / "docs" / "m3" / "shots"
DATA_DIR = ROOT / "build" / "m3_server_data"


class Wait:
    def __init__(self, predicate: Callable[[], object], label: str, timeout: float = 15.0) -> None:
        self.predicate = predicate
        self.label = label
        self.deadline = time.monotonic() + timeout


def make_portrait(text: str, top: str, bottom: str, accent: str) -> QImage:
    """合成一张"人像"：渐变底 + 圆角色块 + 大字，用来当头像素材。"""
    image = QImage(600, 600, QImage.Format_ARGB32)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    gradient = QLinearGradient(0, 0, 0, 600)
    gradient.setColorAt(0.0, QColor(top))
    gradient.setColorAt(1.0, QColor(bottom))
    painter.fillRect(image.rect(), gradient)
    painter.setBrush(QColor(accent))
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(150, 120, 300, 300)
    painter.setBrush(QColor(255, 255, 255, 60))
    painter.drawEllipse(90, 400, 420, 420)
    painter.setPen(QColor("#ffffff"))
    font = QFont()
    font.setPixelSize(180)
    font.setBold(True)
    painter.setFont(font)
    painter.drawText(image.rect(), Qt.AlignCenter, text)
    painter.end()
    return image


def start_server_thread() -> tuple[asyncio.AbstractEventLoop, dict]:
    loop = asyncio.new_event_loop()
    threading.Thread(target=loop.run_forever, daemon=True).start()
    state: dict = {}

    async def boot() -> None:
        app = create_app(data_dir=str(DATA_DIR))
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        state["runner"] = runner
        state["port"] = site._server.sockets[0].getsockname()[1]  # noqa: SLF001

    asyncio.run_coroutine_threadsafe(boot(), loop).result(timeout=10)
    return loop, state


def scenario(a: MainWindow, b: MainWindow, port: int):
    ca, cb = a.client, b.client
    assert ca is not None and cb is not None
    ca.connect_to("127.0.0.1", port)
    cb.connect_to("127.0.0.1", port)
    yield Wait(lambda: ca.connected and cb.connected, "两端连上")
    # 连上后客户端会先上传头像，拿到服务端返回的 id 才能建房（房间要带 avatar）
    yield Wait(lambda: a._avatar_id is not None and b._avatar_id is not None, "头像上传完成", 20.0)  # noqa: SLF001

    ca.create_room("红方", a._avatar_id)  # noqa: SLF001
    yield Wait(lambda: a.room_code is not None, "A 建房")
    code = a.room_code

    cb.join_room(str(code), "黑方", b._avatar_id)  # noqa: SLF001
    yield Wait(lambda: b.room_code == code, "B 进房")

    ca.ready()
    cb.ready()
    yield Wait(lambda: a.online and b.online, "开局")

    # 头像要先上传再取回：等两边的对手头像都加载出来
    yield Wait(
        lambda: a.opponent_badge.has_image and b.opponent_badge.has_image,
        "双方互相看到对方头像",
        20.0,
    )
    yield Wait(lambda: True, "拍照：联机头像")

    return {
        "room_code": code,
        "a_avatar_uploaded": bool(a._avatar_id),  # noqa: SLF001
        "b_avatar_uploaded": bool(b._avatar_id),  # noqa: SLF001
        "a_sees_opponent_avatar": a.opponent_badge.has_image,
        "b_sees_opponent_avatar": b.opponent_badge.has_image,
        "a_my_name": a.my_name_label.text(),
        "a_opponent_name": a.opponent_name_label.text(),
    }


def main() -> int:
    SHOTS.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    loop, state = start_server_thread()
    port = state["port"]

    app = QApplication(sys.argv)
    a = MainWindow()
    b = MainWindow()
    for window in (a, b):
        window.show_result_dialogs = False
        window.resize(1080, 900)
        window.show()
    app.processEvents()
    a._ensure_client()  # noqa: SLF001
    b._ensure_client()  # noqa: SLF001

    # 给两端各配一张不同的头像（走的是真实的上传路径）
    avatar_a = make_portrait("红", "#8e3b2f", "#3d1712", "#e8c07a")
    avatar_b = make_portrait("黑", "#2f4f6b", "#111c26", "#a8c6e0")
    for window, image in ((a, avatar_a), (b, avatar_b)):
        data, suffix = encode_avatar(image)
        store_avatar(data, suffix, appcfg.config_dir() / "avatars")
        window._avatar_image = image  # noqa: SLF001
        window._avatar_bytes = data  # noqa: SLF001
        window.my_badge.set_image(image)

    report: dict = {"avatar_bytes": {}, "crop": {}}
    for name, image in (("a", avatar_a), ("b", avatar_b)):
        data, suffix = encode_avatar(image)
        report["avatar_bytes"][name] = {"bytes": len(data), "format": suffix}

    script = scenario(a, b, port)
    box: dict = {"pending": None}
    outcome: dict = {"status": "running"}

    def finish(status: str, payload=None, message: str = "") -> None:  # noqa: ANN001
        outcome.update({"status": status, "payload": payload, "message": message})
        timer.stop()
        app.quit()

    def step() -> None:
        try:
            current = box["pending"]
            if current is None:
                box["pending"] = next(script)
                return
            if isinstance(current, Wait):
                value = current.predicate()
                if not value and time.monotonic() > current.deadline:
                    finish("timeout", message=f"等待超时：{current.label}")
                    return
                if value:
                    if current.label == "拍照：联机头像":
                        a.grab().save(str(SHOTS / "02-online-avatars.png"))
                    box["pending"] = script.send(value)
        except StopIteration as stop:
            finish("done", payload=stop.value)
        except Exception as exc:  # noqa: BLE001
            finish("error", message=f"{type(exc).__name__}: {exc}")

    timer = QTimer()
    timer.timeout.connect(step)
    timer.setInterval(30)
    timer.start()
    QTimer.singleShot(0, step)
    app.exec()

    if outcome["status"] != "done":
        print("RESULT: FAIL", outcome["status"], outcome.get("message", ""))
        return 1
    report.update(outcome["payload"])

    # 设置对话框截图
    cfg = appcfg.load()
    dialog = SettingsDialog(cfg, a._avatar_image, appcfg.config_dir() / "avatars")  # noqa: SLF001
    dialog.resize(460, 620)
    dialog.show()
    app.processEvents()
    dialog.grab().save(str(SHOTS / "01-settings.png"))
    dialog.close()

    # 头像裁剪对话框截图
    crop = AvatarCropDialog(avatar_a)
    crop.resize(380, 500)
    crop.show()
    app.processEvents()
    crop._view.set_zoom(1.4)  # noqa: SLF001
    app.processEvents()
    crop.grab().save(str(SHOTS / "03-avatar-crop.png"))
    report["crop"] = {"source": "合成的 600×600 人像", "zoom": 1.4}
    crop.close()

    # 持久化：把头像写进配置，新建一个窗口看能不能读回来
    data, suffix = encode_avatar(avatar_a)
    path = store_avatar(data, suffix, appcfg.config_dir() / "avatars")
    appcfg.set_value(cfg, "avatar", {"id": None, "file": str(path)})
    appcfg.set_value(cfg, "look", {"background": None, "darken": 70})
    appcfg.set_value(cfg, "audio", {"bgm_volume": 0.33, "sfx_volume": 0.44, "sfx_enabled": False})
    appcfg.save(cfg)

    fresh = MainWindow()
    fresh.show_result_dialogs = False
    fresh.show()
    app.processEvents()
    report["persistence"] = {
        "config_file": str(appcfg.config_file()),
        "avatar_loaded": fresh.my_badge.has_image,
        "darken": fresh.view.background_darken,
        "bgm_volume": round(fresh.bgm.volume, 2),
        "sfx_enabled": fresh.sounds.enabled,
    }
    fresh.close()

    for window in (a, b):
        if window.client is not None:
            window.client.close()
    asyncio.run_coroutine_threadsafe(state["runner"].cleanup(), loop).result(timeout=10)

    report["server_port"] = port
    out = ROOT / "docs" / "m3" / "report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    ok = (
        report["a_sees_opponent_avatar"]
        and report["b_sees_opponent_avatar"]
        and report["persistence"]["avatar_loaded"]
        and report["persistence"]["sfx_enabled"] is False
    )
    print(f"report -> {out}")
    print("mutual avatars:", report["a_sees_opponent_avatar"], report["b_sees_opponent_avatar"])
    print("persistence:", report["persistence"])
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
