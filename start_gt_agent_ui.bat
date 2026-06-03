@echo off
setlocal

cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo Python was not found in PATH.
  pause
  exit /b 1
)

start "" http://127.0.0.1:8765
python -m gt_agent.web_app --host 127.0.0.1 --port 8765

if errorlevel 1 (
  echo.
  echo GT Agent UI stopped with an error.
  pause
)
