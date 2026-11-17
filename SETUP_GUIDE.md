# SETUP GUIDE — REVERSAL TERMINAL (Windows 10/11)

## 1. Requirements

| Tool | Version used | Get it |
|---|---|---|
| Python | 3.12+ (developed on 3.14) | https://www.python.org/downloads/ (tick "Add to PATH") |
| Node.js | 20+ (developed on 22) | https://nodejs.org/ |
| Internet | outbound HTTPS/WSS to polymarket.com, gamma-api / clob / ws-subscriptions-clob / ws-live-data .polymarket.com, stream.binance.com | — |

**No accounts, API keys or payments are needed for paper trading.** Every data source is free and public. Live trading needs your Polymarket keys (see DEPLOY.md §3).

## 2. First run

Double-click **`start.bat`** in the project folder. On first run it will:

1. create `backend\.venv` and install `backend\requirements.txt`;
2. run `npm install` in `frontend`;
3. open two console windows (backend, frontend) and your browser at http://localhost:3000.

The database is created automatically (Alembic migrations) at `backend\data\reversal_terminal.db`.

Manual equivalent:

```bat
cd backend
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```
```bat
cd frontend
npm install
npm run dev
```

## 3. Optional configuration

Copy `.env.example` to `.env` in the project root and edit if you want to change anything (ports,
latency model, enabled assets, backup cadence, per-asset spot provider). The defaults are sensible. `.env` is
git-ignored. Set `APP_PASSWORD` to require a login. Polymarket keys for live trading go here (local) or in
the server's `.env` (cloud). Never commit them or paste them into chat.

`OPTIONAL_DATA_API_KEY` / `OPTIONAL_DATA_API_SECRET` are empty placeholders for a future paid data vendor:

1. *Which provider:* none today.
2. *Why:* only if you later add a vendor with historical order-book depth (Polymarket does not publish it).
3. *Where to obtain:* that vendor's official website/dashboard.
4. *Where to place:* `.env` in the project root.
5. *How to test:* API Connections page → Test.

## 4. Running a 24/48-hour experiment

1. Open http://localhost:3000 → **Experiments**.
2. Pick **24h** (default) or **48h**, select assets and accounts (blank = all), starting balance (default $20 each),
   leave "reset account balances" ticked, then **Start experiment**.
3. You can close the browser. Keep the **backend** window running.
4. Prevent sleep for long runs: *Settings → System → Power → Screen and sleep → "When plugged in, put my device
   to sleep after: Never"* (or `powercfg /change standby-timeout-ac 0` in an admin terminal).
5. If the PC sleeps, restarts or the backend is closed, start it again. The experiment resumes automatically,
   the offline period is recorded as a data gap, and open positions settle from the official results.
6. When the time is up, the report is generated automatically (Experiments → history → *open*), as HTML and CSV.

## 5. Where to look

| Page | Use |
|---|---|
| Overview | status, capital, live asset cards, event feed |
| Reversal Scanner | live cheap-underdog situations + bucket × checkpoint tables |
| Analytics | all-markets comparison, per-interval stats, profit map, calibration, cross-asset |
| Analytics → BTC/ETH/… | full per-market P&L and statistics |
| Trading Engine | accounts, balance management, risk limits, signals, orders, PAPER/LIVE panel |
| Transactions | every simulated trade, filters, CSV/JSON export, click for full detail |
| Market Replay | step through any recorded market |
| Strategy Lab | strategy comparison, backtester, profitability calculator, historical ingest |
| API Connections | data-source registry and health tests |
| Settings | notifications, asset pause, backups/exports, event log |

## 6. Tests

```bat
cd backend
.venv\Scripts\python -m pytest -q
```

## 7. Troubleshooting

| Symptom | Fix |
|---|---|
| UI shows DATA OFFLINE | Is the backend window running? Visit http://127.0.0.1:8000/api/status |
| An asset shows UNAVAILABLE | Polymarket has no 5-minute market for that asset right now. It is shown, not substituted. |
| Port in use | change `API_PORT` in `.env` and set `BACKEND_URL` / `NEXT_PUBLIC_WS_URL` in `frontend\.env.local` |
| "database is locked" | only run one backend instance per database |
| Want a fresh start | stop the backend, move `backend\data\reversal_terminal.db*` elsewhere, restart |

## 8. Moving to GitHub later

The repository is Git-ready: `.gitignore` excludes `.env`, the database, `node_modules`, `.venv` and build
output. Only `.env.example` is committed. Secrets belong in a local `.env`, or in GitHub *Settings → Secrets and
variables* if you later deploy from GitHub. Always-on operation with your PC off needs a hosted machine
(a small VPS or cloud VM). GitHub itself only stores the code; Actions runners are not suited to a 48-hour
always-on collector.
