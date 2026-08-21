@echo off
setlocal
cd /d "%~dp0"
echo Registering Traffic Manager Notification Listener...
echo Developer Mode must be on: Settings - Privacy and security - For developers.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0windows-notification-listener\register-dev.ps1"
if errorlevel 1 (
  echo.
  echo Registration failed. Install .NET 8 SDK and enable Developer Mode, then retry.
  pause
  exit /b 1
)
echo.
echo Registered. Next: start.bat, then start-listener.bat
pause
