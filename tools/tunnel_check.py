"""用 Cloudflare 临时隧道验证公网联机（wss://）。

用法：
    .venv\\Scripts\\python.exe tools\\tunnel_check.py https://xxx.trycloudflare.com

做的事：
  1. 用 https 访问健康检查（证明隧道通到本地服务端）
  2. 两个 QWebSocket 客户端走 wss:// 建房/进房/准备/走子
  3. 顺便量一下每一步的往返延迟（从发送到收到对手广播）
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication  # noqa: E402

from client.net import ChessClient  # noqa: E402
from client.server_addr import parse_address  # noqa: E402


def wait_until(app: QApplication, predicate, timeout: float = 30.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return False


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("用法: python tools/tunnel_check.py https://xxx.trycloudflare.com")
        return 2

    address = argv[1]
    parsed = parse_address(address)
    print("=" * 60)
    print(f"地址      {parsed.display}")
    print(f"对局入口  {parsed.ws_url}")
    print(f"头像入口  {parsed.http_base}")
    print("=" * 60)

    # 1) HTTPS 健康检查
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(f"{parsed.http_base}/", timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
        elapsed = (time.perf_counter() - started) * 1000
        print(f"1) HTTPS 健康检查通过（{elapsed:.0f} ms）：{payload.get('app')} 协议 v{payload.get('protocol')}")
    except Exception as exc:  # noqa: BLE001
        print(f"1) HTTPS 健康检查失败：{type(exc).__name__} {exc}")
        return 1

    app = QApplication(sys.argv[:1])
    a, b = ChessClient(), ChessClient()
    errors: list[str] = []
    a.errorRaised.connect(lambda m: errors.append(f"A:{m}"))
    b.errorRaised.connect(lambda m: errors.append(f"B:{m}"))

    t0 = time.perf_counter()
    a.connect(parsed.display)
    b.connect(parsed.display)
    if not wait_until(app, lambda: a.connected and b.connected, 40):
        print("2) 客户端 wss 连接失败")
        print("   A:", a.socket.errorString() if a.socket else None)
        print("   B:", b.socket.errorString() if b.socket else None)
        return 1
    print(f"2) 两个客户端 wss 连上（{(time.perf_counter() - t0) * 1000:.0f} ms）")

    a.create_room("红方")
    if not wait_until(app, lambda: a.room_code is not None, 20):
        print("3) 建房失败"); return 1
    code = a.room_code
    print(f"3) 房间码 {code}")

    b.join_room(str(code), "黑方")
    if not wait_until(app, lambda: b.room_code == code, 20):
        print("4) 加入失败"); return 1
    print("4) 对手加入")

    state: dict = {}
    a.gameStarted.connect(lambda d: state.setdefault("start", d))
    b.moveApplied.connect(lambda d: state.setdefault("move_b", (d, time.perf_counter())))
    a.ready()
    b.ready()
    if not wait_until(app, lambda: "start" in state, 25):
        print("5) 开局失败"); return 1
    print(f"5) 开局成功，红方座位 {state['start']['redSeat']}")

    sent = time.perf_counter()
    a.move((1, 7), (4, 7))
    if not wait_until(app, lambda: "move_b" in state, 25):
        print("6) 走子没有广播到对手"); return 1
    move, received = state["move_b"]
    print(f"6) 走子到达对手，往返 {1000 * (received - sent):.0f} ms，记谱={move.get('record')}")

    a.close()
    b.close()
    print("=" * 60)
    print("结论: Cloudflare 隧道 + wss 联机链路可用")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
