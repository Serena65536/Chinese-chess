# -*- mode: python ; coding: utf-8 -*-
"""服务端打包配置：只打 aiohttp + 棋规，不带 Qt，所以体积很小。

用法（仓库根目录）：
    .venv\\Scripts\\python.exe -m PyInstaller build\\server.spec --noconfirm --clean
"""

import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(SPEC)))  # noqa: F821

a = Analysis(  # noqa: F821
    [os.path.join(ROOT, "server_launcher.py")],
    pathex=[ROOT],
    binaries=[],
    datas=[],
    hiddenimports=["aiodns", "aiohttp", "multidict", "yarl"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["PySide6", "numpy", "tkinter", "matplotlib", "PIL", "pandas", "scipy", "pytest", "setuptools"],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="一起来下棋-服务端",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)

coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="一起来下棋-服务端",
)
