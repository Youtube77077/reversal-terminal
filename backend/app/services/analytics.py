"""Research analytics over RESOLVED observations only.

Every rate is returned with its sample size, a 95% Wilson interval and a
sample-size flag. Different checkpoint times are never pooled unless the
caller explicitly groups by something else AND the response says so. Live,
historical, simulated and backtest results come from separate tables/sources
and are never blended into one figure.
"""
from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd
from sqlalchemy import text

from ..constants import (
    ASSETS,
    CHECKPOINTS,
    DISTANCE_BUCKETS_BPS,
    PRICE_BUCKETS,
    PROBABILITY_BUCKETS,
    distance_bucket,
    price_bucket,
    probability_bucket,
)
from ..db import engine
from ..providers.polymarket.fees import DEFAULT_CRYPTO_FEE_RATE
from .statistics import (
    binomial_p_value_greater,
    brier_score,
    calibration_error,
    log_loss,
    max_drawdown,
    mean_ci,
    rate_stat,
    sample_flag,
    wilson_interval,
)

PROB_ORDER = [b[2] for b in PROBABILITY_BUCKETS]
PRICE_ORDER = [b[2] for b in PRICE_BUCKETS]
DIST_ORDER = [b[2] for b in DISTANCE_BUCKETS_BPS]


def _clean(v):
    if v is None:
        return None
    if isinstance(v, (np.floating, float)):
        return None if (math.isnan(v) or math.isinf(v)) else float(v)
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.bool_,)):
        return bool(v)
    return v


def clean_records(df: pd.DataFrame) -> list[dict]:
    return [{k: _clean(v) for k, v in r.items()} for r in df.to_dict(orient="records")]


# ================================================================ loading
def load_checkpoints(source: str = "live", asset: str | None = None, start_ts: int | None = None,
                     end_ts: int | None = None, include_unresolved: bool = False) -> pd.DataFrame:
    q = "SELECT c.*, m.slug, m.open_ts, m.close_ts FROM checkpoints c JOIN markets m ON m.id = c.market_id " \
        "WHERE c.source = :src AND c.valid = 1 AND COALESCE(m.window, '5m') = '5m'"
    p: dict = {"src": source}
    if not include_unresolved:
        q += " AND c.favourite_lost IS NOT NULL"
    if asset and asset != "ALL":
        q += " AND c.asset = :asset"
        p["asset"] = asset
    if start_ts:
        q += " AND c.server_ts >= :s"
        p["s"] = start_ts
    if end_ts:
        q += " AND c.server_ts <= :e"
        p["e"] = end_ts
    df = pd.read_sql(text(q), engine, params=p)
    if df.empty:
        return df
    df["prob_bucket"] = df["fav_prob"].map(probability_bucket)
    df["price_bucket"] = df["dog_ask"].map(price_bucket)
    df["dist_bucket"] = df["dist_bps"].map(distance_bucket)
    df["lost"] = df["favourite_lost"].astype("float")
    fee_rate = DEFAULT_CRYPTO_FEE_RATE
    ask = df["dog_ask"]
    df["fee_ps"] = fee_rate * ask * (1 - ask)
    exec_px = df["dog_vwap_10usd"].where(df["dog_vwap_10usd"].notna(), ask)
    df["exec_px"] = exec_px
    df["real_cost_ps"] = exec_px + fee_rate * exec_px * (1 - exec_px)
    df["executable"] = (ask.notna() & (df["dog_ask_size"].fillna(0) >= 5) &
                        (df["dog_ask_size"].fillna(0) * ask.fillna(0) >= 1.0))
    return df


# ================================================================ metrics
def group_metrics(g: pd.DataFrame) -> dict:
    n = int(len(g))
    resolved = g[g["favourite_lost"].notna()]
    nr = int(len(resolved))
    k = int(resolved["lost"].sum()) if nr else 0
    rs = rate_stat(k, nr)
    fav_won = (1 - resolved["lost"]).astype(int).tolist() if nr else []
    probs = resolved["fav_prob"].astype(float).tolist() if nr else []
    with_ask = resolved[resolved["dog_ask"].notna()]
    ex = with_ask[with_ask["executable"]]
    out = {
        "observations": n, "resolved": nr, "reversals": k, "non_reversals": nr - k,
        "favourite_wins": nr - k, "favourite_losses": k, "underdog_wins": k, "underdog_losses": nr - k,
        "reversal_rate": rs.rate, "reversal_ci_low": rs.ci_low, "reversal_ci_high": rs.ci_high,
        "non_reversal_rate": (1 - rs.rate) if rs.rate is not None else None,
        "sample": rs.sample,
        "implied_fav_prob": float(np.mean(probs)) if probs else None,
        "actual_fav_win_prob": (1 - rs.rate) if rs.rate is not None else None,
        "calibration_error": calibration_error(probs, fav_won),
        "brier": brier_score(probs, fav_won), "log_loss": log_loss(probs, fav_won),
        "opportunities": int(g["dog_ask"].notna().sum()),
        "executable": int(g["executable"].sum()),
        "insufficient_liquidity": int((g["dog_ask"].notna() & ~g["executable"]).sum()),
        "avg_entry_price": _clean(with_ask["dog_ask"].mean()) if len(with_ask) else None,
        "avg_exec_price": _clean(with_ask["exec_px"].mean()) if len(with_ask) else None,
        "avg_liquidity_usd": _clean(g["dog_ask_liq"].mean()),
        "avg_spread": _clean(g["dog_spread"].mean()),
        "avg_secs_remaining": _clean(g["actual_secs_remaining"].mean()),
        "avg_abs_dist_bps": _clean(g["dist_bps"].abs().mean()),
        "avg_abs_mom_10s": _clean(g["mom_10s"].abs().mean()),
    }
    if len(with_ask):
        ret_theo = with_ask["lost"] - with_ask["dog_ask"]
        ret_real = with_ask["lost"] - with_ask["real_cost_ps"]
        m_t = float(ret_theo.mean())
        m_r, lo_r, hi_r = mean_ci(ret_real.astype(float).tolist())
        avg_cost = float(with_ask["real_cost_ps"].mean())
        out.update({
            "avg_potential_payout_per_dollar": _clean((1 / with_ask["dog_ask"].clip(lower=0.001)).mean()),
            "theoretical_ev_per_share": m_t,
            "theoretical_ev_per_dollar": m_t / float(with_ask["dog_ask"].mean()) if with_ask["dog_ask"].mean() else None,
            "realistic_ev_per_share": m_r, "realistic_ev_ci_low": lo_r, "realistic_ev_ci_high": hi_r,
            "realistic_ev_per_dollar": (m_r / avg_cost) if (m_r is not None and avg_cost) else None,
            "breakeven_prob": avg_cost,
            "p_value_vs_breakeven": binomial_p_value_greater(int(with_ask["lost"].sum()), int(len(with_ask)),
                                                              min(0.999, max(0.001, avg_cost))),
        })
    return {k2: _clean(v) for k2, v in out.items()}


def summarize(df: pd.DataFrame, by: list[str], order: dict[str, list] | None = None) -> list[dict]:
    if df.empty:
        return []
    rows = []
    for keys, g in df.groupby(by, dropna=True):
        keys = keys if isinstance(keys, tuple) else (keys,)
        r = dict(zip(by, keys))
        r.update(group_metrics(g))
        rows.append(r)
    if order:
        def sk(r):
            return tuple((order[c].index(r[c]) if (c in order and r[c] in order[c]) else
                          (-r[c] if c == "t_minus" else 0)) for c in by)
        rows.sort(key=sk)
    return [{k: _clean(v) for k, v in r.items()} for r in rows]


# ================================================================ scanner
def scanner(asset: str | None = None, source: str = "live", start_ts: int | None = None, end_ts: int | None = None,
            t_minus: int | None = None) -> dict:
    df = load_checkpoints(source, asset, start_ts, end_ts)
    all_df = load_checkpoints(source, asset, start_ts, end_ts, include_unresolved=True)
    if t_minus is not None and not df.empty:
        df = df[df["t_minus"] == t_minus]
        all_df = all_df[all_df["t_minus"] == t_minus] if not all_df.empty else all_df
    order = {"prob_bucket": PROB_ORDER, "price_bucket": PRICE_ORDER, "t_minus": CHECKPOINTS}
    res = {
        "filters": {"asset": asset or "ALL", "source": source, "t_minus": t_minus, "start_ts": start_ts,
                    "end_ts": end_ts},
        "note": ("Each row is a (bucket, checkpoint) cell — different checkpoint times are never pooled."
                 if t_minus is None else f"Checkpoint T-{t_minus} only."),
        "totals": {"checkpoints_recorded": int(len(all_df)), "resolved": int(len(df))},
        "by_prob_bucket": summarize(df, ["t_minus", "prob_bucket"], order),
        "by_price_bucket": summarize(df, ["t_minus", "price_bucket"], order),
        "by_asset": summarize(df, ["asset", "t_minus"], order) if not asset or asset == "ALL" else [],
    }
    return res


def interval_table(asset: str | None = None, source: str = "live", start_ts: int | None = None,
                   end_ts: int | None = None, min_fav_prob: float | None = None,
                   max_price: float | None = None) -> list[dict]:
    df = load_checkpoints(source, asset, start_ts, end_ts)
    if df.empty:
        return [{"t_minus": t, "resolved": 0, "sample": "insufficient"} for t in CHECKPOINTS]
    if min_fav_prob is not None:
        df = df[df["fav_prob"] >= min_fav_prob]
    if max_price is not None:
        df = df[df["dog_ask"] <= max_price]
    rows = []
    for t in CHECKPOINTS:
        g = df[df["t_minus"] == t]
        r = {"t_minus": t, "key": t in (10, 5, 3, 1)}
        if len(g):
            r.update(group_metrics(g))
            r["avg_fav_prob"] = _clean(g["fav_prob"].mean())
            r["avg_opposite_price"] = _clean(g["dog_ask"].mean())
        else:
            r.update({"resolved": 0, "sample": "insufficient"})
        rows.append(r)
    return rows


def matrix(asset: str | None, row: str, source: str = "live", start_ts: int | None = None,
           end_ts: int | None = None) -> dict:
    df = load_checkpoints(source, asset, start_ts, end_ts)
    order = PROB_ORDER if row == "prob_bucket" else PRICE_ORDER
    cells = []
    if not df.empty:
        for (b, t), g in df.groupby([row, "t_minus"]):
            n = len(g)
            k = int(g["lost"].sum())
            lo, hi = wilson_interval(k, n)
            cells.append({"row": b, "t_minus": int(t), "n": n, "k": k, "rate": k / n if n else None,
                          "ci_low": lo, "ci_high": hi, "sample": sample_flag(n),
                          "avg_ask": _clean(g["dog_ask"].mean())})
    return {"rows": order, "cols": CHECKPOINTS, "cells": cells}


# ================================================================ breakdowns
def breakdowns(asset: str | None = None, source: str = "live", start_ts: int | None = None,
               end_ts: int | None = None, t_minus: int | None = None) -> dict:
    df = load_checkpoints(source, asset, start_ts, end_ts)
    if df.empty:
        return {"distance": [], "momentum": [], "calibration": []}
    if t_minus is not None:
        df = df[df["t_minus"] == t_minus]
    df = df.copy()
    df["momentum_dir"] = df["momentum_toward_dog"].map({True: "toward underdog", False: "away from underdog"}) \
        .fillna("flat/unknown")
    order = {"dist_bucket": DIST_ORDER, "t_minus": CHECKPOINTS}
    cal = []
    edges = [0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 0.98, 0.99, 1.0001]
    for lo, hi in zip(edges[:-1], edges[1:]):
        g = df[(df["fav_prob"] >= lo) & (df["fav_prob"] < hi)]
        if len(g):
            k = int((1 - g["lost"]).sum())
            ci = wilson_interval(k, len(g))
            cal.append({"bin": f"{lo:.2f}-{min(hi, 1):.2f}", "implied": float(g["fav_prob"].mean()),
                        "actual": k / len(g), "ci_low": ci[0], "ci_high": ci[1], "n": int(len(g))})
    return {
        "distance": summarize(df, ["t_minus", "dist_bucket"], order),
        "momentum": summarize(df, ["t_minus", "momentum_dir"], {"t_minus": CHECKPOINTS}),
        "calibration": cal,
        "event_types": event_type_rates(df),
    }


def event_type_rates(df: pd.DataFrame) -> list[dict]:
    """The four reversal types, reported separately per checkpoint (never mixed)."""
    rows = []
    for t in CHECKPOINTS:
        g = df[df["t_minus"] == t]
        if not len(g):
            continue
        r = {"t_minus": t}
        for col, label in (("favourite_lost", "probability_reversal"), ("price_crossover_after", "price_crossover"),
                           ("underlying_reversal", "underlying_reversal"),
                           ("settlement_reversal", "settlement_reversal")):
            s = g[col].dropna()
            st = rate_stat(int(s.astype(bool).sum()), int(len(s)))
            r[label] = st.dict()
        rows.append(r)
    return rows


# ================================================================ cross-asset
def cross_asset(t_minus: int = 10, source: str = "live", start_ts: int | None = None,
                end_ts: int | None = None, max_price: float = 0.20) -> dict:
    df = load_checkpoints(source, None, start_ts, end_ts)
    board = []
    if not df.empty:
        g_all = df[(df["t_minus"] == t_minus) & (df["dog_ask"] <= max_price)]
        for a in ASSETS:
            g = g_all[g_all["asset"] == a]
            m = group_metrics(g) if len(g) else {"resolved": 0, "sample": "insufficient"}
            m["asset"] = a
            board.append(m)
        # rank by the CONSERVATIVE bound of realistic EV, then sample size — never by gross payout
        board.sort(key=lambda r: (r.get("realistic_ev_ci_low") if r.get("realistic_ev_ci_low") is not None else -9,
                                  r.get("resolved", 0)), reverse=True)
        for i, r in enumerate(board):
            r["rank"] = i + 1
    return {"t_minus": t_minus, "max_price": max_price, "leaderboard": board,
            "ranking_basis": "lower 95% CI of realistic EV per share after fees & book-walk price; ties by sample",
            "correlation": correlations(), "simultaneous": simultaneous(df, t_minus)}


def correlations(window_s: int = 10, lookback_hours: float = 24) -> dict:
    q = text("SELECT asset, ts_sec, price FROM underlying_prices WHERE source='chainlink' AND ts_sec >= :s")
    import time
    s = int(time.time() - lookback_hours * 3600)
    df = pd.read_sql(q, engine, params={"s": s})
    if df.empty:
        return {"window_s": window_s, "matrix": {}, "n": 0}
    piv = df.pivot_table(index="ts_sec", columns="asset", values="price").sort_index()
    piv = piv.reindex(range(int(piv.index.min()), int(piv.index.max()) + 1)).ffill(limit=5)
    rets = np.log(piv).diff(window_s).iloc[::window_s].dropna(how="all")
    corr = rets.corr(min_periods=30)
    mat = {a: {b: _clean(corr.loc[a, b]) for b in corr.columns} for a in corr.index}
    return {"window_s": window_s, "matrix": mat, "n": int(len(rets)),
            "btc_beta": {a: _clean(corr.loc["BTC", a]) for a in corr.columns} if "BTC" in corr.index else {}}


def simultaneous(df: pd.DataFrame, t_minus: int) -> dict:
    if df.empty:
        return {}
    g = df[df["t_minus"] == t_minus][["open_ts", "asset", "lost"]]
    if g.empty:
        return {}
    per_window = g.groupby("open_ts").agg(n=("lost", "size"), rev=("lost", "sum"))
    btc = g[g["asset"] == "BTC"].set_index("open_ts")["lost"]
    others = g[g["asset"] != "BTC"].copy()
    others["btc_rev"] = others["open_ts"].map(btc)
    out = {"windows": int(len(per_window)),
           "multi_reversal_windows": int((per_window["rev"] >= 2).sum()),
           "avg_reversals_per_window": _clean(per_window["rev"].mean())}
    for flag, label in ((1.0, "given_btc_reversed"), (0.0, "given_btc_held")):
        sub = others[others["btc_rev"] == flag]
        st = rate_stat(int(sub["lost"].sum()), int(len(sub)))
        out[label] = st.dict()
    return out


# ================================================================ trading results
def transactions_df(experiment_id: str | None = None, account_id: int | None = None, source: str = "live",
                    start_ts: int | None = None, end_ts: int | None = None) -> pd.DataFrame:
    q = "SELECT t.*, a.name AS account_name FROM transactions t JOIN accounts a ON a.id = t.account_id WHERE t.source=:src"
    p: dict = {"src": source}
    if experiment_id:
        q += " AND t.experiment_id = :e"
        p["e"] = experiment_id
    if account_id:
        q += " AND t.account_id = :a"
        p["a"] = account_id
    if start_ts:
        q += " AND t.created_ts >= :s"
        p["s"] = start_ts
    if end_ts:
        q += " AND t.created_ts <= :x"
        p["x"] = end_ts
    return pd.read_sql(text(q), engine, params=p)


def strategy_comparison(experiment_id: str | None = None, start_ts: int | None = None,
                        end_ts: int | None = None) -> list[dict]:
    df = transactions_df(experiment_id, start_ts=start_ts, end_ts=end_ts)
    accts = pd.read_sql(text("SELECT id, name, strategy_key, initial_balance, cash, reserved FROM accounts "
                             "WHERE archived = 0"), engine)
    rows = []
    for _, a in accts.iterrows():
        g = df[df["account_id"] == a["id"]] if not df.empty else df
        rows.append(perf_metrics(g, a.to_dict()))
    rows.sort(key=lambda r: (r.get("net_pnl") or 0), reverse=True)
    return rows


def perf_metrics(g: pd.DataFrame, acct: dict | None = None) -> dict:
    acct = acct or {}
    out = {"account_id": acct.get("id"), "account": acct.get("name"), "strategy": acct.get("strategy_key"),
           "balance": _clean((acct.get("cash") or 0) + (acct.get("reserved") or 0)) if acct else None}
    if g is None or g.empty:
        out.update({"trades": 0, "signals_filled": 0, "wins": 0, "losses": 0, "win_rate": None, "net_pnl": 0.0,
                    "sample": "insufficient"})
        return out
    settled = g[g["status"].isin(["won", "lost"])].sort_values("settled_ts")
    filled = g[g["filled_shares"] > 0]
    w = int((settled["status"] == "won").sum())
    n = int(len(settled))
    rs = rate_stat(w, n)
    pnl = settled["net_profit"].astype(float)
    eq = (pnl.cumsum() + (acct.get("initial_balance") or 0)).tolist()
    mdd, mdd_pct = max_drawdown([acct.get("initial_balance") or 0] + eq) if eq else (0.0, 0.0)
    m, lo, hi = mean_ci(pnl.tolist())
    cost = float(settled["total_cost"].sum())
    be = float((settled["total_cost"] / settled["filled_shares"]).mean()) if n else None
    out.update({
        "trades": int(len(filled)), "orders": int(len(g)), "settled": n, "wins": w, "losses": n - w,
        "open": int(g["status"].isin(["filled", "partially_filled", "pending"]).sum()),
        "unfilled_or_cancelled": int(g["status"].isin(["cancelled", "expired"]).sum()),
        "win_rate": rs.rate, "win_ci_low": rs.ci_low, "win_ci_high": rs.ci_high, "sample": rs.sample,
        "gross_profit": _clean(pnl[pnl > 0].sum()), "gross_loss": _clean(pnl[pnl < 0].sum()),
        "fees": _clean(filled["trading_fee"].sum()), "slippage": _clean(filled["slippage"].sum()),
        "net_pnl": _clean(pnl.sum()), "invested": cost, "roi": (pnl.sum() / cost) if cost else None,
        "ev_per_trade": m, "ev_ci_low": lo, "ev_ci_high": hi,
        "avg_entry_price": _clean(filled["entry_price"].mean()), "breakeven_win_rate": be,
        "p_value_vs_breakeven": binomial_p_value_greater(w, n, min(0.999, max(0.001, be))) if (n and be) else None,
        "max_drawdown": mdd, "max_drawdown_pct": mdd_pct,
    })
    return {k: _clean(v) for k, v in out.items()}


def overview_stats(experiment_id: str | None = None) -> dict:
    with engine.connect() as c:
        def one(q, **p):
            return c.execute(text(q), p).scalar() or 0
        out = {
            "markets_discovered": one("SELECT COUNT(*) FROM markets"),
            "markets_resolved": one("SELECT COUNT(*) FROM markets WHERE status='resolved'"),
            "observations": one("SELECT COUNT(*) FROM market_observations"),
            "checkpoints": one("SELECT COUNT(*) FROM checkpoints WHERE source='live'"),
            "signals": one("SELECT COUNT(*) FROM signals"),
            "signals_accepted": one("SELECT COUNT(*) FROM signals WHERE decision='accepted'"),
            "orders": one("SELECT COUNT(*) FROM simulated_orders"),
            "filled_orders": one("SELECT COUNT(*) FROM simulated_orders WHERE filled_shares > 0"),
            "wins": one("SELECT COUNT(*) FROM transactions WHERE status='won' AND source='live'"),
            "losses": one("SELECT COUNT(*) FROM transactions WHERE status='lost' AND source='live'"),
            "gross_profit": one("SELECT COALESCE(SUM(net_profit),0) FROM transactions WHERE net_profit > 0 AND source='live'"),
            "gross_loss": one("SELECT COALESCE(SUM(net_profit),0) FROM transactions WHERE net_profit < 0 AND source='live'"),
            "fees": one("SELECT COALESCE(SUM(trading_fee),0) FROM transactions WHERE source='live'"),
            "slippage": one("SELECT COALESCE(SUM(slippage),0) FROM transactions WHERE source='live'"),
            "net_pnl": one("SELECT COALESCE(SUM(net_profit),0) FROM transactions WHERE source='live' "
                           "AND status IN ('won','lost','cancelled')"),
            "invested_settled": one("SELECT COALESCE(SUM(total_cost),0) FROM transactions WHERE source='live' "
                                    "AND status IN ('won','lost','cancelled')"),
            "committed_open": one("SELECT COALESCE(SUM(total_cost),0) FROM transactions WHERE source='live' "
                                  "AND status IN ('filled','partially_filled')"),
        }
        key_rates = {}
        for t in (10, 5, 3, 1):
            n_t = one("SELECT COUNT(*) FROM checkpoints WHERE source='live' AND valid=1 AND t_minus=:t "
                      "AND favourite_lost IS NOT NULL", t=t)
            k_t = one("SELECT COUNT(*) FROM checkpoints WHERE source='live' AND valid=1 AND t_minus=:t "
                      "AND favourite_lost=1", t=t)
            key_rates[f"T-{t}"] = rate_stat(int(k_t), int(n_t)).dict()
    n = out["wins"] + out["losses"]
    out["win_rate"] = rate_stat(out["wins"], n).dict()
    out["reversal_frequency"] = key_rates
    out["reversal_frequency_note"] = "Probability-reversal rate per key checkpoint (never pooled across times)."
    out["roi"] = (out["net_pnl"] / out["invested_settled"]) if out["invested_settled"] else None
    return {k: _clean(v) for k, v in out.items()}
