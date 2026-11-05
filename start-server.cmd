@echo off
REM Double-click me to start the online server (keeps this window open).
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] .venv not found next to this script:
  echo         %~dp0
  echo.
  echo Create it once in that folder:
  echo   python -m venv .venv --system-site-packages
  echo   .venv\Scripts\python.exe -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
  pause
  exit /b 1
)

".venv\Scripts\python.exe" -m server.main --port 8765
echo.
echo Server stopped. Press any key to close.
pause >nul
