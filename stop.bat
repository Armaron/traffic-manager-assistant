@echo off
setlocal
echo Stopping Traffic Manager Assistant...

powershell -NoProfile -Command ^
  "Get-NetTCPConnection -LocalPort 8000,5173 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }"

taskkill /FI "WINDOWTITLE eq TMA Backend*" /T /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq TMA Frontend*" /T /F >nul 2>&1

echo Stopped. Ports 8000 and 5173 are free.
if /I not "%~1"=="/nopause" pause
