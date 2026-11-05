"""spike ④：两个客户端经 QWebSocket 互发一步棋。

跑法：
    .venv\\Scripts\\python.exe tools\\spike_net.py

流程：本进程另起一个线程跑 aiohttp 服务端（端口 0 自动分配）→ 两个 QWebSocket
客户端连上 → A 建房拿 6 位码 → B 输码进房 → 双方各走一步 → 校验 seq 递增 →
再验证第三个客户端进不来 → 最后验 ping/pong。

这里刻意用 QWebSocket 而不是 aiohttp 的客户端：正式客户端就是用它，得在这里把
"Qt 事件循环 + Qt WebSocket + aiohttp 服务端"这条链路先证明能跑通。
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

from aiohttp import web  # noqa: E402
from PySide6.QtCore import QTimer, QUrl  # noqa: E402
from PySide6.QtWebSockets import QWebSocket  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from server.main import create_app  # noqa: E402


class Client:
    def __init__(self, name: str) -> None:
        self.name = name
        self.inbox: list[dict] = []
        self.connected = False
        self.socket = QWebSocket()
        self.socket.textMessageReceived.connect(self._on_text)
        self.socket.connected.connect(self._on_connected)

    def _on_text(self, text: str) -> None:
        try:
            self.inbox.append(json.loads(text))
        except json.JSONDecodeError:
            self.inbox.append({"type": "__broken__", "raw": text})

    def _on_connected(self) -> None:
        self.connected = True

    def connect(self, url: str) -> None:
        self.socket.open(QUrl(url))

    def send(self, kind: str, data: dict | None = None) -> None:
        self.socket.sendTextMessage(json.dumps({"type": kind, "data": data or {}}, ensure_ascii=False))

    def close(self) -> None:
        self.socket.close()

    def pop(self, kind: str) -> dict | None:
        for index, message in enumerate(self.inbox):
            if message.get("type") == kind:
                return self.inbox.pop(index)
        return None


class Wait:
    def __init__(self, predicate: Callable[[], object], label: str, timeout: float = 6.0) -> None:
        self.predicate = predicate
        self.label = label
        self.deadline = time.monotonic() + timeout


def start_server_thread() -> tuple[asyncio.AbstractEventLoop, dict]:
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()

    state: dict = {}
    ready = threading.Event()

    async def boot() -> None:
        app = create_app()
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        state["runner"] = runner
        state["port"] = site._server.sockets[0].getsockname()[1]  # noqa: SLF001
        ready.set()

    asyncio.run_coroutine_threadsafe(boot(), loop).result(timeout=10)
    if not ready.wait(10):
        raise RuntimeError("服务端启动超时")
    return loop, state


def scenario(a: Client, b: Client, c: Client, url: str):
    """生成器式脚本：先发起动作，再 yield 一个等待条件。"""
    a.connect(url)
    b.connect(url)
    yield Wait(lambda: a.connected and b.connected, "两个客户端建立连接")

    a.send("create_room", {"name": "红方"})
    created = yield Wait(lambda: a.pop("room_created"), "A 拿到房间码")
    code = created["data"]["code"]

    b.send("join_room", {"code": code, "name": "黑方"})
    yield Wait(lambda: b.pop("room_joined"), "B 加入房间")
    yield Wait(lambda: a.pop("room_state"), "A 收到房间状态")

    a.send("move", {"from": [1, 7], "to": [4, 7]})
    move1 = yield Wait(lambda: b.pop("move_applied"), "B 收到 A 的走子")
    echo1 = yield Wait(lambda: a.pop("move_applied"), "A 收到自己的权威回执")

    b.send("move", {"from": [7, 0], "to": [4, 0]})
    move2 = yield Wait(lambda: a.pop("move_applied"), "A 收到 B 的走子")

    c.connect(url)
    yield Wait(lambda: c.connected, "第三位客户端连上")
    c.send("join_room", {"code": code, "name": "路人"})
    rejected = yield Wait(lambda: c.pop("error"), "第三位客户端被拒")

    a.send("ping", {"t": 12345})
    pong = yield Wait(lambda: a.pop("pong"), "ping/pong")

    yield Wait(lambda: True, "收尾")

    report = {
        "room_code": code,
        "A_move_to_B": move1["data"],
        "A_own_echo": echo1["data"],
        "B_move_to_A": move2["data"],
        "seq_increases": move2["data"]["seq"] == move1["data"]["seq"] + 1,
        "sender_gets_echo": echo1["data"]["seq"] == move1["data"]["seq"],
        "third_client_rejected": rejected.get("message"),
        "pong": pong["data"],
        "room_moves": 2,
    }
    return report


def main() -> int:
    loop, state = start_server_thread()
    url = f"ws://127.0.0.1:{state['port']}/ws"

    app = QApplication(sys.argv)
    clients = {name: Client(name) for name in ("A", "B", "C")}
    script = scenario(clients["A"], clients["B"], clients["C"], url)
    outcome: dict = {"status": "running", "started": time.perf_counter()}
    pending_box: dict = {"value": None}

    timer = QTimer()

    def finish(status: str, payload: object = None, message: str = "") -> None:
        outcome["status"] = status
        outcome["payload"] = payload
        outcome["message"] = message
        timer.stop()
        app.quit()

    def step() -> None:
        try:
            current = pending_box["value"]
            if current is None:
                pending_box["value"] = next(script)
                return
            if isinstance(current, Wait):
                value = current.predicate()
                if value:
                    pending_box["value"] = script.send(value)
                    return
                if time.monotonic() > current.deadline:
                    finish("timeout", message=f"等待超时：{current.label}")
        except StopIteration as stop:
            finish("done", payload=stop.value)
        except Exception as exc:  # noqa: BLE001
            finish("error", message=f"{type(exc).__name__}: {exc}")

    timer.timeout.connect(step)
    timer.setInterval(20)
    timer.start()
    QTimer.singleShot(0, step)
    app.exec()

    for client in clients.values():
        client.close()
    asyncio.run_coroutine_threadsafe(state["runner"].cleanup(), loop).result(timeout=10)

    if outcome["status"] != "done":
        print("RESULT: FAIL", outcome.get("status"), outcome.get("message", ""))
        return 1

    report = outcome["payload"]
    report["server_port"] = state["port"]
    print(json.dumps(report, ensure_ascii=False, indent=2))
    ok = report["seq_increases"] and bool(report["third_client_rejected"]) and report["pong"] == {"t": 12345}
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
