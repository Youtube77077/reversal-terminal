"""Time series for charts: balances, cumulative P&L, daily P&L, reversal curves."""
from __future__ import annotations

import pandas as pd
from sqlalchemy import text

from ..constants import ASSETS, CHECKPOINTS
from ..db import engine
from .analytics import _clean, load_checkpoints
from .statistics import wilson_interval


def _series(df: pd.DataFrame, ts_col: str, val_col: str, max_points: int = 600) -> list[dict]:
    if df.empty:
        return []
    d = df[[ts_col, val_col]].dropna().sort_values(ts_col)
    if len(d) > max_points:
        step = max(1, len(d) // max_points)
        d = pd.concat([d.iloc[::step], d.iloc[[-1]]])
    return [{"t": int(t), "v": _clean(v)} for t, v in zip(d[ts_col], d[val_col])]


def trading_series(mode: str = "all", account_id: int | None = None) -> dict:
    q = ("SELECT t.settled_ts, t.net_profit, t.status, t.strategy_key, t.asset, t.mode, t.total_cost, t.account_id "
         "FROM transactions t WHERE t.status IN ('won','lost','cancelled') AND t.settled_ts IS NOT NULL")
    p: dict = {}
    if mode in ("paper", "live"):
        q += " AND t.mode = :m"
        p["m"] = mode
    if account_id:
        q += " AND t.account_id = :a"
        p["a"] = account_id
    tx = pd.read_sql(text(q + " ORDER BY t.settled_ts"), engine, params=p)
    out: dict = {"cum_pnl": [], "by_strategy": {}, "by_asset": {}, "by_mode": {}, "daily": [], "hourly": [],
                 "pnl_by_asset": [], "pnl_by_strategy": []}
    if not tx.empty:
        tx["cum"] = tx["net_profit"].astype(float).cumsum()
        out["cum_pnl"] = _series(tx, "settled_ts", "cum")
        for col, key in (("strategy_key", "by_strategy"), ("asset", "by_asset"), ("mode", "by_mode")):
            for k, g in tx.groupby(col):
                g = g.copy()
                g["cum"] = g["net_profit"].astype(float).cumsum()
                out[key][str(k)] = _series(g, "settled_ts", "cum", 300)
        dt = pd.to_datetime(tx["settled_ts"], unit="ms", utc=True)
        tx["day"] = dt.dt.strftime("%Y-%m-%d")
        tx["hour"] = dt.dt.floor("h").astype("int64") // 10**6
        for k, g in tx.groupby("day"):
            out["daily"].append({"x": k, "pnl": float(g["net_profit"].sum()), "trades": int(len(g)),
                                 "wins": int((g["status"] == "won").sum())})
        for k, g in tx.groupby("hour"):
            out["hourly"].append({"t": int(k), "pnl": float(g["net_profit"].sum()), "trades": int(len(g))})
        out["hourly"] = out["hourly"][-72:]
        for col, key in (("asset", "pnl_by_asset"), ("strategy_key", "pnl_by_strategy")):
            for k, g in tx.groupby(col):
                n = int(len(g))
                w = int((g["status"] == "won").sum())
                out[key].append({"x": str(k), "pnl": float(g["net_profit"].sum()), "trades": n, "wins": w,
                                 "win_rate": w / n if n else None})
    # balance history (sum of per-account snapshots, forward-filled)
    bq = "SELECT b.ts, b.account_id, b.equity, b.cash FROM account_balances b JOIN accounts a ON a.id=b.account_id"
    bp: dict = {}
    conds = []
    if mode in ("paper", "live"):
        conds.append("a.mode = :m")
        bp["m"] = mode
    if account_id:
        conds.append("b.account_id = :a")
        bp["a"] = account_id
    if conds:
        bq += " WHERE " + " AND ".join(conds)
    b = pd.read_sql(text(bq + " ORDER BY b.ts"), engine, params=bp)
    if not b.empty:
        piv = b.pivot_table(index="ts", columns="account_id", values="equity", aggfunc="last").sort_index().ffill()
        tot = piv.sum(axis=1).reset_index()
        tot.columns = ["ts", "equity"]
        out["equity"] = _series(tot, "ts", "equity")
    else:
        out["equity"] = []
    return out


def reversal_curves() -> dict:
    ck = load_checkpoints("live")
    out: dict = {"assets": {}, "all": []}
    if ck.empty:
        return out

    def curve(df: pd.DataFrame) -> list[dict]:
        rows = []
        for t in CHECKPOINTS:
            g = df[df["t_minus"] == t]
            n = int(len(g))
            k = int(g["lost"].sum()) if n else 0
            lo, hi = wilson_interval(k, n)
            rows.append({"t": t, "rate": (k / n) if n else None, "n": n, "lo": lo, "hi": hi,
                         "fav_prob": _clean(g["fav_prob"].mean()) if n else None,
                         "dog_ask": _clean(g["dog_ask"].mean()) if n else None})
        return rows

    out["all"] = curve(ck)
    for a in ASSETS:
        out["assets"][a] = curve(ck[ck["asset"] == a])
    return out
