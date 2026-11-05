@echo off
setlocal
chcp 936 >nul
set "SRC=%~dp0"
set "DEST=%LOCALAPPDATA%\Programs\一起来下棋"

echo ============================================
echo   一起来下棋 v1.4.0  安装
echo ============================================
echo   安装到: %DEST%
echo.

if not exist "%SRC%\客户端\一起来下棋.exe" (
  echo [错误] 没找到 客户端\一起来下棋.exe
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
powershell -NoProfile -ExecutionPolicy Bypass -File "%SRC%\make_shortcuts.ps1" -Target "%DEST%" -Name "一起来下棋"
if errorlevel 1 echo [提示] 快捷方式创建失败，可以直接运行 %DEST%\客户端\一起来下棋.exe

echo.
echo 安装完成！
echo   客户端: %DEST%\客户端\一起来下棋.exe
echo   服务端: %DEST%\服务端\一起来下棋-服务端.exe
echo   卸载:   %DEST%\卸载.cmd
echo.
if "%SILENT%"=="1" goto done
choice /c YN /m "现在打开客户端?"
if errorlevel 2 goto done
start "" "%DEST%\客户端\一起来下棋.exe"
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
