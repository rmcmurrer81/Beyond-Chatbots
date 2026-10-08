@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Run install_windows.bat first.
  pause
  exit /b 1
)
echo Installing optional PyBullet rigid-body simulation tools...
.venv\Scripts\python.exe -m pip install "pybullet>=3.2,<4"
if errorlevel 1 (
  echo Simulation tools installation failed.
  pause
  exit /b 1
)
echo PyBullet installed.
pause
