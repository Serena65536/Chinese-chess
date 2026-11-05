"""字体：确保中文字体可用。

Windows 正常跑界面时 Qt 走 DirectWrite，字体本来就全；
但**离屏渲染**（截图、自检、无头测试）下 `QFontDatabase.families()` 可能是空的，
于是所有中文都变成方框。这里在启动时补一刀：字体表为空就手动挂载系统字体文件。
"""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtGui import QFontDatabase

_loaded = False
CJK_CANDIDATES = ("simkai.ttf", "STKAITI.TTF", "msyh.ttc", "msyhbd.ttc", "simhei.ttf", "simsun.ttc")


def ensure_fonts() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    if QFontDatabase.families():
        return  # 正常有字体，不用管

    font_dir = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    for name in CJK_CANDIDATES:
        candidate = font_dir / name
        if candidate.exists():
            QFontDatabase.addApplicationFont(str(candidate))


def family(preferred: tuple[str, ...] = ("KaiTi", "楷体", "STKaiti", "Microsoft YaHei")) -> str:
    """按优先级挑一个可用字体族，都没有就返回空串（交给 Qt 默认）。"""
    ensure_fonts()
    available = set(QFontDatabase.families())
    return next((name for name in preferred if name in available), "")
