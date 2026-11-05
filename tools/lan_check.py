"""用局域网真实 IP（而不是 127.0.0.1）验证联机链路。

区别很重要：
- 连 127.0.0.1 只证明协议和逻辑对，不证明服务端真的监听在对外网卡上
- 连本机的局域网 IP（192.168.x.x）会走真实的 TCP 栈和对外的监听地址

脚本会：起打包好的服务端 exe → 用局域网 IP 访问健康检查 → 两个 QWebSocket 客户端
建房/进房/准备/走子 → 打印结果，最后关掉服务端。

用法：
    .venv\\Scripts\\python.exe tools\\lan_check.py
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication  # noqa: E402

from client.net import ChessClient  # noqa: E402

PORT = 8813
SERVER_EXE = ROOT / "dist" / "一起来下棋-服务端" / "一起来下棋-服务端.exe"


def lan_ip() -> str:
    """拿到本机局域网地址（UDP connect 不会真的发包）。"""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("8.8.8.8", 80))
        return probe.getsockname()[0]
    finally:
        probe.close()


def wait_until(app: QApplication, predicate, timeout: float = 15.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.02)
    return False


def main() -> int:
    if not SERVER_EXE.exists():
        print(f"[错误] 找不到服务端 exe：{SERVER_EXE}")
        return 1

    ip = lan_ip()
    print("=" * 58)
    print(f"局域网地址: {ip}:{PORT}")
    print(f"服务端: {SERVER_EXE.name}")
    print("=" * 58)

    process = subprocess.Popen(
        [str(SERVER_EXE), "--port", str(PORT)],
        cwd=str(SERVER_EXE.parent),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    ok = False
    try:
        # 1) 健康检查走局域网 IP，证明服务端真的监听在对外网卡
        healthy = False
        deadline = time.time() + 25
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(f"http://{ip}:{PORT}/", timeout=2) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                healthy = bool(payload.get("ok"))
                break
            except Exception:  # noqa: BLE001
                time.sleep(0.4)
        print(f"1) 通过 {ip} 访问健康检查: {'成功' if healthy else '失败'}")
        if not healthy:
            return 1

        app = QApplication(sys.argv)
        a, b = ChessClient(), ChessClient()
        events: list[str] = []
        a.statusChanged.connect(lambda m: events.append(f"A:{m}"))
        b.statusChanged.connect(lambda m: events.append(f"B:{m}"))

        a.connect_to(ip, PORT)
        b.connect_to(ip, PORT)
        if not wait_until(app, lambda: a.connected and b.connected, 12):
            print("2) 两个客户端连不上服务端")
            print("   状态记录:", events[-6:])
            for name, client in (("A", a), ("B", b)):
                print(f"   {name}: connected={client.connected} url={client._url} "  # noqa: SLF001
                      f"err={client.socket.errorString() if client.socket else None}")
            return 1
        print(f"2) 两个客户端连上 ws://{ip}:{PORT}/ws")

        a.create_room("红方")
        if not wait_until(app, lambda: a.room_code is not None, 10):
            print("3) 建房失败")
            return 1
        code = a.room_code
        print(f"3) 建房成功，房间码 {code}")

        b.join_room(str(code), "黑方")
        if not wait_until(app, lambda: b.room_code == code, 10):
            print("4) 加入房间失败")
            return 1
        print("4) 对手加入成功")

        states: dict = {}
        a.gameStarted.connect(lambda d: states.setdefault("start", d))
        a.moveApplied.connect(lambda d: states.setdefault("move", d))
        a.ready()
        b.ready()
        if not wait_until(app, lambda: "start" in states, 10):
            print("5) 没能开局")
            return 1
        print(f"5) 开局：红方座位 {states['start']['redSeat']}，FEN {states['start']['fen'][:20]}…")

        a.move((1, 7), (4, 7))  # 炮二平五
        if not wait_until(app, lambda: "move" in states, 10):
            print("6) 走子没有广播回来")
            return 1
        move = states["move"]
        print(f"6) 走子广播成功：seq={move['seq']} 记谱={move.get('record')}")

        a.close()
        b.close()
        ok = True
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()

    print("=" * 58)
    print("结论:", "通过——服务端在局域网地址上可被两个客户端访问" if ok else "失败")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
