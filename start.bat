@echo off
setlocal
cd /d "%~dp0"

if not exist "backend\.venv\Scripts\python.exe" (
  echo [ERROR] No backend venv. First run:
  echo   cd backend
  echo   python -m venv .venv
  echo   .venv\Scripts\python.exe -m pip install -r requirements.txt
  pause
  exit /b 1
)

if not exist "frontend\node_modules" (
  echo [ERROR] No frontend\node_modules. First run:
  echo   cd frontend
  echo   npm install
  pause
  exit /b 1
)

echo Starting backend on http://127.0.0.1:8000
start /b "" "%~dp0backend\.venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --app-dir "%~dp0backend"

echo Starting frontend on http://127.0.0.1:5173
start /b "" cmd /c "cd /d "%~dp0frontend" && npm run dev"

echo.
echo Inbox:   http://127.0.0.1:5173
echo Health:  http://127.0.0.1:8000/health
echo.
echo Close this window, then run stop.bat — or press any key to stop now.
pause >nul

call "%~dp0stop.bat" /nopause
