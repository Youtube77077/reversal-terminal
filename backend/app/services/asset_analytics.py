"""Per-asset deep-dive analytics, profitability map and asset comparison.

Answers "what is profitable and what is not" for every market (BTC, ETH, SOL,
XRP, DOGE, HYPE, BNB) using realised paper-trading P&L and resolved research
observations. Every grouping carries sample size, a 95% CI and a verdict that
only says PROFITABLE / UNPROFITABLE when the confidence interval excludes zero.
"""
from __future__ import annotations

import json
import math

import pandas as pd
from sqlalchemy import text

from ..constants import ASSETS, CHECKPOINTS, distance_bucket, price_bucket, probability_bucket
from ..db import engine
from .analytics import (
    DIST_ORDER,
    PRICE_ORDER,
    PROB_ORDER,
    _clean,
    breakdowns,
    interval_table,
    load_checkpoints,
    perf_metrics,
    summarize,
    transactions_df,
)
from .statistics import mean_ci, rate_stat

ENTRY_T_ORDER = ["T-0..2", "T-2..4", "T-4..7", "T-7..12", "T-12..20", "T-20..35", "T-35..70", "T-70+"]
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def verdict(lo, hi, n) -> str:
    """Plain-language verdict from the 95% CI of EV per trade / per share."""
    if not n or n < 2 or lo is None or hi is None:
        return "no data"
    if n < 30:
        return "too few samples"
    if lo > 0:
        return "PROFITABLE (95% CI > 0)"
    if hi < 0:
        return "UNPROFITABLE (95% CI < 0)"
    return "inconclusive"


def entry_t_bucket(secs) -> str | None:
    if secs is None or (isinstance(secs, float) and math.isnan(secs)):
        return None
    for lo, hi, lab in ((0, 2, "T-0..2"), (2, 4, "T-2..4"), (4, 7, "T-4..7"), (7, 12, "T-7..12"),
                        (12, 20, "T-12..20"), (20, 35, "T-20..35"), (35, 70, "T-35..70"), (70, 1e9, "T-70+")):
        if lo <= secs < hi:
            return lab
    return None


def pnl_groups(settled: pd.DataFrame, col: str, order: list | None = None) -> list[dict]:
    rows = []
    if settled is None or settled.empty or col not in settled:
        return rows
    for key, g in settled.groupby(col, dropna=True):
        n = int(len(g))
        w = int((g["status"] == "won").sum())
        rs = rate_stat(w, n)
        pnl = g["net_profit"].astype(float)
        cost = float(g["total_cost"].sum())
        m, lo, hi = mean_ci(pnl.tolist())
        be = float((g["total_cost"] / g["filled_shares"]).mean()) if n else None
        rows.append({"group": key, "trades": n, "wins": w, "losses": n - w, "win_rate": rs.rate,
                     "win_ci_low": rs.ci_low, "win_ci_high": rs.ci_high, "sample": rs.sample,
                     "net_pnl": float(pnl.sum()), "gross_profit": float(pnl[pnl > 0].sum()),
                     "gross_loss": float(pnl[pnl < 0].sum()), "fees": float(g["trading_fee"].sum()),
                     "slippage": float(g["slippage"].sum()), "invested": cost,
                     "roi": (float(pnl.sum()) / cost) if cost else None, "ev_per_trade": m, "ev_ci_low": lo,
                     "ev_ci_high": hi, "breakeven_win_rate": be, "avg_entry": _clean(g["entry_price"].mean()),
                     "verdict": verdict(lo, hi, n)})
    if order:
        rows.sort(key=lambda r: order.index(r["group"]) if r["group"] in order else 999)
    return [{k: _clean(v) for k, v in r.items()} for r in rows]


def _enrich(settled: pd.DataFrame) -> pd.DataFrame:
    s = settled.copy()
    s["price_bucket"] = s["entry_price"].map(price_bucket)
    s["entry_t"] = s["entry_secs_remaining"].map(entry_t_bucket)
    dt = pd.to_datetime(s["created_ts"], unit="ms", utc=True)
    s["hour_utc"] = dt.dt.hour
    s["weekday_utc"] = dt.dt.day_name().str[:3]
    snaps = s["entry_snapshot_json"].map(lambda x: json.loads(x) if x else {})
    s["prob_bucket"] = snaps.map(lambda d: probability_bucket(d.get("fav_prob")))
    s["dist_bucket"] = snaps.map(lambda d: distance_bucket(d.get("dist_bps")))
    s["momentum"] = snaps.map(lambda d: ((d.get("decision") or {}).get("reasons") or {}).get("mom_toward_dog")) \
        .map({True: "toward underdog", False: "away from underdog"}).fillna("flat/unknown")
    s = s.sort_values("settled_ts")
    s["cum_pnl"] = s["net_profit"].astype(float).cumsum()
    return s


def asset_report(asset: str) -> dict:
    tx = transactions_df(source="live")
    tx = tx[tx["asset"] == asset] if not tx.empty else tx
    settled = tx[tx["status"].isin(["won", "lost"])] if not tx.empty else tx
    settled = _enrich(settled) if not settled.empty else settled
    perf = perf_metrics(tx, {"id": None, "name": asset, "strategy_key": "ALL", "initial_balance": 0})
    orders = int(len(tx))
    filled_mask = (tx["filled_shares"] > 0) if orders else None
    filled = int(filled_mask.sum()) if orders else 0
    partial = int(((tx["unfilled_shares"] > 1e-6) & filled_mask).sum()) if orders else 0

    by_strategy = []
    if not tx.empty:
        accts = pd.read_sql(text("SELECT id, name, strategy_key FROM accounts"), engine)
        for _, a in accts.iterrows():
            g = tx[tx["account_id"] == a["id"]]
            if len(g):
                r = perf_metrics(g, {"id": int(a["id"]), "name": a["name"], "strategy_key": a["strategy_key"],
                                     "initial_balance": 0})
                r["verdict"] = verdict(r.get("ev_ci_low"), r.get("ev_ci_high"), r.get("settled") or 0)
                by_strategy.append(r)
        by_strategy.sort(key=lambda r: r.get("net_pnl") or 0, reverse=True)

    with engine.connect() as c:
        mk = c.execute(text(
            "SELECT COUNT(*), SUM(status='resolved'), SUM(winner='UP'), SUM(winner='DOWN'), "
            "AVG(ABS(close_price-open_price)/open_price*1e4) FROM markets WHERE asset=:a AND COALESCE(window,'5m')='5m'"), {"a": asset}).one()
        ob = c.execute(text(
            "SELECT COUNT(*), AVG(up_ask-up_bid), AVG(down_ask-down_bid), AVG(up_ask_liq+down_ask_liq), "
            "AVG(vol_30s), AVG(CASE WHEN book_ok THEN 1.0 ELSE 0 END), AVG(CASE WHEN spot_ok THEN 1.0 ELSE 0 END), "
            "AVG(trade_volume) FROM market_observations WHERE asset=:a"), {"a": asset}).one()
        gaps = c.execute(text("SELECT COALESCE(SUM(missing_seconds),0) FROM collector_gaps WHERE asset=:a"),
                         {"a": asset}).scalar()
    upw, dnw = int(mk[2] or 0), int(mk[3] or 0)
    market_stats = {
        "markets": int(mk[0] or 0), "resolved": int(mk[1] or 0), "up_wins": upw, "down_wins": dnw,
        "up_win_rate": rate_stat(upw, upw + dnw).dict(), "avg_abs_move_bps": _clean(mk[4]),
        "observations": int(ob[0] or 0), "avg_up_spread": _clean(ob[1]), "avg_down_spread": _clean(ob[2]),
        "avg_top5_ask_liquidity_usd": _clean(ob[3]), "avg_vol_30s_bps": _clean(ob[4]),
        "book_coverage": _clean(ob[5]), "spot_coverage": _clean(ob[6]), "avg_shares_traded_per_s": _clean(ob[7]),
        "missing_seconds": int(gaps or 0),
    }
    ck = load_checkpoints("live", asset)
    order = {"price_bucket": PRICE_ORDER, "prob_bucket": PROB_ORDER, "t_minus": CHECKPOINTS}
    cells = summarize(ck, ["t_minus", "price_bucket"], order) if not ck.empty else []
    for c in cells:
        c["verdict"] = verdict(c.get("realistic_ev_ci_low"), c.get("realistic_ev_ci_high"), c.get("resolved") or 0)
    profit_cells = sorted([c for c in cells if c.get("realistic_ev_per_share") is not None],
                          key=lambda c: (c.get("realistic_ev_ci_low") if c.get("realistic_ev_ci_low") is not None
                                         else -9), reverse=True)
    br = breakdowns(asset, "live")
    st = settled if not settled.empty else None
    return {
        "asset": asset,
        "trading": {**perf, "orders": orders, "filled_orders": filled,
                    "fill_rate": (filled / orders) if orders else None,
                    "partial_fill_rate": (partial / filled) if filled else None,
                    "avg_holding_s": _clean(settled["holding_seconds"].mean()) if st is not None else None,
                    "best_trade": _clean(settled["net_profit"].max()) if st is not None else None,
                    "worst_trade": _clean(settled["net_profit"].min()) if st is not None else None,
                    "verdict": verdict(perf.get("ev_ci_low"), perf.get("ev_ci_high"), perf.get("settled") or 0)},
        "equity_curve": [{"ts": int(r.settled_ts), "cum_pnl": float(r.cum_pnl)} for r in settled.itertuples()]
        if st is not None else [],
        "pnl_by_strategy": by_strategy,
        "pnl_by_entry_price": pnl_groups(st, "price_bucket", PRICE_ORDER),
        "pnl_by_entry_time": pnl_groups(st, "entry_t", ENTRY_T_ORDER),
        "pnl_by_fav_prob": pnl_groups(st, "prob_bucket", PROB_ORDER),
        "pnl_by_distance": pnl_groups(st, "dist_bucket", DIST_ORDER),
        "pnl_by_momentum": pnl_groups(st, "momentum"),
        "pnl_by_side": pnl_groups(st, "outcome"),
        "pnl_by_hour_utc": pnl_groups(st, "hour_utc", list(range(24))),
        "pnl_by_weekday_utc": pnl_groups(st, "weekday_utc", WEEKDAYS),
        "market_stats": market_stats,
        "intervals": interval_table(asset, "live"),
        "by_prob_bucket": summarize(ck, ["t_minus", "prob_bucket"], order) if not ck.empty else [],
        "profit_cells": profit_cells,
        "event_types": br.get("event_types", []),
        "calibration": br.get("calibration", []),
        "distance": br.get("distance", []),
        "momentum": br.get("momentum", []),
    }


def profit_map(min_n: int = 0) -> dict:
    ck = load_checkpoints("live")
    note = ("Ranked by the lower 95% bound of realistic EV per $1-payout share (after book-walk price and taker fee). "
            "Testing many cells inflates false positives — treat a 'PROFITABLE' cell as a hypothesis to confirm "
            "out-of-sample (Backtester test period or a fresh experiment), not as proof.")
    if ck.empty:
        return {"cells": [], "note": note}
    order = {"price_bucket": PRICE_ORDER, "t_minus": CHECKPOINTS}
    cells = summarize(ck, ["asset", "t_minus", "price_bucket"], order) + \
        [dict(c, asset="ALL") for c in summarize(ck, ["t_minus", "price_bucket"], order)]
    cells = [c for c in cells if c.get("realistic_ev_per_share") is not None and (c.get("resolved") or 0) >= min_n]
    for c in cells:
        c["verdict"] = verdict(c.get("realistic_ev_ci_low"), c.get("realistic_ev_ci_high"), c.get("resolved") or 0)
    cells.sort(key=lambda c: (c.get("realistic_ev_ci_low") if c.get("realistic_ev_ci_low") is not None else -9,
                              c.get("resolved") or 0), reverse=True)
    return {"cells": cells, "note": note}


def assets_summary() -> list[dict]:
    tx = transactions_df(source="live")
    out = []
    for a in ASSETS:
        g = tx[tx["asset"] == a] if not tx.empty else tx
        p = perf_metrics(g, {"id": None, "name": a, "strategy_key": "ALL", "initial_balance": 0})
        row = {"asset": a}
        for k in ("trades", "settled", "wins", "losses", "win_rate", "win_ci_low", "win_ci_high", "sample", "net_pnl",
                  "fees", "roi", "ev_per_trade", "ev_ci_low", "ev_ci_high", "max_drawdown", "breakeven_win_rate"):
            row[k] = p.get(k)
        row["verdict"] = verdict(p.get("ev_ci_low"), p.get("ev_ci_high"), p.get("settled") or 0)
        ck = load_checkpoints("live", a)
        for t in (10, 5, 3, 1):
            g2 = ck[ck["t_minus"] == t] if not ck.empty else ck
            row[f"rev_T{t}"] = rate_stat(int(g2["lost"].sum()) if len(g2) else 0, int(len(g2))).dict()
        out.append(row)
    return out
