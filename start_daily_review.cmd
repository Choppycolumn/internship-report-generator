@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo ERROR: Python virtual environment was not found.
  echo Run the installation commands in README.md first.
  pause
  exit /b 1
)

".venv\Scripts\python.exe" launch_daily_review.py
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
  echo.
  echo ERROR: Daily review app failed to start. Exit code: %EXIT_CODE%
  pause
)

exit /b %EXIT_CODE%
