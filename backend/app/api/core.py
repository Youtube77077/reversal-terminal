"""Core API: status, overview, live assets, markets, replay, connections, eligibility, settings, DB."""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import func, select

from ..constants import ASSETS, CHECKPOINTS
from ..db import now_ms, session_scope
from ..execution import accounting
from ..execution.eligibility import check_eligibility
from ..models import (
    Account,
    ApiConnection,
    AppEvent,
    Asset,
    Checkpoint,
    CollectorGap,
    Experiment,
    Market,
    MarketObservation,
    MarketResolution,
    OrderBookSnapshot,
    Transaction,
)
from ..services import analytics, app_settings, backup
from ..services.collector import collector
from ..services.connections import SOURCES, registry
from ..services.experiments import experiment_dict

router = APIRouter(prefix="/api")


def _engine():
    return collector.engine


@router.get("/status")
def status():
    with session_scope() as s:
        e = s.scalar(select(Experiment).where(Experiment.status.in_(("running", "paused"))).limit(1))
        exp = experiment_dict(e) if e else None
    eng = _engine()
    return {"mode": "PAPER", "server_ts": now_ms(), "collector": collector.health(), "experiment": exp,
            "engine": {"paused": eng.paused if eng else None, "last_tick_ts": eng.last_tick_ts if eng else None,
                       "resting_orders": len(eng.resting) if eng else 0},
            "live_trading": "disabled"}


@router.get("/summary")
def summary():
    """Lightweight totals for the app shell and Money screen."""
    from ..execution.session import session_status
    eng = _engine()
    with session_scope() as s:
        accts = s.scalars(select(Account).where(Account.archived.is_(False))).all()
        tot = {"equity": 0.0, "available": 0.0, "reserved": 0.0, "realized": 0.0, "unrealized": 0.0, "open_cost": 0.0}
        rows = []
        running = 0
        for a in accts:
            sm = accounting.account_summary(s, a, eng.mark_prices(s, a.id) if eng else {})
            ss = session_status(s, a)
            if ss["active"] and ss["state"] == "running" and not a.halted_reason:
                running += 1
            for k, src in (("equity", "equity"), ("available", "available"), ("reserved", "reserved"),
                           ("realized", "realized_pnl"), ("unrealized", "unrealized_pnl"),
                           ("open_cost", "open_position_cost")):
                tot[k] += sm[src]
            rows.append({"id": a.id, "name": a.name, "mode": a.mode, "strategy_key": a.strategy_key,
                         "equity": sm["equity"], "realized": sm["realized_pnl"], "open_positions": sm["open_positions"],
                         "session": ss, "halted_reason": a.halted_reason, "paused": a.paused})
        today = (now_ms() // 86_400_000) * 86_400_000
        t_pnl = s.scalar(select(func.coalesce(func.sum(Transaction.net_profit), 0.0))
                         .where(Transaction.settled_ts >= today)) or 0.0
        t_n = s.scalar(select(func.count()).select_from(Transaction).where(Transaction.settled_ts >= today)) or 0
        e = s.scalar(select(Experiment).where(Experiment.status.in_(("running", "paused"))).limit(1))
    return {**{k: round(v, 6) for k, v in tot.items()}, "accounts": rows, "running_bots": running,
            "today_pnl": t_pnl, "today_settled": t_n, "live_armed": bool(eng and eng.live_armed),
            "engine_paused": bool(eng and eng.paused), "experiment": experiment_dict(e) if e else None,
            "server_ts": now_ms()}


@router.get("/overview")
def overview():
    stats = analytics.overview_stats()
    with session_scope() as s:
        accts = s.scalars(select(Account).where(Account.archived.is_(False))).all()
        eng = _engine()
        totals = {"initial": 0.0, "available": 0.0, "reserved": 0.0, "equity": 0.0, "unrealized": 0.0,
                  "open_cost": 0.0, "realized": 0.0, "deposited": 0.0, "withdrawn": 0.0}
        max_dd = 0.0
        for a in accts:
            sm = accounting.account_summary(s, a, eng.mark_prices(s, a.id) if eng else {})
            totals["initial"] += a.initial_balance
            totals["available"] += sm["available"]
            totals["reserved"] += sm["reserved"]
            totals["equity"] += sm["equity"]
            totals["unrealized"] += sm["unrealized_pnl"]
            totals["open_cost"] += sm["open_position_cost"]
            totals["realized"] += sm["realized_pnl"]
            totals["deposited"] += sm["deposited"]
            totals["withdrawn"] += sm["withdrawn"]
            if a.peak_equity:
                max_dd = max(max_dd, (a.peak_equity - sm["equity"]) / a.peak_equity)
        e = s.scalar(select(Experiment).where(Experiment.status.in_(("running", "paused"))).limit(1)) or \
            s.scalar(select(Experiment).order_by(Experiment.started_ts.desc()).limit(1))
        exp = experiment_dict(e) if e else None
    return {"stats": stats, "balances": totals, "accounts": len(accts), "max_drawdown_pct_worst_account": max_dd,
            "experiment": exp, "assets_monitored": len(collector.assets), "collector": collector.health(),
            "mode": "PAPER"}


@router.get("/assets/live")
def assets_live():
    out = []
    for a in ASSETS:
        st = collector.live_states.get(a)
        status = collector.asset_status.get(a, {"status": "disabled"})
        if st and now_ms() - st["server_ts"] > 5000:
            st = {**st, "stale": True}
        out.append({"asset": a, "name": ASSETS[a]["name"], "enabled": a in collector.assets, "state": st,
                    "status": status.get("status"), "status_detail": status.get("detail")})
    return out


@router.get("/markets")
def markets(asset: str | None = None, status: str | None = None, limit: int = 100, offset: int = 0):
    with session_scope() as s:
        q = select(Market)
        if asset:
            q = q.where(Market.asset == asset)
        if status:
            q = q.where(Market.status == status)
        total = s.scalar(select(func.count()).select_from(q.subquery()))
        rows = s.scalars(q.order_by(Market.open_ts.desc()).limit(min(limit, 500)).offset(offset)).all()
        return {"total": total, "rows": [_market_dict(m) for m in rows]}


def _market_dict(m: Market) -> dict:
    return {k: getattr(m, k) for k in (
        "id", "asset", "slug", "window", "gamma_event_id", "gamma_market_id", "condition_id", "question_id",
        "question", "up_token_id", "down_token_id", "open_ts", "close_ts", "status", "resolution_source",
        "settlement_method", "twap_lookback_s", "open_price", "close_price", "open_price_source", "winner",
        "resolved_ts", "fee_type", "fee_rate", "fee_exponent", "fee_taker_only", "fee_rebate_rate", "fee_verified",
        "tick_size", "min_order_size", "neg_risk", "restricted", "substitution_note", "observation_count",
        "discovered_ts")}


@router.get("/markets/{market_id}")
def market_detail(market_id: int):
    with session_scope() as s:
        m = s.get(Market, market_id)
        if not m:
            raise HTTPException(404, "market not found")
        res = s.get(MarketResolution, market_id)
        cks = s.scalars(select(Checkpoint).where(Checkpoint.market_id == market_id)
                        .order_by(Checkpoint.t_minus.desc())).all()
        txs = s.scalars(select(Transaction).where(Transaction.market_id == market_id)).all()
        return {"market": _market_dict(m),
                "resolution": {c.name: getattr(res, c.name) for c in MarketResolution.__table__.columns} if res else None,
                "checkpoints": [{c.name: getattr(k, c.name) for c in Checkpoint.__table__.columns} for k in cks],
                "transactions": [_tx_brief(t) for t in txs]}


def _tx_brief(t: Transaction) -> dict:
    return {"id": t.id, "account_id": t.account_id, "strategy_key": t.strategy_key, "outcome": t.outcome,
            "entry_price": t.entry_price, "filled_shares": t.filled_shares, "status": t.status,
            "entry_ts": t.entry_ts, "created_ts": t.created_ts, "entry_secs_remaining": t.entry_secs_remaining,
            "net_profit": t.net_profit, "limit_price": t.limit_price}


@router.get("/markets/{market_id}/observations")
def market_observations(market_id: int):
    with session_scope() as s:
        rows = s.scalars(select(MarketObservation).where(MarketObservation.market_id == market_id)
                         .order_by(MarketObservation.server_ts)).all()
        cols = [c.name for c in MarketObservation.__table__.columns]
        return [{c: getattr(r, c) for c in cols} for r in rows]


@router.get("/replay/markets")
def replay_markets(asset: str | None = None, with_trades: bool = False, limit: int = 200):
    with session_scope() as s:
        q = select(Market).where(Market.observation_count > 0)
        if asset:
            q = q.where(Market.asset == asset)
        if with_trades:
            q = q.where(Market.id.in_(select(Transaction.market_id)))
        rows = s.scalars(q.order_by(Market.open_ts.desc()).limit(limit)).all()
        ids = [m.id for m in rows]
        tx_counts = dict(s.execute(select(Transaction.market_id, func.count()).where(Transaction.market_id.in_(ids))
                                   .group_by(Transaction.market_id)).all()) if ids else {}
        return [{"id": m.id, "asset": m.asset, "slug": m.slug, "open_ts": m.open_ts, "close_ts": m.close_ts,
                 "status": m.status, "winner": m.winner, "observations": m.observation_count,
                 "trades": tx_counts.get(m.id, 0)} for m in rows]


@router.get("/replay/{market_id}")
def replay(market_id: int):
    with session_scope() as s:
        m = s.get(Market, market_id)
        if not m:
            raise HTTPException(404, "market not found")
        obs = s.execute(select(MarketObservation.server_ts, MarketObservation.secs_remaining, MarketObservation.up_bid,
                               MarketObservation.up_ask, MarketObservation.down_bid, MarketObservation.down_ask,
                               MarketObservation.up_mid, MarketObservation.down_mid, MarketObservation.up_ask_liq,
                               MarketObservation.down_ask_liq, MarketObservation.up_bid_liq,
                               MarketObservation.down_bid_liq, MarketObservation.spot, MarketObservation.open_price,
                               MarketObservation.dist_bps, MarketObservation.mom_10s, MarketObservation.twap60_est,
                               MarketObservation.up_asks_json, MarketObservation.down_asks_json,
                               MarketObservation.book_ok, MarketObservation.spot_ok)
                        .where(MarketObservation.market_id == market_id).order_by(MarketObservation.server_ts)).all()
        keys = ["ts", "secs", "up_bid", "up_ask", "down_bid", "down_ask", "up_mid", "down_mid", "up_ask_liq",
                "down_ask_liq", "up_bid_liq", "down_bid_liq", "spot", "open_price", "dist_bps", "mom_10s", "twap60",
                "up_asks", "down_asks", "book_ok", "spot_ok"]
        frames = []
        for r in obs:
            d = dict(zip(keys, r))
            d["up_asks"] = json.loads(d["up_asks"] or "[]")
            d["down_asks"] = json.loads(d["down_asks"] or "[]")
            frames.append(d)
        txs = s.scalars(select(Transaction).where(Transaction.market_id == market_id)).all()
        trades = []
        for t in txs:
            acct = s.get(Account, t.account_id)
            snap = json.loads(t.entry_snapshot_json) if t.entry_snapshot_json else None
            trades.append({**_tx_brief(t), "account": acct.name if acct else None,
                           "decision": (snap or {}).get("decision"), "knew": snap})
        res = s.get(MarketResolution, market_id)
        cks = s.scalars(select(Checkpoint).where(Checkpoint.market_id == market_id)).all()
        return {"market": _market_dict(m), "frames": frames, "trades": trades,
                "resolution": {"winner": res.winner, "open_price": res.open_price, "close_price": res.close_price,
                               "official": res.official, "status": res.status} if res else None,
                "checkpoints": [{"t_minus": c.t_minus, "favourite": c.favourite, "fav_prob": c.fav_prob,
                                 "dog_ask": c.dog_ask, "favourite_lost": c.favourite_lost} for c in cks]}


@router.get("/orderbook-snapshots/{snap_id}")
def orderbook_snapshot(snap_id: int):
    with session_scope() as s:
        b = s.get(OrderBookSnapshot, snap_id)
        if not b:
            raise HTTPException(404)
        return {"id": b.id, "market_id": b.market_id, "server_ts": b.server_ts, "exchange_ts": b.exchange_ts,
                "reason": b.reason, "up_bids": json.loads(b.up_bids_json), "up_asks": json.loads(b.up_asks_json),
                "down_bids": json.loads(b.down_bids_json), "down_asks": json.loads(b.down_asks_json)}


@router.get("/connections")
def connections():
    live = registry.snapshot()
    with session_scope() as s:
        rows = {r.key: r for r in s.scalars(select(ApiConnection)).all()}
    out = []
    for src in SOURCES:
        st = live.get(src["key"], {})
        out.append({**src, "status": st.get("status", rows.get(src["key"]).status if src["key"] in rows else "unknown"),
                    "last_success_ts": st.get("last_success_ts"), "last_error_ts": st.get("last_error_ts"),
                    "last_error": st.get("last_error"), "failures": st.get("failures", 0),
                    "reconnects": st.get("reconnects", 0), "messages": st.get("messages", 0)})
    return out


@router.post("/connections/{key}/test")
async def test_connection(key: str):
    import time

    import httpx
    from ..config import get_settings
    st = get_settings()
    urls = {"gamma": f"{st.gamma_base_url}/events?limit=1", "clob_rest": f"{st.clob_base_url}/time",
            "crypto_price": None, "geoblock": st.geoblock_url, "binance": f"{st.binance_rest_url}/api/v3/ping"}
    if key in ("clob_ws", "rtds"):
        h = collector.health()
        node = h["clob_ws" if key == "clob_ws" else "rtds"]
        return {"key": key, "ok": node["connected"], "detail": node}
    if key == "clob_trading":
        return {"key": key, "ok": False, "detail": "Live trading disabled (restricted jurisdiction)."}
    url = urls.get(key)
    if key == "crypto_price":
        from ..providers.polymarket.resolution import _iso
        n = now_ms() // 300000 * 300000
        url = f"{st.crypto_price_url}?symbol=BTC&variant=fiveminute&eventStartTime={_iso(n - 300000)}&endDate={_iso(n)}"
    if not url:
        raise HTTPException(404, "unknown connection")
    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(url, headers={"Accept": "application/json"})
        ok = r.status_code == 200
        (registry.ok if ok else registry.fail)(key, *([] if ok else [f"HTTP {r.status_code}"]))
        detail = {"http": r.status_code, "latency_ms": round((time.perf_counter() - t0) * 1000)}
        if key == "geoblock" and ok:
            d = r.json()
            detail.update({"blocked": d.get("blocked"), "country": d.get("country")})
        return {"key": key, "ok": ok, "detail": detail}
    except Exception as e:
        registry.fail(key, repr(e))
        return {"key": key, "ok": False, "detail": repr(e)}


@router.get("/live-mode")
async def live_mode(force: bool = False):
    return await check_eligibility(force)


@router.get("/settings")
def get_settings_api():
    return app_settings.get_all()


@router.put("/settings")
def put_settings(body: dict):
    return app_settings.update(body)


@router.get("/events")
def events(category: str | None = None, limit: int = 200, level: str | None = None):
    with session_scope() as s:
        q = select(AppEvent)
        if category:
            q = q.where(AppEvent.category == category)
        if level:
            q = q.where(AppEvent.level == level)
        rows = s.scalars(q.order_by(AppEvent.ts.desc()).limit(min(limit, 1000))).all()
        return [{"id": r.id, "ts": r.ts, "level": r.level, "category": r.category, "message": r.message,
                 "data": json.loads(r.data_json) if r.data_json else None} for r in rows]


@router.get("/health")
def health():
    with session_scope() as s:
        gaps = s.scalars(select(CollectorGap).order_by(CollectorGap.end_ts.desc()).limit(50)).all()
        gap_total = s.scalar(select(func.coalesce(func.sum(CollectorGap.missing_seconds), 0))) or 0
    return {"collector": collector.health(), "db": backup.db_health(), "missing_seconds_total": gap_total,
            "gaps": [{"asset": g.asset, "start_ts": g.start_ts, "end_ts": g.end_ts, "missing_seconds": g.missing_seconds,
                      "reason": g.reason} for g in gaps],
            "connections": registry.snapshot()}


@router.post("/db/backup")
async def db_backup():
    import asyncio
    p = await asyncio.to_thread(backup.backup_now)
    return {"path": p}


@router.get("/db/export")
async def db_export(fmt: str = Query("csv", pattern="^(csv|json)$"), observations: bool = False):
    import asyncio
    data = await asyncio.to_thread(backup.export_zip, fmt, observations)
    return Response(data, media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="reversal_terminal_export_{fmt}.zip"'})


@router.get("/meta")
def meta():
    from ..constants import CALCULATOR_PRICES, PRICE_BUCKETS, PROBABILITY_BUCKETS
    return {"assets": ASSETS, "checkpoints": CHECKPOINTS, "prob_buckets": [b[2] for b in PROBABILITY_BUCKETS],
            "price_buckets": [b[2] for b in PRICE_BUCKETS], "calculator_prices": CALCULATOR_PRICES}


@router.post("/assets/{symbol}/{action}")
def asset_action(symbol: str, action: str):
    if action not in ("pause", "resume"):
        raise HTTPException(400, "action must be pause|resume")
    from ..services.collector import db_write_lock
    with db_write_lock, session_scope() as s:
        a = s.get(Asset, symbol.upper())
        if not a:
            raise HTTPException(404)
        a.paused = action == "pause"
        return {"asset": a.symbol, "paused": a.paused}


@router.get("/assets")
def assets():
    with session_scope() as s:
        return [{"symbol": a.symbol, "name": a.name, "enabled": a.enabled, "paused": a.paused, "status": a.status,
                 "status_detail": a.status_detail} for a in s.scalars(select(Asset)).all()]
