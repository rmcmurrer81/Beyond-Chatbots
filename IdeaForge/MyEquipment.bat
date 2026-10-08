@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\pythonw.exe (
  echo Run install_windows.bat first.
  pause
  exit /b 1
)
start "" .venv\Scripts\pythonw.exe -m inventory.gui
