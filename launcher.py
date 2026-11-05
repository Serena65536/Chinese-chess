"""打包入口：PyInstaller 从这里进来。

- 正常启动：``python launcher.py``（开发期）或双击 exe（发布期）
- 自检模式：``一起来下棋.exe --selftest``，离屏渲染一帧后退出，用来验证打包产物能跑

注意：发布版是窗口程序（console=False），此时 ``sys.stdout`` 可能为 None，
所有诊断信息一律写文件，别用 print——否则会抛异常并弹出一个没人会去点的对话框。
"""

from __future__ import annotations

import os
import sys
import traceback


def _log_dir() -> str:
    base = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__))
    return base


def _write_log(name: str, text: str) -> str:
    target = os.path.join(_log_dir(), name)
    try:
        with open(target, "w", encoding="utf-8") as handle:
            handle.write(text)
    except OSError:
        pass
    return target


def _say(message: str) -> None:
    """有控制台就打印，没有就只写日志（由调用方负责落盘）。"""
    stream = getattr(sys, "stdout", None)
    if stream is None:
        return
    try:
        print(message)
    except (OSError, ValueError, AttributeError):
        pass


def selftest() -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    lines: list[str] = []
    try:
        from PySide6.QtWidgets import QApplication

        from client import logging_setup
        from client.app import MainWindow
        from client.fonts import ensure_fonts

        logging_setup.configure("client")

        app = QApplication([])
        ensure_fonts()
        window = MainWindow()
        window.resize(700, 800)
        window.show()
        app.processEvents()
        window.view.fit()
        app.processEvents()

        target = os.path.join(_log_dir(), "selftest.png")
        ok = bool(window.grab().save(target))
        lines.append(f"SELFTEST {'OK' if ok else 'FAIL'} -> {target}")
        lines.append(f"QT platform: {app.platformName()}")
        lines.append(f"frozen: {getattr(sys, 'frozen', False)}")
        code = 0 if ok else 1
    except Exception:  # noqa: BLE001
        lines.append("SELFTEST EXCEPTION")
        lines.append(traceback.format_exc())
        code = 2

    text = "\n".join(lines)
    log_path = _write_log("selftest.log", text)
    _say(text)
    _say(f"log -> {log_path}")
    return code


def net_selftest(address: str) -> int:
    """网络自检：连服务器、建个房间、立刻退出。用来排查"连不上"。"""
    import time

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    lines: list[str] = []
    code = 1
    try:
        from PySide6.QtWidgets import QApplication

        from client import logging_setup
        from client.fonts import ensure_fonts
        from client.net import ChessClient
        from client.server_addr import parse_address

        logging_setup.configure("client")
        parsed = parse_address(address)
        lines.append(f"地址: {parsed.display}")
        lines.append(f"对局: {parsed.ws_url}")
        lines.append(f"头像: {parsed.http_base}")

        app = QApplication([])
        ensure_fonts()
        client = ChessClient()
        started = time.perf_counter()
        client.connect(parsed.display)

        deadline = time.time() + 30
        while time.time() < deadline:
            app.processEvents()
            if client.room_code:
                break
            if client.connected and not getattr(client, "_asked", False):
                client._asked = True  # noqa: SLF001
                client.create_room("自检", None)
            time.sleep(0.02)

        if client.room_code:
            lines.append(f"成功: 连上并建房 {client.room_code}，耗时 {time.perf_counter() - started:.1f}s")
            code = 0
        else:
            err = client.socket.errorString() if client.socket else "未知"
            lines.append(f"失败: 没连上（{err}）")
            lines.append(f"连接状态: {client.socket.state() if client.socket else None}")
        client.close()
    except Exception:  # noqa: BLE001
        lines.append("异常:")
        lines.append(traceback.format_exc())
        code = 2

    text = "\n".join(lines)
    path = _write_log("net-selftest.log", text)
    _say(text)
    _say(f"log -> {path}")
    return code


def main() -> int:
    if "--net-selftest" in sys.argv:
        index = sys.argv.index("--net-selftest")
        target = sys.argv[index + 1] if len(sys.argv) > index + 1 else ""
        return net_selftest(target)

    if "--selftest" in sys.argv:
        return selftest()
    from client.app import main as run_app

    return run_app()


if __name__ == "__main__":
    raise SystemExit(main())
