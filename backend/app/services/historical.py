"""Historical ingest from public Polymarket endpoints (kept separate from live data).

What is available for free (verified 2026-11-17):
* Gamma: every past 5m market by slug, with official ``outcomePrices``.
* CLOB ``/prices-history``: price points for a token at ~1-minute fidelity.
* Data API v1 was retired (v2 exists); historical order-book depth is NOT
  published anywhere public.

Consequently historical results can only measure calibration/reversal rates
at coarse horizons (roughly T-60 s and T-120 s, using the last price point at
or before that time). They are NOT executable prices and are never mixed with
live checkpoint results or used for paper-trade P&L.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time

import httpx
from sqlalchemy import select

from ..config import get_settings
from ..constants import ASSETS, MARKET_DURATION_SECONDS, probability_bucket
from ..db import now_ms, session_scope
from ..models import HistoricalMarket
from ..providers.polymarket.discovery import fetch_market, window_start
from .collector import db_write_lock
from .connections import registry
from .statistics import rate_stat

log = logging.getLogger("reversal.historical")

STATE = {"running": False, "done": 0, "total": 0, "errors": 0, "started_ts": None, "finished_ts": None}
HORIZONS = (60, 120, 180)


async def _one(client, sem, asset: str, start: int, gamma: str, clob: str) -> None:
    slug = f"{ASSETS[asset]['slug']}-updown-5m-{start}"
    async with sem:
        try:
            with session_scope() as s:
                if s.scalar(select(HistoricalMarket.id).where(HistoricalMarket.slug == slug)):
                    return
            dm = await fetch_market(client, gamma, asset, start)
            if dm is None or not dm.up_token_id:
                return
            winner = dm.official_winner
            if winner not in ("UP", "DOWN"):
                return
            r = await client.get(f"{clob}/prices-history", params={
                "market": dm.up_token_id, "startTs": start - 60, "endTs": start + MARKET_DURATION_SECONDS,
                "fidelity": 1}, timeout=15)
            hist = r.json().get("history", []) if r.status_code == 200 else []
            registry.ok("clob_rest")
            pts = [[int(h["t"]), float(h["p"])] for h in hist if "t" in h and "p" in h]
            with db_write_lock, session_scope() as s:
                s.add(HistoricalMarket(asset=asset, slug=slug, open_ts=start * 1000,
                                       close_ts=(start + MARKET_DURATION_SECONDS) * 1000, winner=winner,
                                       up_token_id=dm.up_token_id, price_points=len(pts),
                                       history_json=json.dumps(pts), ingested_ts=now_ms()))
        except Exception as e:
            STATE["errors"] += 1
            registry.fail("clob_rest", repr(e))
        finally:
            STATE["done"] += 1
            await asyncio.sleep(0.05)


async def ingest(hours: float = 24, assets: list[str] | None = None) -> None:
    if STATE["running"]:
        return
    st = get_settings()
    assets = [a for a in (assets or list(ASSETS)) if a in ASSETS]
    end = window_start(time.time()) - 2 * MARKET_DURATION_SECONDS
    starts = list(range(end - int(hours * 3600), end, MARKET_DURATION_SECONDS))
    STATE.update(running=True, done=0, total=len(starts) * len(assets), errors=0, started_ts=now_ms(),
                 finished_ts=None)
    sem = asyncio.Semaphore(4)
    try:
        async with httpx.AsyncClient(headers={"User-Agent": "reversal-terminal/1.0 (research)"}) as c:
            await asyncio.gather(*(_one(c, sem, a, s, st.gamma_base_url, st.clob_base_url)
                                   for a in assets for s in starts))
    finally:
        STATE.update(running=False, finished_ts=now_ms())


def historical_stats(asset: str | None = None) -> dict:
    with session_scope() as s:
        q = select(HistoricalMarket)
        if asset and asset != "ALL":
            q = q.where(HistoricalMarket.asset == asset)
        rows = s.scalars(q).all()
        data = [(r.asset, r.close_ts // 1000, r.winner, json.loads(r.history_json or "[]")) for r in rows]
    cells: dict[tuple, list[int]] = {}
    per_h: dict[int, list[int]] = {h: [0, 0] for h in HORIZONS}
    usable = 0
    for a, close, winner, pts in data:
        if not pts:
            continue
        usable += 1
        for h in HORIZONS:
            cut = close - h
            prior = [p for t, p in pts if t <= cut and t >= close - MARKET_DURATION_SECONDS - 60]
            if not prior:
                continue
            p_up = prior[-1]
            if p_up == 0.5:
                continue
            fav = "UP" if p_up > 0.5 else "DOWN"
            fp = max(p_up, 1 - p_up)
            lost = int(fav != winner)
            per_h[h][0] += lost
            per_h[h][1] += 1
            key = (h, probability_bucket(fp))
            c = cells.setdefault(key, [0, 0])
            c[0] += lost
            c[1] += 1
    return {
        "source": "historical (Gamma official outcomes + CLOB prices-history, ~1-minute fidelity)",
        "warning": "Coarse price history, not executable order-book prices. Not comparable to live T-10/T-5/T-3/T-1 "
                   "checkpoints and never used for P&L.",
        "markets_ingested": len(data), "markets_with_prices": usable, "ingest": dict(STATE),
        "by_horizon": [{"horizon_s": h, **rate_stat(*per_h[h]).dict()} for h in HORIZONS],
        "by_prob_bucket": [{"horizon_s": h, "prob_bucket": b, **rate_stat(k, n).dict()}
                           for (h, b), (k, n) in sorted(cells.items(), key=lambda kv: (kv[0][0], str(kv[0][1])))],
    }
