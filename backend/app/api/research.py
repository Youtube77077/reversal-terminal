"""Research API: scanner, analytics, calculator, backtesting, historical data."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..services import analytics, backtest, calculator, historical

router = APIRouter(prefix="/api")


@router.get("/scanner")
async def scanner(asset: str | None = None, source: str = "live", start: int | None = None, end: int | None = None,
                  t_minus: int | None = None):
    return await asyncio.to_thread(analytics.scanner, asset, source, start, end, t_minus)


@router.get("/scanner/matrix")
async def scanner_matrix(asset: str | None = None, row: str = "prob_bucket", start: int | None = None,
                         end: int | None = None):
    if row not in ("prob_bucket", "price_bucket"):
        raise HTTPException(400, "row must be prob_bucket|price_bucket")
    return await asyncio.to_thread(analytics.matrix, asset, row, "live", start, end)


@router.get("/analytics/intervals")
async def intervals(asset: str | None = None, start: int | None = None, end: int | None = None,
                    min_fav_prob: float | None = None, max_price: float | None = None):
    return await asyncio.to_thread(analytics.interval_table, asset, "live", start, end, min_fav_prob, max_price)


@router.get("/analytics/breakdowns")
async def breakdowns(asset: str | None = None, t_minus: int | None = None, start: int | None = None,
                     end: int | None = None):
    return await asyncio.to_thread(analytics.breakdowns, asset, "live", start, end, t_minus)


@router.get("/analytics/cross-asset")
async def cross_asset(t_minus: int = 10, max_price: float = 0.20, start: int | None = None, end: int | None = None):
    return await asyncio.to_thread(analytics.cross_asset, t_minus, "live", start, end, max_price)


@router.get("/analytics/checkpoints")
async def checkpoint_rows(asset: str | None = None, t_minus: int | None = None, prob_bucket: str | None = None,
                          price_bucket: str | None = None, limit: int = 500):
    """Drill-down: the raw resolved observations behind any statistic."""
    def _do():
        df = analytics.load_checkpoints("live", asset)
        if df.empty:
            return []
        if t_minus is not None:
            df = df[df["t_minus"] == t_minus]
        if prob_bucket:
            df = df[df["prob_bucket"] == prob_bucket]
        if price_bucket:
            df = df[df["price_bucket"] == price_bucket]
        cols = ["market_id", "slug", "asset", "t_minus", "server_ts", "actual_secs_remaining", "favourite",
                "fav_prob", "dog_ask", "dog_ask_size", "dog_ask_liq", "dog_spread", "dist_bps", "mom_10s",
                "momentum_toward_dog", "winner", "favourite_lost", "price_crossover_after", "underlying_reversal",
                "settlement_reversal", "prob_bucket", "price_bucket"]
        return analytics.clean_records(df.sort_values("server_ts", ascending=False)[cols].head(limit))
    return await asyncio.to_thread(_do)


class CalcIn(BaseModel):
    entry_price: float
    investment: float | None = None
    quantity: float | None = None
    fee_override: float | None = None
    slippage_per_share: float = 0.0
    other_costs: float = 0.0
    reversal_frequency: float | None = None
    fee_rate: float = 0.07


@router.post("/calculator")
async def calc(body: CalcIn):
    try:
        return calculator.calculate(**body.model_dump())
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/calculator/table")
async def calc_table(investment: float = 1.0, slippage_per_share: float = 0.0, fee_rate: float = 0.07):
    return calculator.table(investment, slippage_per_share, fee_rate)


class BacktestIn(BaseModel):
    strategy_key: str = "A"
    params: dict = {}
    start_ts: int | None = None
    end_ts: int | None = None
    assets: list[str] = []
    train_fraction: float = 0.6
    starting_balance: float = 20.0


@router.post("/backtest")
async def run_backtest(body: BacktestIn):
    return await asyncio.to_thread(backtest.run_backtest, body.strategy_key, body.params, body.start_ts, body.end_ts,
                                   body.assets or None, body.train_fraction, body.starting_balance)


class IngestIn(BaseModel):
    hours: float = 24
    assets: list[str] = []


@router.post("/historical/ingest")
async def hist_ingest(body: IngestIn):
    if historical.STATE["running"]:
        return {"started": False, "state": historical.STATE}
    asyncio.create_task(historical.ingest(min(body.hours, 24 * 14), body.assets or None))
    return {"started": True}


@router.get("/historical/stats")
async def hist_stats(asset: str | None = None):
    return await asyncio.to_thread(historical.historical_stats, asset)


@router.get("/analytics/asset/{asset}")
async def asset_analytics(asset: str):
    from ..constants import ASSETS
    from ..services import asset_analytics
    a = asset.upper()
    if a not in ASSETS:
        raise HTTPException(404, "unknown asset")
    return await asyncio.to_thread(asset_analytics.asset_report, a)


@router.get("/analytics/assets-summary")
async def assets_summary():
    from ..services import asset_analytics
    return await asyncio.to_thread(asset_analytics.assets_summary)


@router.get("/analytics/profit-map")
async def profit_map(min_n: int = 0):
    from ..services import asset_analytics
    return await asyncio.to_thread(asset_analytics.profit_map, min_n)


@router.get("/analytics/series")
async def analytics_series(mode: str = "all", account_id: int | None = None):
    from ..services import charts
    return await asyncio.to_thread(charts.trading_series, mode, account_id)


@router.get("/analytics/reversal-curves")
async def reversal_curves():
    from ..services import charts
    return await asyncio.to_thread(charts.reversal_curves)


# ================================================================ Strategy Builder
from pydantic import BaseModel as _BM


class _StratIn(_BM):
    name: str | None = None
    params: dict | None = None


class _TestIn(_BM):
    params: dict
    start_balance: float = 100.0
    days: float | None = None


class _CodeIn(_BM):
    code: str


@router.get("/custom-strategies")
async def custom_list():
    from ..services import custom_strategies as cs
    return await asyncio.to_thread(cs.list_all)


@router.get("/custom-strategies/fields")
def custom_fields():
    from ..strategies.custom import DEFAULTS, LABELS
    return {"defaults": DEFAULTS, "labels": LABELS}


@router.post("/custom-strategies")
def custom_create(body: _StratIn):
    from ..services import custom_strategies as cs
    return cs.create(body.name or "My strategy", body.params or {})


@router.patch("/custom-strategies/{sid}")
def custom_update(sid: int, body: _StratIn):
    from fastapi import HTTPException
    from ..services import custom_strategies as cs
    try:
        return cs.update(sid, body.name, body.params)
    except KeyError as e:
        raise HTTPException(404, str(e))


@router.delete("/custom-strategies/{sid}")
def custom_delete(sid: int):
    from fastapi import HTTPException
    from ..services import custom_strategies as cs
    try:
        cs.delete(sid)
    except KeyError as e:
        raise HTTPException(404, str(e))
    return {"deleted": True}


@router.post("/custom-strategies/decode")
def custom_decode(body: _CodeIn):
    from fastapi import HTTPException
    from ..services import custom_strategies as cs
    try:
        return cs.from_code(body.code)
    except Exception as e:
        raise HTTPException(400, f"Could not read that code: {e}")


@router.get("/custom-strategies/data-status")
def custom_data_status():
    from ..services import custom_backtest as cb
    return cb.status()


@router.post("/custom-strategies/test-start")
def custom_test_start(body: _TestIn):
    from ..services import custom_backtest as cb
    return {"job": cb.start_job(body.params, max(1.0, body.start_balance), body.days)}


@router.get("/custom-strategies/test-job/{jid}")
def custom_test_job(jid: str):
    from fastapi import HTTPException
    from ..services import custom_backtest as cb
    j = cb.job(jid)
    if j is None:
        raise HTTPException(404, "test not found (the server may have restarted) — press Test again")
    return j


@router.post("/custom-strategies/test")
async def custom_test(body: _TestIn):
    from ..services import custom_backtest as cb
    return await asyncio.to_thread(cb.run, body.params, max(1.0, body.start_balance), body.days)


@router.get("/accounts/{account_id}/report")
async def bot_report(account_id: int):
    from ..services import bot_report as br
    return await asyncio.to_thread(br.report, account_id)


@router.get("/analytics/movement")
async def movement():
    from ..services import movement as mv
    return await asyncio.to_thread(mv.get)


@router.get("/analytics/odds")
async def odds():
    from ..services import odds as odds_svc
    return await asyncio.to_thread(odds_svc.odds_table)
