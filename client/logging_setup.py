"""日志：滚动文件 + 崩溃现场，出问题让用户把文件发过来就行。

- 普通日志：``<配置目录>/logs/client.log``，512KB 滚动，保留 3 份
- 崩溃现场：``client-crash.log``（faulthandler，段错误也能留下栈）
- 未捕获异常：写进普通日志，并尽量弹个框告诉用户日志在哪
"""

from __future__ import annotations

import faulthandler
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

_configured = False
_crash_handle = None


def log_dir() -> Path:
    from . import config as appcfg

    return appcfg.config_dir() / "logs"


def configure(name: str = "client") -> Optional[Path]:
    """初始化日志，返回日志文件路径（失败则返回 None，绝不因此影响启动）。"""
    global _configured, _crash_handle
    if _configured:
        return log_dir() / f"{name}.log"

    try:
        folder = log_dir()
        folder.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None

    path = folder / f"{name}.log"
    try:
        handler = RotatingFileHandler(path, maxBytes=512 * 1024, backupCount=3, encoding="utf-8")
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S")
        )
        root = logging.getLogger()
        root.setLevel(logging.INFO)
        root.addHandler(handler)
    except OSError:
        return None

    # 段错误/硬崩溃也能留下现场
    try:
        _crash_handle = open(folder / f"{name}-crash.log", "a", encoding="utf-8")
        faulthandler.enable(_crash_handle)
    except OSError:
        _crash_handle = None

    _install_excepthook()
    _configured = True
    from .version import __version__

    logging.getLogger("app").info("启动 %s v%s (frozen=%s)", name, __version__, getattr(sys, "frozen", False))
    return path


def _install_excepthook() -> None:
    logger = logging.getLogger("uncaught")

    def hook(exc_type, exc, tb) -> None:  # noqa: ANN001
        logger.error("未捕获异常", exc_info=(exc_type, exc, tb))

    sys.excepthook = hook


def snapshot(reason: str) -> None:
    """主动记一笔，方便在日志里定位操作序列。"""
    logging.getLogger("app").info(reason)
