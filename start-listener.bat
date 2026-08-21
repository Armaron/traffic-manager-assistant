@echo off
setlocal
cd /d "%~dp0"
echo Starting Traffic Manager Notification Listener...

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$pkg = Get-AppxPackage -Name 'TrafficManager.NotificationListener' -ErrorAction SilentlyContinue; if (-not $pkg) { Write-Host 'Listener is not registered.'; Write-Host 'Run register-listener.bat first.'; exit 1 }; Start-Process ('shell:AppsFolder\' + $pkg.PackageFamilyName + '!App')"

if errorlevel 1 (
  echo.
  echo Run register-listener.bat once, then start-listener.bat again.
  pause
  exit /b 1
)

echo.
echo Keep Slack Desktop running with notifications enabled.
echo Backend must be up ^(start.bat^) with SLACK_NOTIFICATION_CAPTURE_ENABLED=true
pause
