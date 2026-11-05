"""发布前自检：把"能不能装、能不能跑、能不能联机"用脚本过一遍。

跑法：
    .venv\\Scripts\\python.exe tools\\release_check.py

检查项：
  1. 发布目录/压缩包是否齐全、体积是否合理
  2. 客户端 exe 能否自检通过（离屏渲染一帧）
  3. 服务端 exe 能否起来并响应 / 健康检查
  4. 安装脚本 / 卸载脚本是否随包带上，且能语法级执行（/silent 安装到临时目录）
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from client.version import __app_name__, __version__  # noqa: E402

STAGE = ROOT / "release" / f"{__app_name__}-{__version__}"
ARCHIVE = ROOT / "release" / f"{__app_name__}-{__version__}-安装包.zip"
CLIENT_EXE = STAGE / "客户端" / f"{__app_name__}.exe"
SERVER_EXE = STAGE / "服务端" / f"{__app_name__}-服务端.exe"

_results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    _results.append((name, ok, detail))
    mark = "[OK]  " if ok else "[FAIL]"
    print(f"  {mark} {name}" + (f"  {detail}" if detail else ""))


def check_client() -> None:
    log = CLIENT_EXE.parent / "selftest.log"
    log.unlink(missing_ok=True)
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    started = time.perf_counter()
    try:
        proc = subprocess.run([str(CLIENT_EXE), "--selftest"], env=env, timeout=120, capture_output=True)
        elapsed = time.perf_counter() - started
        text = log.read_text(encoding="utf-8") if log.exists() else proc.stdout.decode("utf-8", "ignore")
        check("客户端自检", "SELFTEST OK" in text, f"{elapsed:.1f}s，退出码 {proc.returncode}")
    except subprocess.TimeoutExpired:
        check("客户端自检", False, "超时（120s）")
    finally:
        log.unlink(missing_ok=True)
        (CLIENT_EXE.parent / "selftest.png").unlink(missing_ok=True)


def check_server(port: int = 8811) -> None:
    env = dict(os.environ)
    started = time.perf_counter()
    proc = subprocess.Popen(
        [str(SERVER_EXE), "--port", str(port)],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    ok = False
    detail = ""
    try:
        deadline = time.time() + 25
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                if payload.get("ok"):
                    ok = True
                    detail = f"{time.perf_counter() - started:.1f}s 起来，协议 v{payload.get('protocol')}"
                break
            except Exception:  # noqa: BLE001
                time.sleep(0.4)
        if not ok and not detail:
            detail = "25 秒内没起来"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
    check("服务端启动 + 健康检查", ok, detail)
    data = SERVER_EXE.parent / "server_data"
    check("服务端数据目录落在 exe 边上", data.exists(), str(data.name))
    shutil.rmtree(data, ignore_errors=True)


def check_installer() -> None:
    installer = STAGE / "安装.cmd"
    uninstaller = STAGE / "卸载.cmd"
    check("安装/卸载脚本齐全", installer.exists() and uninstaller.exists())

    target = Path(tempfile.mkdtemp(prefix="yqlxq-install-"))
    env = dict(os.environ, LOCALAPPDATA=str(target))
    try:
        proc = subprocess.run(
            ["cmd", "/c", str(installer), "/silent"], env=env, timeout=180, capture_output=True
        )
        installed = target / "Programs" / __app_name__
        good = proc.returncode == 0 and (installed / "客户端" / f"{__app_name__}.exe").exists()
        check("静默安装到临时目录", good, str(installed) if good else f"退出码 {proc.returncode}")

        if good:
            un_proc = subprocess.run(
                ["cmd", "/c", str(installed / "卸载.cmd"), "/silent"], env=env, timeout=120, capture_output=True
            )
            for _ in range(20):
                if not installed.exists():
                    break
                time.sleep(0.5)
            check("静默卸载", not installed.exists(), f"退出码 {un_proc.returncode}")
    except subprocess.TimeoutExpired:
        check("静默安装到临时目录", False, "超时")
    finally:
        shutil.rmtree(target, ignore_errors=True)


def main() -> int:
    print("=" * 60)
    print(f"发布自检  {__app_name__} v{__version__}")
    print("=" * 60)

    check("发布目录存在", STAGE.exists())
    check("安装包存在", ARCHIVE.exists(), f"{ARCHIVE.stat().st_size / 1e6:.1f} MB" if ARCHIVE.exists() else "")
    check("客户端 exe", CLIENT_EXE.exists())
    check("服务端 exe", SERVER_EXE.exists())

    if CLIENT_EXE.exists():
        check_client()
    if SERVER_EXE.exists():
        check_server()
    if STAGE.exists():
        check_installer()

    ok = all(passed for _, passed, _ in _results)
    print("-" * 60)
    print(f"{sum(1 for _, ok_, _ in _results if ok_)}/{len(_results)} 项通过")
    print("结论:", "可以发布" if ok else "还有问题，先别发")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
