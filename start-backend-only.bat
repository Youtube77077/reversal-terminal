@echo off
REM Runs only the data collector + API (no UI). Use this for long unattended experiments.
cd /d "%~dp0backend"
.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
