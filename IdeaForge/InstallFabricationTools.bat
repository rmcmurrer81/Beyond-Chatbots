@echo off
echo IdeaForge generates OpenSCAD source automatically.
echo.
where openscad >nul 2>nul
if errorlevel 1 (
  echo OpenSCAD is not currently available in PATH.
  echo Install OpenSCAD for automatic STL export, then make sure openscad.exe is available in PATH.
) else (
  echo OpenSCAD detected.
)
echo.
echo Python mesh-validation tools are installed by install_windows.bat.
pause
