"""Real reversal odds vs Polymarket's price, per market and time left.

For every recorded checkpoint (T-60 … T-1) of every resolved 5-minute market:
  * market_price  = what Polymarket charged for the underdog (its implied chance of a flip)
  * model_prob    = the Smart-long-shot model's flip chance at that moment
  * actual        = did the favourite actually lose?
Aggregated per coin and checkpoint, this shows where the market over/under-prices flips
(edge = actual − price − fee) and how well the model is calibrated. Recomputed on every
request, so it updates as each new market resolves (every 5 minutes).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import norm
from sqlalchemy import text

from ..constants import ASSETS
from ..db import engine
from .analytics import _clean
from .statistics import wilson_interval

TS = [60, 30, 15, 10, 5, 3, 1]
FEE = 0.07


def _model(df: pd.DataFrame) -> np.ndarray:
    """Vectorised copy of strategies.library.flip_probability for the underdog."""
    t = df["actual_secs_remaining"].clip(lower=0.5).to_numpy()
    spot = df["o_spot"].to_numpy(dtype=float)
    op = df["o_open"].to_numpy(dtype=float)
    twap = df["o_twap"].fillna(df["o_spot"]).to_numpy(dtype=float)
    vol = df["o_vol"].fillna(1.0).clip(lower=0.05).to_numpy(dtype=float)
    sigma = vol * 1e-4 * spot
    w = np.clip(t / 60.0, 0, 1)
    mean = np.where(t < 60, (1 - w) * (twap - op) + w * (spot - op), spot - op)
    sd = np.where(t < 60, w * sigma * np.sqrt(t / 3.0), sigma * np.sqrt(np.maximum(t - 60, 0) + 20))
    dog_up = (df["favourite"] == "DOWN").to_numpy()
    z = np.where(dog_up, mean, -mean) / np.where(sd > 0, sd, np.nan)
    return np.clip(norm.cdf(z), 1e-4, 0.9999)


def load() -> pd.DataFrame:
    q = text("""
        SELECT c.asset, c.t_minus, c.actual_secs_remaining, c.favourite, c.fav_prob, c.dog_ask, c.favourite_lost,
               c.dist_bps, o.spot AS o_spot, o.open_price AS o_open, o.twap60_est AS o_twap, o.vol_30s AS o_vol
        FROM checkpoints c
        JOIN market_observations o ON o.market_id = c.market_id AND o.server_ts = c.server_ts
        JOIN markets mk ON mk.id = c.market_id AND COALESCE(mk.window, '5m') = '5m'
        WHERE c.valid = 1 AND c.favourite_lost IS NOT NULL AND c.source = 'live' AND c.dog_ask IS NOT NULL
          AND o.spot IS NOT NULL AND o.open_price IS NOT NULL""")
    df = pd.read_sql(q, engine)
    if df.empty:
        return df
    df["model"] = _model(df)
    df["lost"] = df["favourite_lost"].astype(float)
    df["cost"] = df["dog_ask"] + FEE * df["dog_ask"] * (1 - df["dog_ask"])
    return df


def _row(g: pd.DataFrame) -> dict:
    n = int(len(g))
    k = int(g["lost"].sum())
    lo, hi = wilson_interval(k, n)
    actual = k / n if n else None
    price = float(g["dog_ask"].mean())
    # model-selected trades: only where model chance beats cost by 1 point
    sel = g[g["model"] - g["cost"] >= 0.01]
    sel_n = int(len(sel))
    sel_pnl = float((sel["lost"] - sel["cost"]).sum()) if sel_n else 0.0
    brier_m = float(((g["model"] - g["lost"]) ** 2).mean())
    brier_p = float(((g["dog_ask"] - g["lost"]) ** 2).mean())
    return {k2: _clean(v) for k2, v in {
        "n": n, "reversals": k, "actual": actual, "ci_low": lo, "ci_high": hi,
        "market_price": price, "model": float(g["model"].mean()),
        "edge_vs_price": (actual - float(g["cost"].mean())) if actual is not None else None,
        "brier_model": brier_m, "brier_market": brier_p,
        "model_trades": sel_n, "model_trade_wins": int(sel["lost"].sum()) if sel_n else 0,
        "model_pnl_per_share": sel_pnl, "avg_abs_dist_bps": float(g["dist_bps"].abs().mean()),
    }.items()}


def odds_table() -> dict:
    df = load()
    out = {"ts": TS, "assets": {}, "all": [], "note": "edge_vs_price = actual reversal rate − (price + fee). "
           "Positive means Polymarket underprices flips at that point. model_trades = checkpoints where the Smart "
           "long-shot model would have bought (model chance ≥ price + fee + 1pt); model_pnl_per_share is their "
           "summed result per $1 share."}
    if df.empty:
        return out
    for t in TS:
        g = df[df["t_minus"] == t]
        if len(g):
            out["all"].append({"t": t, **_row(g)})
    for a in ASSETS:
        rows = []
        for t in TS:
            g = df[(df["asset"] == a) & (df["t_minus"] == t)]
            if len(g):
                rows.append({"t": t, **_row(g)})
        out["assets"][a] = rows
    return out
