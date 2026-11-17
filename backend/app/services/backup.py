"""SQLite online backups and data export."""
from __future__ import annotations

import asyncio
import io
import logging
import sqlite3
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from sqlalchemy import text

from ..config import get_settings
from ..db import engine
from .events import record_event

log = logging.getLogger("reversal.backup")

EXPORT_TABLES = ["assets", "markets", "market_resolutions", "checkpoints", "transactions", "simulated_orders",
                 "simulated_fills", "fees", "signals", "accounts", "account_ledger", "account_balances", "experiments",
                 "experiment_reports", "api_connections", "app_events", "collector_gaps", "historical_markets"]


def db_path() -> Path | None:
    url = get_settings().database_url
    if not url.startswith("sqlite:///"):
        return None
    return Path(url.replace("sqlite:///", "", 1))


def backup_now() -> str | None:
    src = db_path()
    if not src or not src.exists():
        return None
    st = get_settings()
    out_dir = Path(st.data_dir) / "backups"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    dest = out_dir / f"reversal_terminal-{stamp}.db"
    with sqlite3.connect(str(src)) as a, sqlite3.connect(str(dest)) as b:
        a.backup(b)  # consistent online backup (safe while writing)
    backups = sorted(out_dir.glob("reversal_terminal-*.db"))
    for old in backups[:-st.backup_keep]:
        old.unlink(missing_ok=True)
    return str(dest)


async def backup_loop() -> None:
    st = get_settings()
    while True:
        await asyncio.sleep(st.backup_interval_hours * 3600)
        try:
            p = await asyncio.to_thread(backup_now)
            record_event("database", f"Backup written: {p}")
        except Exception as e:
            record_event("database", f"Backup failed: {e!r}", level="ERROR")


def export_zip(fmt: str = "csv", include_observations: bool = False) -> bytes:
    buf = io.BytesIO()
    tables = EXPORT_TABLES + (["market_observations", "underlying_prices"] if include_observations else [])
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for t in tables:
            df = pd.read_sql(text(f"SELECT * FROM {t}"), engine)
            if fmt == "json":
                z.writestr(f"{t}.json", df.to_json(orient="records"))
            else:
                z.writestr(f"{t}.csv", df.to_csv(index=False))
    return buf.getvalue()


def db_health() -> dict:
    p = db_path()
    out = {"path": str(p) if p else None, "size_mb": None, "wal_mb": None, "integrity": None, "tables": {}}
    if p and p.exists():
        out["size_mb"] = round(p.stat().st_size / 1e6, 2)
        wal = Path(str(p) + "-wal")
        out["wal_mb"] = round(wal.stat().st_size / 1e6, 2) if wal.exists() else 0
    with engine.connect() as c:
        out["integrity"] = c.execute(text("PRAGMA quick_check")).scalar()
        for t in ("markets", "market_observations", "checkpoints", "transactions", "app_events"):
            out["tables"][t] = c.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar()
    bdir = Path(get_settings().data_dir) / "backups"
    bl = sorted(bdir.glob("reversal_terminal-*.db"))
    out["backups"] = [{"file": b.name, "size_mb": round(b.stat().st_size / 1e6, 2)} for b in bl[-5:]]
    return out
