"""Chronological backtester over RECORDED live observations.

Data source: the second-by-second observations this application recorded
itself (top-5 ask levels per outcome + best bid). Polymarket does not publish
historical second-by-second order books, so a backtest can only cover periods
during which the collector was running. Coverage is reported explicitly.

No look-ahead:
* markets are replayed in time order, one observation at a time;
* the strategy sees only the observation at the decision second;
* execution happens against the NEXT recorded observation (>= 1 s latency);
* historical reversal statistics used by Strategy I/J come only from
  checkpoints of markets that had officially resolved before the decision
  (training period: expanding window; test period: frozen at the split).
"""
from __future__ import annotations

import json

import pandas as pd
from sqlalchemy import text

from ..constants import price_bucket
from ..db import engine
from ..execution.simulator import simulate_marketable_buy, simulate_passive_check
from ..providers.polymarket.fees import FeeSchedule
from ..strategies.library import StrategyContext, evaluate, nearest_checkpoint
from .market_state import MarketState
from .statistics import binomial_p_value_greater, max_drawdown, mean_ci, rate_stat

RESOLUTION_DELAY_MS = 120_000  # assume official result known 2 min after close (observed ~1.3 min)


def _levels(js: str | None) -> list[tuple[float, float]]:
    if not js:
        return []
    try:
        return [(float(p), float(s)) for p, s in json.loads(js)]
    except (ValueError, TypeError):
        return []


def _state(m: dict, o: dict, fee: FeeSchedule) -> MarketState:
    st = MarketState(
        market_id=m["id"], asset=m["asset"], slug=m["slug"], condition_id=None, up_token="UP", down_token="DOWN",
        open_ts=m["open_ts"], close_ts=m["close_ts"], server_ts=o["server_ts"], secs_remaining=o["secs_remaining"],
        open_price=o["open_price"] or m["open_price"], fee=fee, min_order_size=m["min_order_size"] or 5.0,
        tick_size=m["tick_size"] or 0.01,
        up_bid=o["up_bid"], up_ask=o["up_ask"], down_bid=o["down_bid"], down_ask=o["down_ask"],
        up_bid_size=o["up_bid_size"], up_ask_size=o["up_ask_size"], down_bid_size=o["down_bid_size"],
        down_ask_size=o["down_ask_size"], up_asks=_levels(o["up_asks_json"]), down_asks=_levels(o["down_asks_json"]),
        up_bids=[(o["up_bid"], o["up_bid_size"] or 0)] if o["up_bid"] is not None else [],
        down_bids=[(o["down_bid"], o["down_bid_size"] or 0)] if o["down_bid"] is not None else [],
        book_ok=bool(o["book_ok"]), spot_ok=bool(o["spot_ok"]),
        features={k: o[k] for k in ("spot", "dist_abs", "dist_bps", "mom_1s", "mom_3s", "mom_5s", "mom_10s",
                                    "mom_30s", "mom_60s", "vol_30s", "accel", "twap60_est")},
    )
    return st


def run_backtest(strategy_key: str, params: dict | None = None, start_ts: int | None = None,
                 end_ts: int | None = None, assets: list[str] | None = None, train_fraction: float = 0.6,
                 starting_balance: float = 20.0) -> dict:
    params = params or {}
    q = ("SELECT id, asset, slug, open_ts, close_ts, winner, open_price, fee_rate, fee_exponent, fee_taker_only, "
         "fee_verified, min_order_size, tick_size FROM markets WHERE status='resolved' AND winner IN ('UP','DOWN')")
    p: dict = {}
    if start_ts:
        q += " AND open_ts >= :s"
        p["s"] = start_ts
    if end_ts:
        q += " AND close_ts <= :e"
        p["e"] = end_ts
    mk = pd.read_sql(text(q + " ORDER BY open_ts"), engine, params=p)
    if assets:
        mk = mk[mk["asset"].isin(assets)]
    if mk.empty:
        return {"error": "No resolved markets with recorded observations in range. Run the collector first.",
                "coverage": {"markets": 0}}
    split_idx = int(len(mk) * train_fraction)
    split_ts = int(mk.iloc[split_idx]["open_ts"]) if split_idx < len(mk) else int(mk.iloc[-1]["close_ts"])
    ids = ",".join(str(int(i)) for i in mk["id"])
    obs = pd.read_sql(text(f"SELECT * FROM market_observations WHERE market_id IN ({ids}) ORDER BY server_ts"), engine)
    ck = pd.read_sql(text(f"SELECT c.asset, c.t_minus, c.dog_ask, c.favourite_lost, m.close_ts FROM checkpoints c "
                          f"JOIN markets m ON m.id=c.market_id WHERE c.valid=1 AND c.favourite_lost IS NOT NULL "
                          f"AND c.source='live' ORDER BY m.close_ts"), engine)
    ck["known_ts"] = ck["close_ts"] + RESOLUTION_DELAY_MS
    ck["bucket"] = ck["dog_ask"].map(price_bucket)
    ck_rows = ck.to_dict("records")

    counts: dict[tuple, list[int]] = {}
    ck_ptr = 0

    def advance(ts: int) -> None:
        nonlocal ck_ptr
        limit = min(ts, split_ts) if ts >= split_ts else ts  # freeze stats at the split for the test period
        while ck_ptr < len(ck_rows) and ck_rows[ck_ptr]["known_ts"] <= limit:
            r = ck_rows[ck_ptr]
            if r["bucket"]:
                c = counts.setdefault((r["asset"], r["t_minus"], r["bucket"]), [0, 0])
                c[0] += int(bool(r["favourite_lost"]))
                c[1] += 1
            ck_ptr += 1

    def lookup(asset: str, t: int, price: float) -> tuple[int, int]:
        b = price_bucket(price)
        c = counts.get((asset, t, b), [0, 0]) if b else [0, 0]
        return c[0], c[1]

    ctx = StrategyContext(hist_lookup=lookup)
    trades = []
    total_obs = len(obs)
    ok_obs = int(obs["book_ok"].sum()) if total_obs else 0
    groups = {mid: g.to_dict("records") for mid, g in obs.groupby("market_id")}
    balance = starting_balance
    markets_with_data = 0
    for m in mk.to_dict("records"):
        rows = groups.get(m["id"])
        if not rows:
            continue
        markets_with_data += 1
        fee = FeeSchedule(rate=m["fee_rate"] if m["fee_rate"] is not None else 0.07,
                          exponent=m["fee_exponent"] or 1.0, taker_only=bool(m["fee_taker_only"] if m["fee_taker_only"]
                                                                              is not None else True),
                          verified=bool(m["fee_verified"]))
        for i, o in enumerate(rows):
            advance(o["server_ts"])
            st = _state(m, o, fee)
            d, _ = evaluate(strategy_key, st, params, ctx)
            if d is None:
                continue
            if i + 1 >= len(rows):
                break
            nxt = _state(m, rows[i + 1], fee)
            if d.order_type == "passive_limit":
                fills, filled = [], 0.0
                for o2 in rows[i + 1:]:
                    s2 = _state(m, o2, fee)
                    f = simulate_passive_check(s2.asks(d.side), d.limit_price, d.shares - filled, fee)
                    fills += f
                    filled += sum(x.shares for x in f)
                    if filled >= d.shares - 1e-6:
                        break
                status = "filled" if filled >= d.shares - 1e-6 else ("partially_filled" if filled else "expired")
            else:
                rep = simulate_marketable_buy(nxt.asks(d.side), d.limit_price, d.shares, fee, d.tif,
                                              st.min_order_size, 1.0, st.tick_size)
                fills, status = rep.fills, rep.status
            sh = sum(f.shares for f in fills)
            cost = sum(f.notional + f.fee for f in fills)
            if sh > 0 and cost > balance + 1e-9:
                status, fills, sh, cost = "insufficient_funds", [], 0.0, 0.0
            payout = sh if d.side == m["winner"] else 0.0
            pnl = payout - cost if sh > 0 else 0.0
            if sh > 0:
                balance += pnl
            trades.append({
                "market_id": m["id"], "slug": m["slug"], "asset": m["asset"], "ts": o["server_ts"],
                "period": "train" if o["server_ts"] < split_ts else "test",
                "secs_remaining": o["secs_remaining"], "side": d.side, "decision_ask": d.decision_ask,
                "limit": d.limit_price, "requested": d.shares, "filled": sh,
                "vwap": (sum(f.notional for f in fills) / sh) if sh else None,
                "fees": sum(f.fee for f in fills), "cost": cost, "winner": m["winner"], "payout": payout,
                "pnl": pnl, "status": status if sh == 0 else ("won" if payout > 0 else "lost"),
                "hist": [d.reasons.get("hist_wins"), d.reasons.get("hist_n")],
                "checkpoint": nearest_checkpoint(o["secs_remaining"]), "balance_after": balance,
            })
            break  # one trade per market

    def metrics(ts: list[dict]) -> dict:
        settled = [t for t in ts if t["filled"] > 0]
        w = sum(1 for t in settled if t["payout"] > 0)
        rs = rate_stat(w, len(settled))
        pnl = [t["pnl"] for t in settled]
        m, lo, hi = mean_ci(pnl)
        cost = sum(t["cost"] for t in settled)
        be = (sum(t["cost"] / t["filled"] for t in settled) / len(settled)) if settled else None
        eq, run = [], starting_balance
        for v in pnl:
            run += v
            eq.append(run)
        mdd, mdd_pct = max_drawdown([starting_balance] + eq)
        return {"signals": len(ts), "filled_trades": len(settled),
                "unfilled": sum(1 for t in ts if t["filled"] == 0), "wins": w, "losses": len(settled) - w,
                "win_rate": rs.rate, "win_ci_low": rs.ci_low, "win_ci_high": rs.ci_high, "sample": rs.sample,
                "net_pnl": sum(pnl), "fees": sum(t["fees"] for t in settled), "invested": cost,
                "roi": (sum(pnl) / cost) if cost else None, "ev_per_trade": m, "ev_ci_low": lo, "ev_ci_high": hi,
                "breakeven_win_rate": be,
                "p_value_vs_breakeven": binomial_p_value_greater(w, len(settled), be) if (settled and be) else None,
                "max_drawdown": mdd, "max_drawdown_pct": mdd_pct}

    train = [t for t in trades if t["period"] == "train"]
    test = [t for t in trades if t["period"] == "test"]
    return {
        "strategy": strategy_key, "params": params, "train_fraction": train_fraction, "split_ts": split_ts,
        "coverage": {
            "markets_in_range": int(len(mk)), "markets_with_observations": markets_with_data,
            "observations": total_obs, "observations_with_synced_book": ok_obs,
            "book_coverage_pct": (ok_obs / total_obs) if total_obs else None,
            "first_ts": int(mk["open_ts"].min()), "last_ts": int(mk["close_ts"].max()),
            "limitation": "Uses only data recorded by this collector (top-5 ask levels at 1 s). Polymarket does not "
                          "publish historical second-by-second order books, so earlier periods cannot be tested.",
        },
        "train": metrics(train), "test": metrics(test), "all": metrics(trades),
        "trades": trades[-2000:],
    }
