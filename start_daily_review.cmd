@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo 未找到项目虚拟环境，请先按照 README 安装依赖。
  pause
  exit /b 1
)
".venv\Scripts\python.exe" launch_daily_review.py
if errorlevel 1 (
  echo.
  echo 启动失败。请保留本窗口并检查上方错误信息。
  pause
)
