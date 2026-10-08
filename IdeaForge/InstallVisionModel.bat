@echo off
where ollama >nul 2>nul
if errorlevel 1 (
  echo Ollama is not installed or not available in PATH.
  pause
  exit /b 1
)
echo This installs the optional local Qwen3-VL 8B model used for troubleshooting photos and screenshots.
echo.
ollama pull qwen3-vl:8b
if errorlevel 1 (
  echo Vision model installation failed.
  pause
  exit /b 1
)
echo.
echo Vision model installed.
pause
