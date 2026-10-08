@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\pythonw.exe (
  echo IdeaForge is not installed yet. Run install_windows.bat first.
  pause
  exit /b 1
)
start "" .venv\Scripts\pythonw.exe ideaforge.py
