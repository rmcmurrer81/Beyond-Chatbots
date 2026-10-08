@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
  echo Python 3.11 or newer is required.
  pause
  exit /b 1
)

py -3 -m venv .venv
if errorlevel 1 goto :error
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
if errorlevel 1 goto :error

echo.
where ollama >nul 2>nul
if errorlevel 1 (
  echo NOTE: Ollama was not found in PATH.
  echo Install Ollama and make qwen3.5:9b available before using IdeaForge chat.
) else (
  ollama list | findstr /I /C:"qwen3.5:9b" >nul 2>nul
  if errorlevel 1 (
    echo NOTE: qwen3.5:9b was not found in Ollama.
  ) else (
    echo qwen3.5:9b detected.
  )
  ollama list | findstr /I /C:"qwen3-vl:8b" >nul 2>nul
  if errorlevel 1 (
    echo NOTE: qwen3-vl:8b was not found. Run InstallVisionModel.bat for photo/screenshot troubleshooting.
  ) else (
    echo qwen3-vl:8b troubleshooting vision detected.
  )
)

echo.
echo IdeaForge installed.
echo Hands-free uses installed Windows speech components; it does not download a speech model.
echo See ai\HANDS_FREE.md for separate Windows voice setup.
echo Double-click IdeaForge.bat to start.
pause
exit /b 0

:error
echo Installation failed. Review the error above.
pause
exit /b 1
