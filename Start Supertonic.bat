@echo off
rem Double-click to start Supertonic on Windows. Close this window to stop it.
rem The execution policy bypass applies to this one PowerShell process only.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\launch.ps1" %*
if errorlevel 1 (
  echo.
  pause
)
