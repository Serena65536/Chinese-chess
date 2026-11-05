@echo off
setlocal
chcp 936 >nul
cd /d "%~dp0"
title 一起来下棋 - 临时公网联机

echo ============================================
echo   一起来下棋  临时公网联机（Cloudflare 隧道）
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

if not exist "一起来下棋-服务端.exe" (
  echo [错误] 没找到 一起来下棋-服务端.exe，请确认压缩包解压完整。
  pause
  exit /b 1
)

echo 启动服务端...
start "服务端" /min "一起来下棋-服务端.exe" --port 8765 --host 127.0.0.1
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
