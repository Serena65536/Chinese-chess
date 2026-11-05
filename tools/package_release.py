"""发布打包：把客户端、服务端、安装/卸载脚本 + 说明打成一个压缩包。

为什么要自己写安装脚本：这台机器上没有 NSIS / Inno Setup，只有 7-Zip，
而 7-Zip 自带的 SFX 不支持"解压后执行安装脚本"。所以做成"自带安装脚本的压缩包"：
解压 → 双击 `安装.cmd` → 复制到 %LOCALAPPDATA%\\Programs\\一起来下棋 + 建快捷方式，
效果和安装程序一样，而且用户能看见脚本在做什么。

用法：
    .venv\\Scripts\\python.exe tools\\package_release.py
"""

from __future__ import annotations

import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from client.version import __app_name__, __version__  # noqa: E402

CLIENT_DIR = ROOT / "dist" / __app_name__
SERVER_DIR = ROOT / "dist" / f"{__app_name__}-服务端"
RELEASE = ROOT / "release"
STAGE = RELEASE / f"{__app_name__}-{__version__}"

INSTALLER = r"""@echo off
setlocal
chcp 936 >nul
set "SRC=%~dp0"
set "DEST=%LOCALAPPDATA%\Programs\%APPNAME%"

echo ============================================
echo   %APPNAME% v%VERSION%  安装
echo ============================================
echo   安装到: %DEST%
echo.

if not exist "%SRC%\客户端\%APPNAME%.exe" (
  echo [错误] 没找到 客户端\%APPNAME%.exe
  echo        请先把压缩包完整解压，再运行本脚本。
  pause
  exit /b 1
)

set "SILENT=0"
if /i "%~1"=="/silent" set "SILENT=1"

if exist "%DEST%" (
  if "%SILENT%"=="0" (
    echo 检测到已安装，将覆盖更新（设置和头像不会丢）。
    choice /c YN /m "继续?"
    if errorlevel 2 exit /b 0
  )
)

echo 正在复制文件（约 150MB，稍等）...
robocopy "%SRC%客户端" "%DEST%\客户端" /e /nfl /ndl /njh /njs >nul
robocopy "%SRC%服务端" "%DEST%\服务端" /e /nfl /ndl /njh /njs >nul
if errorlevel 8 goto fail

copy /y "%SRC%\卸载.cmd" "%DEST%\卸载.cmd" >nul
copy /y "%SRC%\使用说明.txt" "%DEST%\使用说明.txt" >nul

echo 正在创建快捷方式...
powershell -NoProfile -ExecutionPolicy Bypass -File "%SRC%\make_shortcuts.ps1" -Target "%DEST%" -Name "%APPNAME%"
if errorlevel 1 echo [提示] 快捷方式创建失败，可以直接运行 %DEST%\客户端\%APPNAME%.exe

echo.
echo 安装完成！
echo   客户端: %DEST%\客户端\%APPNAME%.exe
echo   服务端: %DEST%\服务端\%APPNAME%-服务端.exe
echo   卸载:   %DEST%\卸载.cmd
echo.
if "%SILENT%"=="1" goto done
choice /c YN /m "现在打开客户端?"
if errorlevel 2 goto done
start "" "%DEST%\客户端\%APPNAME%.exe"
:done
if "%SILENT%"=="1" exit /b 0
echo.
pause
exit /b 0

:fail
echo.
echo [错误] 文件复制失败。可能原因：目标目录被占用，或没有写权限。
echo        先关掉正在运行的程序，再重试。
if "%SILENT%"=="1" exit /b 1
pause
exit /b 1
"""

UNINSTALLER = r"""@echo off
setlocal
chcp 936 >nul
set "DEST=%LOCALAPPDATA%\Programs\%APPNAME%"

echo ============================================
echo   %APPNAME%  卸载
echo ============================================
echo   程序目录: %DEST%
echo.
set "SILENT=0"
if /i "%~1"=="/silent" set "SILENT=1"
if "%SILENT%"=="0" (
  choice /c YN /m "确认卸载?"
  if errorlevel 2 exit /b 0
)

echo 正在删除快捷方式...
powershell -NoProfile -Command ^
  "$d=[Environment]::GetFolderPath('Desktop'); $s=[Environment]::GetFolderPath('Programs');" ^
  "Get-ChildItem -Path $d,$s -Filter '%APPNAME%*.lnk' -Recurse -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue;" ^
  "Remove-Item -Recurse -Force -ErrorAction SilentlyContinue (Join-Path $s '%APPNAME%')"

if "%SILENT%"=="1" goto keepcfg
choice /c YN /m "是否同时删除设置与头像（%APPDATA%\%APPNAME%）?"
if errorlevel 2 goto keepcfg
rmdir /s /q "%APPDATA%\%APPNAME%" 2>nul
:keepcfg

echo 正在删除程序文件...
set "TMPBAT=%TEMP%\yqlxq-uninstall-%RANDOM%.cmd"
> "%TMPBAT%" echo @echo off
>> "%TMPBAT%" echo timeout /t 2 /nobreak ^>nul
>> "%TMPBAT%" echo rmdir /s /q "%DEST%"
>> "%TMPBAT%" echo del "%%~f0" ^>nul
start "" /min cmd /c "%TMPBAT%"

echo.
if "%SILENT%"=="1" exit /b 0
echo 已卸载。窗口会在几秒后自动关闭。
timeout /t 3 /nobreak >nul
"""

SHORTCUTS_PS1 = r"""param(
    [Parameter(Mandatory = $true)][string]$Target,
    [string]$Name = "一起来下棋"
)

$Wsh = New-Object -ComObject WScript.Shell
$desktop = [Environment]::GetFolderPath("Desktop")
$programs = [Environment]::GetFolderPath("Programs")
$startMenu = Join-Path $programs $Name
$failed = @()

function New-Lnk {
    param([string]$Path, [string]$Exe, [string]$WorkDir, [string]$Desc, [string]$Label)
    try {
        $sc = $Wsh.CreateShortcut($Path)
        $sc.TargetPath = $Exe
        $sc.WorkingDirectory = $WorkDir
        $sc.Description = $Desc
        $sc.Save()
    } catch {
        $script:failed += $Label
    }
}

$clientExe = Join-Path $Target ("客户端\" + $Name + ".exe")
$serverExe = Join-Path $Target ("服务端\" + $Name + "-服务端.exe")
$clientDir = Join-Path $Target "客户端"
$serverDir = Join-Path $Target "服务端"

New-Lnk (Join-Path $desktop "$Name.lnk") $clientExe $clientDir "一起来下棋" "桌面-客户端"
New-Lnk (Join-Path $desktop "$Name-服务端.lnk") $serverExe $serverDir "联机服务端" "桌面-服务端"

try {
    New-Item -ItemType Directory -Force -Path $startMenu -ErrorAction Stop | Out-Null
    New-Lnk (Join-Path $startMenu "$Name.lnk") $clientExe $clientDir "一起来下棋" "开始菜单-客户端"
    New-Lnk (Join-Path $startMenu "$Name-服务端.lnk") $serverExe $serverDir "联机服务端" "开始菜单-服务端"
} catch {
    $failed += "开始菜单目录"
}

if ($failed.Count -gt 0) {
    Write-Host ("[提示] 这些快捷方式没能创建: " + ($failed -join "、"))
    Write-Host "       可以直接运行程序目录里的 exe。"
    exit 1
}
Write-Host "快捷方式已创建：桌面 + 开始菜单"
"""

TUNNEL_CMD = r"""@echo off
setlocal
chcp 936 >nul
cd /d "%~dp0"
title %APPNAME% - 临时公网联机

echo ============================================
echo   %APPNAME%  临时公网联机（Cloudflare 隧道）
echo ============================================
echo.
echo 这个脚本会做两件事：
echo   1. 在本机启动服务端（只监听 127.0.0.1）
echo   2. 通过 Cloudflare 申请一个临时公网地址
echo.
echo 拿到 https://xxxx.trycloudflare.com 这样的地址后，
echo 把它填到客户端：菜单 联机 - 服务器地址（或用 设置 里的服务器地址）。
echo.

set "CF=%~dp0cloudflared.exe"
if not exist "%CF%" (
  echo 没找到 cloudflared.exe，尝试自动下载（约 50MB，只需一次）...
  powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "Invoke-WebRequest -Uri 'https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe' -OutFile '%CF%' -UseBasicParsing"
  if not exist "%CF%" (
    echo.
    echo [失败] 自动下载没成功。请手动下载：
    echo   https://github.com/cloudflare/cloudflared/releases/latest
    echo   选 cloudflared-windows-amd64.exe，改名 cloudflared.exe 放到本目录。
    pause
    exit /b 1
  )
  echo 下载完成。
)

if not exist "%APPNAME%-服务端.exe" (
  echo [错误] 没找到 %APPNAME%-服务端.exe，请确认压缩包解压完整。
  pause
  exit /b 1
)

echo 启动服务端...
start "服务端" /min "%APPNAME%-服务端.exe" --port 8765 --host 127.0.0.1
timeout /t 3 /nobreak >nul

echo.
echo ------------------------------------------------------------
echo 下面这段里找 https://xxxx.trycloudflare.com
echo 把它发给朋友，或在客户端把自己也连上去：
echo ------------------------------------------------------------
echo.

"%CF%" tunnel --url http://127.0.0.1:8765 --no-autoupdate

echo.
echo 隧道已断开（服务端窗口可能还开着，可以手动关掉）。
pause
"""

README = """一起来下棋 v{version}
==================================================

这是什么
  电脑端中国象棋，两个人远程对战。没有电脑对手。

安装（1 分钟）
  1. 把本压缩包完整解压到任意位置（不要在压缩包里直接运行）
  2. 双击 安装.cmd
  3. 桌面上会出现两个图标：
       一起来下棋          客户端
       一起来下棋-服务端    联机用的服务端

怎么下
  只自己练手：直接打开客户端，点棋子就能走，红黑轮流。

  和朋友联机：
  1. 其中一台机器（或一台云主机）双击「一起来下棋-服务端」，
     窗口里会显示局域网地址，例如 192.168.1.20:8765
  2. 两台机器都打开客户端，菜单「联机 → 服务器地址…」填这个地址
  3. 一方点「创建房间」拿到 6 位房间码，另一方点「加入房间」输码
  4. 双方点「准备」，开始下棋
  首次开服务端时 Windows 可能弹防火墙提示，要选「允许」。

  不在同一个局域网怎么办（异地联机）
    服务端文件夹里有个「启动临时公网联机.cmd」：
    双击它 → 它会自动下载 cloudflared（首次约 50MB）并申请一个
    https://xxx.trycloudflare.com 地址 → 把这个地址填到客户端「服务器地址」。
    注意：每次重启脚本地址都会变；隧道期间别关窗口。

自定义
  菜单「设置…」（Ctrl+,）：头像、昵称、服务器地址、背景图、音乐/音效音量。
  头像会同步给对手看；背景图和音乐只在本机生效。

出问题了
  菜单「帮助 → 打开日志目录」，把 client.log 发过来就能定位。
  服务端日志在 服务端\\server_data\\logs\\server.log。

卸载
  开始菜单里运行「一起来下棋」目录下的卸载，或直接运行安装目录里的 卸载.cmd。
  卸载时会问你要不要连设置和头像一起删。
"""


def write_text(path: Path, text: str, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding=encoding)


def main() -> int:
    for required in (CLIENT_DIR, SERVER_DIR):
        if not required.exists():
            print(f"[错误] 找不到 {required}，先跑 PyInstaller 打包客户端和服务端。")
            return 1

    if STAGE.exists():
        shutil.rmtree(STAGE)
    STAGE.mkdir(parents=True)

    # 自检产物和日志不能进发布包
    junk = shutil.ignore_patterns("selftest.*", "*.log", "server_data", "cloudflared.exe")
    print("复制客户端…")
    shutil.copytree(CLIENT_DIR, STAGE / "客户端", ignore=junk)
    print("复制服务端…")
    shutil.copytree(SERVER_DIR, STAGE / "服务端", ignore=junk)

    # 安装脚本用 GBK：中文 Windows 的 cmd 默认 936，UTF-8 会显示乱码
    installer = INSTALLER.replace("%APPNAME%", __app_name__).replace("%VERSION%", __version__)
    write_text(STAGE / "安装.cmd", installer, encoding="gbk")
    write_text(STAGE / "卸载.cmd", UNINSTALLER.replace("%APPNAME%", __app_name__), encoding="gbk")
    write_text(
        STAGE / "服务端" / "启动临时公网联机.cmd",
        TUNNEL_CMD.replace("%APPNAME%", __app_name__),
        encoding="gbk",
    )
    write_text(STAGE / "make_shortcuts.ps1", SHORTCUTS_PS1, encoding="utf-8-sig")
    write_text(STAGE / "使用说明.txt", README.replace("{version}", __version__), encoding="utf-8-sig")

    archive = RELEASE / f"{__app_name__}-{__version__}-安装包.zip"
    print("压缩…")
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        for path in sorted(STAGE.rglob("*")):
            if path.is_file():
                bundle.write(path, path.relative_to(STAGE.parent))

    size_mb = archive.stat().st_size / 1024 / 1024
    print()
    print(f"目录  {STAGE}")
    print(f"压缩包 {archive}  ({size_mb:.1f} MB)")
    print(f"客户端 {sum(1 for _ in (STAGE / '客户端').rglob('*') if _.is_file())} 个文件")
    print(f"服务端 {sum(1 for _ in (STAGE / '服务端').rglob('*') if _.is_file())} 个文件")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
