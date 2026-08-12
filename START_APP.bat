@echo off
setlocal
title G2B Compare - Start
cd /d "%~dp0"

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass ^
  -File "%~dp0scripts\start-user.ps1"
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
  echo.
  echo The app could not start. See the message above.
  echo For help, open QUICK_START.txt.
)

echo.
echo Press any key to close this window.
pause >nul
exit /b %EXIT_CODE%
