@echo off
REM Double-click me to open the client (local play if not connected to a server).
cd /d "%~dp0"

if exist ".venv\Scripts\pythonw.exe" (
  start "" ".venv\Scripts\pythonw.exe" -m client.app
  exit /b 0
)

if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m client.app
  exit /b 0
)

echo [ERROR] .venv not found next to this script:
echo         %~dp0
echo.
echo Try the packaged build instead:
echo   dist\^<app^>\^<app^>.exe
pause
exit /b 1
