"""服务端打包入口：一起来下棋-服务端.exe 从这里启动。

和服务端逻辑分开，是为了让打包配置只关心"启动"这一件事：
- 把工作目录切到 exe 所在目录，这样 server_data（头像、日志）落在 exe 边上，
  而不是落在用户双击时的当前目录
- 日志同时写文件和控制台，方便别人让你远程看现场
"""

from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def main() -> int:
    base = app_dir()
    os.chdir(base)  # 让默认的 data-dir 落在 exe 旁边
    sys.path.insert(0, str(base))

    try:
        from server.main import main as server_main

        return server_main()
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001
        text = traceback.format_exc()
        try:
            (base / "server_crash.log").write_text(text, encoding="utf-8")
        except OSError:
            pass
        print("服务端启动失败，详情：")
        print(text)
        input("按回车关闭…")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
