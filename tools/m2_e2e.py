"""M2 端到端取证：两个真实 Qt 客户端 + 进程内服务端，走完一局并抓关键画面。

跑法：
    .venv\\Scripts\\python.exe tools\\m2_e2e.py

产物：docs/m2/shots/*.png 与 docs/m2/report.json

为了在截图里看到"读秒"，服务端配置成 4 秒保留 + 30 秒读秒（正式运行是 30 分钟 + 30 秒）。
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

from aiohttp import web  # noqa: E402
from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from client.app import MainWindow  # noqa: E402
from server.clock import ClockConfig  # noqa: E402
from server.main import create_app  # noqa: E402
from xiangqi_core import Move  # noqa: E402

SHOTS = ROOT / "docs" / "m2" / "shots"
SERVER_CONFIG = ClockConfig(base_ms=4000, byo_ms=30_000)

OPENING = [
    ((1, 7), (4, 7)),  # 红：炮二平五
    ((7, 0), (6, 2)),  # 黑：马８进７
    ((1, 9), (2, 7)),  # 红：马二进三
    ((7, 2), (7, 4)),  # 黑：炮８进２
    ((0, 9), (0, 7)),  # 红：车一进二
    ((0, 3), (0, 4)),  # 黑：卒１进１
]


TRACE: dict = {}


class Wait:
    def __init__(self, predicate: Callable[[], object], label: str, timeout: float = 15.0) -> None:
        self.predicate = predicate
        self.label = label
        self.deadline = time.monotonic() + timeout


class Sleep:
    def __init__(self, seconds: float) -> None:
        self.until = time.monotonic() + seconds


def start_server_thread(config: ClockConfig) -> tuple[asyncio.AbstractEventLoop, dict]:
    loop = asyncio.new_event_loop()
    threading.Thread(target=loop.run_forever, daemon=True).start()
    state: dict = {}
    ready = threading.Event()

    async def boot() -> None:
        app = create_app(config)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        state["runner"] = runner
        state["port"] = site._server.sockets[0].getsockname()[1]  # noqa: SLF001
        ready.set()

    asyncio.run_coroutine_threadsafe(boot(), loop).result(timeout=10)
    ready.wait(10)
    return loop, state


def scenario(a: MainWindow, b: MainWindow, host: str, port: int):
    ca, cb = a.client, b.client
    assert ca is not None and cb is not None

    ca.connect_to(host, port)
    cb.connect_to(host, port)
    yield Wait(lambda: ca.connected and cb.connected, "两端连上服务器")

    ca.create_room("红方")
    yield Wait(lambda: a.room_code is not None, "A 建房拿到房间码")
    code = a.room_code

    cb.join_room(str(code), "黑方")
    yield Wait(lambda: b.room_code == code and b.my_seat == 1, "B 进入房间")
    TRACE["after_join"] = {"room": cb.room_code, "token": bool(cb.token), "seat": cb.seat}

    ca.ready()
    cb.ready()
    yield Wait(lambda: a.online and b.online, "双方就绪，对局开始")
    TRACE["after_start"] = {
        "a_seat": a.my_seat, "a_online": a.online, "a_red": a.red_seat,
        "b_seat": b.my_seat, "b_online": b.online,
    }

    # 让红方想 3.6 秒：4 秒保留时间即将用尽，画面会切到"读秒"
    yield Sleep(4.6)
    yield Wait(lambda: True, "拍照：读秒")

    for index, (src, dst) in enumerate(OPENING, start=1):
        mover = a if a._my_turn() else b  # noqa: SLF001
        assert mover.client is not None
        mover.client.move(src, dst)
        yield Wait(
            lambda: len(a.game.entries) >= index and len(b.game.entries) >= index,
            f"第 {index} 手同步到两端",
        )

    yield Wait(lambda: True, "拍照：中局")

    # 拔线：B 断开，A 应看到对手掉线且时钟暂停
    cb.socket.close()
    yield Wait(lambda: a.game.turn is not None and a.clock_bar._snapshot.get("paused"), "A 看到时钟暂停")  # noqa: SLF001
    yield Wait(lambda: True, "拍照：对手掉线")

    # 自动重连（客户端内部定时器）
    yield Wait(lambda: cb.connected and not a.clock_bar._snapshot.get("paused"), "B 自动重连、时钟恢复", 30.0)  # noqa: SLF001
    yield Wait(lambda: True, "拍照：重连后")

    ca.resign()
    yield Wait(lambda: a.game.is_over and b.game.is_over, "认输后两端都结束")
    yield Wait(lambda: True, "拍照：终局")

    return {
        "room_code": code,
        "record_a": a._record_lines,  # noqa: SLF001
        "record_b": b._record_lines,  # noqa: SLF001
        "records_match": a._record_lines == b._record_lines,  # noqa: SLF001
        "a_seat": a.my_seat,
        "b_seat": b.my_seat,
        "a_color": a._my_color().label if a._my_color() is not None else None,  # noqa: SLF001
        "b_color": b._my_color().label if b._my_color() is not None else None,  # noqa: SLF001
        "game_over_text": a.info_label.text(),
        "clock_paused_after_drop": True,
        "reconnected": cb.connected,
    }


def main() -> int:
    SHOTS.mkdir(parents=True, exist_ok=True)
    loop, state = start_server_thread(SERVER_CONFIG)
    port = state["port"]
    url = f"ws://127.0.0.1:{port}/ws"

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
    a.view.animate_moves = False
    b.view.animate_moves = False

    status_log: list[str] = []
    for window in (a, b):
        if window.client is not None:
            window.client.statusChanged.connect(lambda msg: status_log.append(msg))

    script = scenario(a, b, "127.0.0.1", port)
    outcome: dict = {"status": "running"}
    box: dict = {"pending": None}

    def grab(window: MainWindow, name: str) -> None:
        window.grab().save(str(SHOTS / f"{name}.png"))

    # 拍照时机插在 Wait("拍照：…") 完成的瞬间
    shots = [
        ("拍照：读秒", "01-byoyomi", a),
        ("拍照：中局", "02-midgame", a),
        ("拍照：对手掉线", "03-opponent-offline", a),
        ("拍照：重连后", "04-reconnected", a),
        ("拍照：终局", "05-gameover", a),
    ]

    timer = QTimer()

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
            if isinstance(current, Sleep):
                if time.monotonic() < current.until:
                    return
                box["pending"] = script.send(None)
                return
            if isinstance(current, Wait):
                value = current.predicate()
                if not value and time.monotonic() > current.deadline:
                    finish("timeout", message=f"等待超时：{current.label}")
                    return
                if value:
                    for label, name, window in shots:
                        if label == current.label:
                            grab(window, name)
                    box["pending"] = script.send(value)
        except StopIteration as stop:
            finish("done", payload=stop.value)
        except Exception as exc:  # noqa: BLE001
            finish("error", message=f"{type(exc).__name__}: {exc}")

    timer.timeout.connect(step)
    timer.setInterval(30)
    timer.start()
    QTimer.singleShot(0, step)
    app.exec()

    for window in (a, b):
        try:
            if window.client is not None:
                window.client.close()
        except Exception:  # noqa: BLE001
            pass
    asyncio.run_coroutine_threadsafe(state["runner"].cleanup(), loop).result(timeout=10)

    if outcome["status"] != "done":
        print("RESULT: FAIL", outcome["status"], outcome.get("message", ""))
        print("trace:", TRACE)
        print("status log:", status_log[-12:])
        print("cb.connected:", b.client.connected, "room:", b.client.room_code, "token:", bool(b.client.token))
        return 1

    report = outcome["payload"]
    report["server_port"] = port
    report["clock_config"] = SERVER_CONFIG.as_payload()
    out = ROOT / "docs" / "m2" / "report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    ok = report["records_match"] and report["reconnected"] and "胜" in report["game_over_text"]
    print(f"report -> {out}")
    print("records match:", report["records_match"])
    print("reconnected:", report["reconnected"])
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
