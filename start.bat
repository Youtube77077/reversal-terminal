@echo off
REM REVERSAL - run everything on this PC: API + collector + engine (port 8000, serves the web UI)
REM and the live-order executor (localhost only). Settings and keys come from .env.
setlocal
cd /d "%~dp0"

if not exist ".env" (
  copy .env.example .env >nul
  echo [setup] created .env - set APP_PASSWORD in it to require a login.
)
if not exist "backend\.venv\Scripts\python.exe" (
  echo [setup] creating Python virtual environment...
  python -m venv backend\.venv || goto :err
  backend\.venv\Scripts\python -m pip install --upgrade pip
  backend\.venv\Scripts\pip install -r backend\requirements.txt || goto :err
)
if not exist "frontend\out\index.html" (
  echo [setup] building the web app...
  pushd frontend & call npm install & call npm run build & popd
)
if not exist "executor\node_modules" (
  pushd executor & call npm install & popd
)

start "REVERSAL - executor" cmd /k "cd /d %~dp0executor && node --env-file=..\.env index.mjs"
start "REVERSAL - server" cmd /k "cd /d %~dp0backend && .venv\Scripts\python -m uvicorn app.main:app --host 0.0.0.0 --port 8000"
timeout /t 8 >nul
start "" http://localhost:8000
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4"') do echo iPhone app server address: http:%%a:8000
echo Open http://localhost:8000 . Close the two windows to stop.
exit /b 0

:err
echo Setup failed. See SETUP_GUIDE.md
exit /b 1
