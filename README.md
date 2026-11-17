# REVERSAL TERMINAL

Research and paper-trading platform for **5-minute crypto UP/DOWN prediction markets** on Polymarket
(BTC, ETH, SOL, XRP, DOGE, HYPE, BNB).

It asks one question rigorously: *does buying the extremely cheap side late in a 5-minute market have
positive expected value after all costs?* It records every second of every market, measures how often the
favourite actually loses at T-120 … T-1, and runs ten independently-accounted paper strategies against the
real order book. It doesn't fake fills, and it doesn't hide missing data.

> **Paper by default, live optional.** Live order placement uses your own Polymarket keys through an isolated
> executor (same SDK path as Polybot). It is off until you set `LIVE_TRADING_ENABLED=true`, add keys on the server,
> create a live account and arm it with your password. Polymarket's geoblock docs list NL as frontend-only (API not
> restricted), but its Terms of Use list the Netherlands as restricted, so trade at your own risk.

**Run it 24/7 without your PC:** see [DEPLOY.md](DEPLOY.md) for the cloud server, HTTPS, password, API keys and iPhone app.

**UI:** Cash App-style with light and dark modes. Phones get 5 tabs: Money, Markets, Bot ($), Activity and Analytics. PC gets a sidebar. Everything
else (Scanner, Strategy Lab, Replay, Experiments, Live, Settings) is under More.

## Quick start (Windows)

```bat
start.bat
```

That creates the Python venv and installs packages on first run, then starts:

* **backend** — FastAPI + the persistent collector on http://127.0.0.1:8000 (API docs at `/docs`)
* **frontend** — Next.js terminal UI on http://localhost:3000

Open the UI → **Experiments** → choose 24h or 48h → **Start experiment**. You can close the browser; the
backend keeps collecting and trading. Use `start-backend-only.bat` for unattended runs.

Full instructions: [SETUP_GUIDE.md](SETUP_GUIDE.md). Research notes: [RESEARCH.md](RESEARCH.md).
Reference-bot study: [REFERENCE_BOT_ANALYSIS.md](REFERENCE_BOT_ANALYSIS.md).

## What it does

| Area | Summary |
|---|---|
| Discovery | Finds the current + next 5m market per asset from Gamma (`{asset}-updown-5m-{start}`), maps UP/DOWN tokens **by label**, records resolution source, TWAP settlement rule, fee schedule, tick/min size. Unavailable markets are shown as unavailable, and substitutions are recorded. |
| Collection | One observation per market per second (UTC-aligned): bids/asks/sizes, top-5 depth, liquidity, last trades, volume, Chainlink spot, opening reference, distance (abs/bp), momentum 1/3/5/10/30/60 s, 30 s volatility, acceleration, estimated 60 s TWAP. Server and exchange timestamps are both kept. |
| Checkpoints | Exact snapshots at T-120, 90, 60, 45, 30, 20, 15, 10, 7, 5, 3, 2, 1 s, never pooled. |
| Resolution | Official outcome from Gamma `outcomePrices`, cross-checked against Polymarket's crypto-price open/close. Four reversal types are classified separately: probability reversal, price crossover, underlying reversal, settlement reversal. |
| Scanner | Probability buckets (50–100 %) × entry-price buckets (<1 c … 20 c) × checkpoint, per asset and combined. Shows opportunities, executable vs thin-liquidity counts, reversal % with Wilson CI and sample size, average ask/liquidity/spread/time/distance/momentum, and theoretical and realistic EV. |
| Paper engine | Strategies A–J (+ F at six entry times) each on its own account. Account-level risk limits apply. Funds are reserved, then the order executes against the **live book after 400 ms simulated latency** (book walk, limit respected, FAK/FOK, partial fills, $1 / 5-share / tick validation; passive limits fill only on trade-through). Fee = shares × 0.07 × p × (1−p) from the market's feeSchedule. Positions settle only on official resolution. |
| Accounting | Every cent goes through the ledger: reserve / fill debit / release / settlement / manual deposit, withdrawal and reset. Accounts track available, reserved, realised, unrealised (mark-to-bid, estimate) and equity. Balances can never go negative. |
| Analytics | Per-interval tables, calibration, Brier and log loss, distance and momentum breakdowns, cross-asset leaderboard (ranked by the lower CI bound of realistic EV), return correlations, simultaneous-reversal analysis, strategy comparison with p-values vs break-even. |
| Per-market analytics | Dedicated page per asset (BTC…BNB). Shows full P&L, win rate vs break-even, EV with CI and a verdict. P&L is broken down by entry price, entry time, favourite probability, distance, momentum, side, hour and weekday. It also includes strategy results per asset, a "what's profitable" cell ranking, market microstructure stats and data coverage. |
| Profit map | Every asset × checkpoint × entry-price cell, ranked by its conservative EV bound, with a multiple-testing warning. |
| Backtester | Chronological replay of recorded data with no look-ahead. It executes on the next recorded second and keeps a train/test split, reporting in-sample and **out-of-sample** results separately, plus coverage. |
| Replay | Second-by-second market replay at 1–50× speed, with a timeline slider, trade markers and the exact state each decision saw. |
| Experiments | 1 h – 48 h or unlimited. Experiments persist through restarts and sleep, and gaps are recorded honestly. Each experiment produces an automatic HTML and CSV report with a rule-based conclusion (EV evidence, sample sufficiency, significance, fee and slippage survival, cross-asset consistency). |
| Ops | Source registry with live connection health, automatic reconnect with backoff, supervised loops, structured logs, SQLite WAL, automatic backups, CSV/JSON export, browser/desktop notifications (each type toggleable). |

## Layout

```
backend/   FastAPI app (app/), Alembic migrations, tests, requirements.txt
  app/providers/polymarket  discovery, market websocket, RTDS Chainlink, resolution, fees
  app/providers/spot        Binance cross-check feed
  app/services              collector, analytics, asset_analytics, backtest, historical, reports, experiments
  app/execution             adapter interface, paper adapter, simulator, accounting, risk, engine, eligibility
  app/strategies            strategy library A–J
frontend/  Next.js 14 + Tailwind + TradingView Lightweight Charts + Lucide
```

## Tests

```bat
cd backend
.venv\Scripts\python -m pytest -q
```

The suite covers discovery, outcome identification, settlement and probability, reversal classification, fees,
slippage, book execution, partial fills, balances, P&L, EV and break-even, persistence, duplicate prevention,
websocket reconnection and experiment recovery. All tests use fixtures and a temp database; they make no network calls and place no orders.

## Honest limitations

* Settlement uses a **60-second Chainlink TWAP**. This damps last-second price moves, so the market's late
  probabilities reflect the TWAP, not just spot. The "est. 60s TWAP" shown is our reconstruction from RTDS ticks.
* Polymarket publishes **no historical second-by-second order books**. Backtests cover only what this
  collector recorded. The historical ingest (Gamma + `prices-history`, about 1-minute resolution) is labelled coarse
  and is never mixed with live results or P&L.
* Queue position for passive orders is unknowable. Passive fills use a conservative trade-through rule.
* Fees follow the documented formula. Gas is recorded as $0 (relayer-paid) and flagged as an estimate.
