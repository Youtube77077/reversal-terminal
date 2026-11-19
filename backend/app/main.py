"""REVERSAL TERMINAL — FastAPI application entry point.

Run:  python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
"""
from __future__ import annotations

import asyncio
import json
import logging
import logging.handlers
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .db import now_ms, run_migrations

settings = get_settings()


def _setup_logging() -> None:
    fmt = logging.Formatter('{"ts":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":%(message)r}')
    root = logging.getLogger()
    root.setLevel(settings.log_level)
    log_dir = Path(settings.data_dir) / "logs"
    log_dir.mkdir(exist_ok=True)
    fh = logging.handlers.RotatingFileHandler(log_dir / "reversal_terminal.log", maxBytes=20_000_000, backupCount=5,
                                              encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler()
    sh.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
    root.handlers = [fh, sh]
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("websockets").setLevel(logging.WARNING)


_setup_logging()
log = logging.getLogger("reversal")


async def _backtest_warm():
    """Keep the Strategy Builder's test data loaded and fresh (new markets every 5 minutes)."""
    from .services import custom_backtest as cb
    await asyncio.sleep(20)
    while True:
        try:
            await asyncio.to_thread(cb.data, True)
        except Exception:
            log.exception("strategy builder data refresh failed")
        await asyncio.sleep(300)


@asynccontextmanager
async def lifespan(app: FastAPI):
    run_migrations()
    from .execution.engine import TradingEngine
    from .services import backup
    from .services.collector import collector
    from .services.connections import seed_connections
    from .services.experiments import experiment_watchdog, seed_strategies_and_accounts

    seed_connections()
    seed_strategies_and_accounts()
    from .services import wallets as _w
    _w.seed()
    collector.engine = TradingEngine(collector)
    await collector.start()
    bg = [asyncio.create_task(experiment_watchdog(), name="experiment-watchdog"),
          asyncio.create_task(backup.backup_loop(), name="backup-loop"),
          asyncio.create_task(_maintenance(collector), name="maintenance"),
          asyncio.create_task(_live_watch(collector), name="live-watch"),
          asyncio.create_task(_backtest_warm(), name="backtest-warm")]
    log.info("REVERSAL TERMINAL backend ready on http://%s:%s (PAPER mode)", settings.api_host, settings.api_port)
    try:
        yield
    finally:
        for t in bg:
            t.cancel()
        await collector.stop()


async def _maintenance(collector) -> None:
    n = 0
    while True:
        await asyncio.sleep(60)
        n += 1
        try:
            if n % 5 == 0:
                await asyncio.to_thread(collector.engine.mark_unresolved)
        except Exception:
            log.exception("maintenance failed")


async def _live_watch(collector) -> None:
    """Keeps live eligibility fresh; restores the armed state the user chose after restarts."""
    from .execution.eligibility import check_eligibility
    from .services import app_settings
    from .services.events import record_event
    from .execution.eligibility import executor_health
    from .execution.switch import live_enabled
    from .services import credentials
    eng = collector.engine
    eng.live_armed = bool(app_settings.get_all().get("live_armed")) and live_enabled()
    while True:
        try:
            if credentials.configured_wallets():
                h = await executor_health()
                if (not h.get("ok") and "unreachable" not in str(h.get("error"))) or (h.get("liveEnabled") != live_enabled()) \
                        or set(h.get("wallets") or []) != set(credentials.configured_wallets()):
                    await credentials.push_all(live_enabled())
            if live_enabled():
                el = await check_eligibility(force=True)
                was = eng.live_eligible
                eng.live_eligible = bool(el["eligible"])
                if was and not eng.live_eligible:
                    record_event("connection_failed", "Live trading paused: " + " | ".join(el["reasons"]),
                                 level="ERROR")
            else:
                eng.live_eligible = False
        except Exception:
            log.exception("live watch failed")
            eng.live_eligible = False
        await asyncio.sleep(60)


app = FastAPI(title="REVERSAL TERMINAL API", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
                   allow_methods=["*"], allow_headers=["*"])

from . import auth  # noqa: E402
from .api import core, research, trading  # noqa: E402

app.middleware("http")(auth.auth_middleware)
app.include_router(auth.router)
app.include_router(core.router)
app.include_router(trading.router)
app.include_router(research.router)


@app.websocket("/ws/live")
async def ws_live(ws: WebSocket):
    """Pushes live asset states once per second plus application events as they happen."""
    from .services.collector import collector
    from .services.events import bus

    from .auth import request_authorized
    if not request_authorized(ws.cookies, ws.headers):
        await ws.close(code=4401)
        return
    await ws.accept()
    q = bus.subscribe()

    async def pump_events():
        while True:
            ev = await q.get()
            await ws.send_text(json.dumps(ev, default=str))

    pump = asyncio.create_task(pump_events())
    try:
        while True:
            eng = collector.engine
            payload = {"type": "tick", "ts": now_ms(), "assets": collector.live_states,
                       "asset_status": collector.asset_status,
                       "opportunities": list(eng.opportunities.values()) if eng else [],
                       "collector": {"last_tick_ts": collector.last_tick_ts,
                                     "observations": collector.observations_written,
                                     "clob_ws": collector.channel.connected, "rtds": collector.chainlink.connected,
                                     "binance": collector.binance.connected},
                       "engine_paused": eng.paused if eng else None}
            await ws.send_text(json.dumps(payload, default=str))
            await asyncio.sleep(1.0)
    except (WebSocketDisconnect, RuntimeError):
        pass
    except Exception:
        log.exception("ws error")
    finally:
        pump.cancel()
        bus.unsubscribe(q)


# ---------------------------------------------------------------- UI (exported Next.js app)
FRONTEND_OUT = Path(__file__).resolve().parents[2] / "frontend" / "out"


@app.get("/{full_path:path}", include_in_schema=False)
async def ui(full_path: str):
    from fastapi.responses import FileResponse, JSONResponse
    if not (settings.serve_frontend and FRONTEND_OUT.exists()):
        return JSONResponse({"app": "REVERSAL TERMINAL", "docs": "/docs",
                             "ui": "frontend not built — run `npm run build` in frontend/ or use the dev server"})
    base = FRONTEND_OUT.resolve()
    clean = full_path.strip("/")
    for cand in (clean, f"{clean}/index.html", f"{clean}.html", "index.html" if not clean else None):
        if cand is None:
            continue
        f = (base / cand).resolve()
        if base in f.parents or f == base / "index.html":
            if f.is_file():
                headers = {"Cache-Control": "public, max-age=31536000, immutable"} if "/_next/static/" in f"/{cand}"                     else {"Cache-Control": "no-cache"}
                return FileResponse(f, headers=headers)
    nf = base / "404.html"
    return FileResponse(nf, status_code=404) if nf.exists() else JSONResponse({"detail": "not found"}, 404)
