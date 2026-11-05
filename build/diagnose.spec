# -*- mode: python ; coding: utf-8 -*-
"""诊断用：console 版本，能看到卡在哪一步（正式发布用「一起来下棋.spec」）。"""

import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(SPEC)))  # noqa: F821

EXCLUDES = [
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtWebChannel",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuickWidgets",
    "PySide6.QtQuick3D",
    "PySide6.QtQuickControls2",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DRender",
    "PySide6.Qt3DInput",
    "PySide6.Qt3DLogic",
    "PySide6.Qt3DAnimation",
    "PySide6.Qt3DExtras",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtGraphs",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtDesigner",
    "PySide6.QtTest",
    "PySide6.QtSql",
    "PySide6.QtBluetooth",
    "PySide6.QtPositioning",
    "PySide6.QtSerialPort",
    "PySide6.QtHelp",
    "PySide6.QtUiTools",
    "PySide6.QtSpatialAudio",
    "PySide6.QtHttpServer",
    "numpy",
    "tkinter",
    "matplotlib",
    "PIL",
    "pandas",
    "scipy",
    "IPython",
    "pytest",
    "setuptools",
]

a = Analysis(  # noqa: F821
    [os.path.join(ROOT, "launcher.py")],
    pathex=[ROOT],
    excludes=EXCLUDES,
    hiddenimports=[
        "PySide6.QtMultimedia",
        "PySide6.QtWebSockets",
        "PySide6.QtSvg",
        "PySide6.QtNetwork",
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="一起来下棋-console",
    debug=False,
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
    name="一起来下棋-console",
)
