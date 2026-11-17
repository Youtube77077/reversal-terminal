@echo off
REM REVERSAL TERMINAL - start backend (collector + API) and frontend in two windows.
REM The backend keeps collecting even if you close the browser.
setlocal
cd /d "%~dp0"

if not exist "backend\.venv\Scripts\python.exe" (
  echo [setup] creating Python virtual environment...
  python -m venv backend\.venv || goto :err
  backend\.venv\Scripts\python -m pip install --upgrade pip
  backend\.venv\Scripts\pip install -r backend\requirements.txt || goto :err
)
if not exist "frontend\node_modules" (
  echo [setup] installing frontend packages...
  pushd frontend & call npm install & popd
)

start "REVERSAL TERMINAL - backend" cmd /k "cd /d %~dp0backend && .venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000"
start "REVERSAL TERMINAL - frontend" cmd /k "cd /d %~dp0frontend && npm run dev"
timeout /t 8 >nul
start "" http://localhost:3000
echo Backend: http://127.0.0.1:8000/docs   Frontend: http://localhost:3000
exit /b 0

:err
echo Setup failed. See SETUP_GUIDE.md
exit /b 1
