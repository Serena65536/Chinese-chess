@echo off
setlocal
chcp 936 >nul
set "DEST=%LOCALAPPDATA%\Programs\一起来下棋"

echo ============================================
echo   一起来下棋  卸载
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
  "Get-ChildItem -Path $d,$s -Filter '一起来下棋*.lnk' -Recurse -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue;" ^
  "Remove-Item -Recurse -Force -ErrorAction SilentlyContinue (Join-Path $s '一起来下棋')"

if "%SILENT%"=="1" goto keepcfg
choice /c YN /m "是否同时删除设置与头像（%APPDATA%\一起来下棋）?"
if errorlevel 2 goto keepcfg
rmdir /s /q "%APPDATA%\一起来下棋" 2>nul
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
