"""How each coin moves in a 5-minute market — learned from every recorded market.

For each coin, from the recorded Chainlink price (the settlement feed):
  * typical 5-minute move (final 60s average vs the price to beat = 60s average at the start)
  * typical moves over the last 120 / 60 / 30 / 10 seconds
  * how often the price crosses the price to beat in the last 2 minutes / last 60 s
  * UP win rate, typical 1-second volatility
  * sigma_scale: how far off the flip-chance model's uncertainty was for this coin
    (1.0 = right; >1 = the coin moved more than the model expected, so be less confident)

Recomputed at most every 5 minutes. Strategies read ``SIGMA_SCALE`` (no DB access in the hot path).
"""
from __future__ import annotations

import threading
import time

import numpy as np
import pandas as pd
from sqlalchemy import text

from ..constants import ASSETS
from ..db import engine

SIGMA_SCALE: dict[str, float] = {}   # asset -> learned model correction (read by strategies)
_cache: dict = {"ts": 0, "data": None}
_lock = threading.Lock()
TTL = 300


def _q(arr, q):
    arr = np.asarray([x for x in arr if x == x])
    return float(np.quantile(arr, q)) if len(arr) else None


def compute(days: int = 30) -> dict:
    since = int((time.time() - days * 86400) * 1000)
    m = pd.read_sql(text("SELECT id, asset, open_ts, close_ts, winner FROM markets "
                         "WHERE status='resolved' AND winner IN ('UP','DOWN') AND open_ts >= :s"), engine, params={"s": since})
    sp = pd.read_sql(text("SELECT asset, COALESCE(spot_exchange_ts, server_ts) AS ts, spot, vol_30s FROM market_observations "
                          "WHERE spot IS NOT NULL AND server_ts >= :s"), engine, params={"s": since - 120_000})
    out = {"generated_ts": int(time.time() * 1000), "markets": int(len(m)), "assets": {}}
    if m.empty or sp.empty:
        return out
    sp = sp.sort_values("ts").drop_duplicates(["asset", "ts"])
    for a in ASSETS:
        g = sp[sp.asset == a]
        mm = m[m.asset == a]
        if g.empty or mm.empty:
            continue
        ts, px, vol = g.ts.to_numpy(), g.spot.to_numpy(dtype=float), g.vol_30s.to_numpy(dtype=float)

        def at(t):
            i = np.searchsorted(ts, t, side="right") - 1
            return px[i] if i >= 0 and t - ts[i] < 5000 else np.nan

        def avg(t0, t1):
            k = (ts > t0) & (ts <= t1)
            return px[k].mean() if k.sum() >= 20 else np.nan

        rows, zs = [], []
        for r in mm.itertuples():
            ref = avg(r.open_ts - 60_000, r.open_ts)
            fin = avg(r.close_ts - 60_000, r.close_ts)
            if ref != ref or fin != fin:
                continue
            p = {k: at(r.close_ts - k * 1000) for k in (120, 60, 30, 10, 0)}
            k2 = (ts > r.close_ts - 120_000) & (ts <= r.close_ts)
            sgn = np.sign(px[k2] - ref)
            sgn = sgn[sgn != 0]
            crosses = int((np.diff(sgn) != 0).sum()) if len(sgn) > 1 else 0
            k1 = ts > r.close_ts - 60_000
            sg1 = np.sign(px[k1 & k2] - ref)
            sg1 = sg1[sg1 != 0]
            cross60 = int((np.diff(sg1) != 0).sum()) if len(sg1) > 1 else 0
            seg = px[(ts > r.open_ts) & (ts <= r.close_ts)]
            rows.append({"ref": ref, "move": fin - ref, "d120": p[0] - p[120], "d60": p[0] - p[60],
                         "d30": p[0] - p[30], "d10": p[0] - p[10], "crosses": crosses, "cross60": cross60,
                         "up": r.winner == "UP", "fin": fin, "open_ts": int(r.open_ts), "close_ts": int(r.close_ts),
                         "range": float(seg.max() - seg.min()) if len(seg) else np.nan, "id": int(r.id),
                         "agree": (fin >= ref) == (r.winner == "UP")})
            # model calibration at T-60 and T-30: predicted sd of (final avg - projection) vs reality
            for t in (60, 30):
                T = r.close_ts - t * 1000
                i = np.searchsorted(ts, T, side="right") - 1
                if i < 0 or vol[i] != vol[i]:
                    continue
                s_now = px[i]
                known = avg(r.close_ts - 60_000, T) if t < 60 else s_now
                if known != known:
                    known = s_now
                w = t / 60
                proj = (1 - w) * known + w * s_now
                sigma = max(vol[i], 0.05) * 1e-4 * s_now
                sd = w * sigma * np.sqrt(t / 3)
                if sd > 0:
                    zs.append((fin - proj) / sd)
        if not rows:
            continue
        df = pd.DataFrame(rows)
        price = float(df.ref.median())
        bps = lambda s: (s.abs() / df.ref * 1e4)
        z = np.asarray(zs)
        scale = float(np.clip(1.4826 * np.median(np.abs(z - np.median(z))), 0.5, 3.0)) if len(z) >= 30 else 1.0
        SIGMA_SCALE[a] = scale
        pct = lambda col: {k: (_q(bps(df[col]), q) or 0) / 100 for k, q in
                           (("p25", .25), ("median", .5), ("p75", .75), ("p90", .9), ("max", 1.0))}
        usd = lambda col: {k: _q(df[col].abs(), q) for k, q in
                           (("p25", .25), ("median", .5), ("p75", .75), ("p90", .9), ("max", 1.0))}
        df["hour"] = pd.to_datetime(df.open_ts, unit="ms").dt.hour
        by_hour = [{"hour": int(h), "n": int(len(x)), "move_pct": float((x.move.abs() / x.ref * 100).median()),
                    "up_rate": float(x.up.mean())} for h, x in df.groupby("hour")]
        # histogram of 5-minute moves in % (signed)
        mv = (df.move / df.ref * 100).to_numpy()
        lim = float(np.quantile(np.abs(mv), 0.98)) or 0.01
        edges = np.linspace(-lim, lim, 13)
        hist, _ = np.histogram(np.clip(mv, -lim, lim), bins=edges)
        recent = df.sort_values("open_ts", ascending=False).head(24)
        out["assets"][a] = {
            "move_5m_pct_full": pct("move"), "move_5m_usd_full": usd("move"),
            "range_5m_usd": usd("range"), "range_5m_pct": pct("range"),
            "last_120s_pct": {"median": (_q(bps(df.d120), .5) or 0) / 100, "p90": (_q(bps(df.d120), .9) or 0) / 100},
            "last_30s_pct": {"median": (_q(bps(df.d30), .5) or 0) / 100, "p90": (_q(bps(df.d30), .9) or 0) / 100},
            "last_10s_pct": {"median": (_q(bps(df.d10), .5) or 0) / 100, "p90": (_q(bps(df.d10), .9) or 0) / 100},
            "biggest_up_usd": float(df.move.max()), "biggest_down_usd": float(df.move.min()),
            "by_hour": by_hour, "hist": {"edges": [float(e) for e in edges], "counts": [int(c) for c in hist]},
            "rule_agreement": float(df.agree.mean()),
            "streak_up_max": _streak(df.sort_values("open_ts").up.tolist(), True),
            "streak_down_max": _streak(df.sort_values("open_ts").up.tolist(), False),
            "recent": [{"id": int(x.id), "open_ts": int(x.open_ts), "price_to_beat": float(x.ref), "final_avg": float(x.fin),
                        "move": float(x.move), "move_pct": float(x.move / x.ref * 100), "winner": "UP" if x.up else "DOWN",
                        "crosses_last_120s": int(x.crosses), "range": None if x.range != x.range else float(x.range)}
                       for x in recent.itertuples()],
            "markets": int(len(df)), "price": price,
            "move_5m_usd": {"median": _q(df.move.abs(), .5), "p90": _q(df.move.abs(), .9), "max": float(df.move.abs().max())},
            "move_5m_pct": {"median": _q(bps(df.move), .5) / 100, "p90": _q(bps(df.move), .9) / 100},
            "last_120s_usd": {"median": _q(df.d120.abs(), .5), "p90": _q(df.d120.abs(), .9)},
            "last_60s_usd": {"median": _q(df.d60.abs(), .5), "p90": _q(df.d60.abs(), .9)},
            "last_30s_usd": {"median": _q(df.d30.abs(), .5), "p90": _q(df.d30.abs(), .9)},
            "last_10s_usd": {"median": _q(df.d10.abs(), .5), "p90": _q(df.d10.abs(), .9)},
            "last_60s_pct": {"median": _q(bps(df.d60), .5) / 100, "p90": _q(bps(df.d60), .9) / 100},
            "crosses_last_120s_avg": float(df.crosses.mean()),
            "pct_markets_crossing_last_60s": float((df.cross60 > 0).mean()),
            "pct_markets_crossing_last_120s": float((df.crosses > 0).mean()),
            "up_win_rate": float(df.up.mean()),
            "vol_1s_bps": _q(g.vol_30s, .5),
            "sigma_scale": scale, "calibration_points": int(len(z)),
        }
    return out


def _streak(seq: list, val: bool) -> int:
    best = cur = 0
    for v in seq:
        cur = cur + 1 if v == val else 0
        best = max(best, cur)
    return best


def flip_rates(days: int = 30) -> dict:
    """Favourite-lost rate and Polymarket's underdog price per coin and time left (from checkpoints)."""
    since = int((time.time() - days * 86400) * 1000)
    df = pd.read_sql(text("SELECT asset, t_minus, favourite_lost, fav_prob FROM checkpoints WHERE valid=1 AND "
                          "favourite_lost IS NOT NULL AND source='live' AND server_ts >= :s"), engine, params={"s": since})
    out = {}
    for a, g in df.groupby("asset"):
        rows = []
        for t, x in g.groupby("t_minus"):
            rows.append({"t": int(t), "n": int(len(x)), "real": float(x.favourite_lost.mean()),
                         "polymarket": float((1 - x.fav_prob).mean())})
        out[a] = sorted(rows, key=lambda r: -r["t"])
    return out


def get(force: bool = False) -> dict:
    with _lock:
        if force or not _cache["data"] or time.time() - _cache["ts"] > TTL:
            data = compute()
            try:
                fr = flip_rates()
                for a, rows in fr.items():
                    if a in data["assets"]:
                        data["assets"][a]["flip_rates"] = rows
            except Exception:
                pass
            _cache["data"] = data
            _cache["ts"] = time.time()
        return _cache["data"]
