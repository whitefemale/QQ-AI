@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\launch_desktop.ps1" %*
if errorlevel 1 (
  echo.
  echo 启动没有完成，请查看上方错误信息。
  pause
)

endlocal
