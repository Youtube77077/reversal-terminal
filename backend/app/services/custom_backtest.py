"""Test a Strategy Builder strategy on every recorded market (same code path as live).

Replays the recorded order book + prices second by second, calls strategies.custom.evaluate_custom,
fills 1 observation (~1 s) later from the recorded ask levels at or below the order's limit, applies
fees, early exits, daily guards and loss protection, settles with the official winner, and returns
every trade with the balance after it ("where the money went"). Data refreshes every 5 minutes as
new markets finish.
"""
from __future__ import annotations

import json
import math
import threading
import time
from datetime import datetime

import numpy as np
import pandas as pd
from sqlalchemy import text

from ..db import engine
from ..providers.polymarket.fees import FeeSchedule, taker_fee
from ..strategies.custom import AMS, evaluate_custom, merged, safety_z, scalp_exit, stake_usd
from .market_state import MarketState

_cache: dict = {"ts": 0.0, "data": None}
_lock = threading.Lock()            # guards swapping _cache (held for microseconds only)
_refresh_lock = threading.Lock()    # one refresh at a time; tests never wait for it once data exists
_results: dict = {}                 # same strategy + same data -> instant answer
FEE = FeeSchedule()
NUM = {"secs": "secs_remaining", "up_bid": "up_bid", "up_ask": "up_ask", "down_bid": "down_bid", "down_ask": "down_ask",
       "ubl": "up_bid_liq", "dbl": "down_bid_liq", "spot": "spot", "fast": "fast_spot", "twap": "twap_window",
       "vol": "vol_30s", "mom": "mom_10s"}


def _load_batch(mk: pd.DataFrame) -> tuple[dict, dict]:
    """Observations of these markets as plain numpy arrays (fast to replay) + each market's price to beat."""
    if mk.empty:
        return {}, {}
    ids = ",".join(str(int(i)) for i in mk.id)
    ob = pd.read_sql(text(f"""SELECT market_id, server_ts, secs_remaining, up_bid, up_ask, down_bid, down_ask, up_asks_json,
        down_asks_json, up_bid_liq, down_bid_liq, spot, fast_spot, twap_window, vol_30s, mom_10s
        FROM market_observations WHERE market_id IN ({ids}) AND book_ok = 1 ORDER BY market_id, server_ts"""), engine)
    # price to beat for older markets: 60 s average of the recorded spot before the window opened
    spot_by_asset = {}
    allsp = ob.merge(mk[["id", "asset"]], left_on="market_id", right_on="id")[["asset", "server_ts", "spot"]].dropna()
    for a, g in allsp.groupby("asset"):
        g = g.sort_values("server_ts").drop_duplicates("server_ts")
        spot_by_asset[a] = (g.server_ts.to_numpy(), g.spot.to_numpy())
    ptb = {}
    for r in mk.itertuples():
        v = r.price_to_beat
        if not v or v != v:
            ts, px = spot_by_asset.get(r.asset, (np.array([]), np.array([])))
            m = (ts > r.open_ts - 60_000) & (ts <= r.open_ts)
            v = float(px[m].mean()) if m.sum() >= 20 else None
            if v is None:   # previous market not in this batch (incremental refresh) -> ask the database
                q = pd.read_sql(text("""SELECT AVG(o.spot) AS v, COUNT(o.spot) AS n FROM market_observations o
                    WHERE o.market_id IN (SELECT id FROM markets WHERE asset = :a AND close_ts >= :lo AND open_ts <= :hi)
                    AND o.server_ts > :lo AND o.server_ts <= :hi"""),
                                engine, params={"a": r.asset, "lo": int(r.open_ts) - 60_000, "hi": int(r.open_ts)})
                if len(q) and (q.n.iloc[0] or 0) >= 20:
                    v = float(q.v.iloc[0])
        ptb[int(r.id)] = v
    close_by = dict(zip(mk.id.astype(int), mk.close_ts.astype(int)))
    for c in NUM.values():
        ob[c] = pd.to_numeric(ob[c], errors="coerce").astype(float)
    obs = {}
    for mid, g in ob.groupby("market_id", sort=False):
        a = {k: g[c].to_numpy(dtype=float) for k, c in NUM.items()}
        a["ts"] = g.server_ts.to_numpy(dtype=np.int64)
        a["ua"] = g.up_asks_json.to_numpy(dtype=object)
        a["da"] = g.down_asks_json.to_numpy(dtype=object)
        sp = np.where(a["ts"] > close_by[int(mid)] - 60_000, a["spot"], np.nan)
        cs = np.cumsum(np.nan_to_num(sp)); cn = np.cumsum(~np.isnan(sp))
        with np.errstate(invalid="ignore", divide="ignore"):
            a["tw"] = np.where(~np.isnan(a["twap"]), a["twap"], np.where(cn > 0, cs / np.maximum(cn, 1), np.nan))
        a["fav_up"] = np.nan_to_num(a["up_ask"]) >= np.nan_to_num(a["down_ask"])
        obs[int(mid)] = a
    return obs, ptb


def refresh(full: bool = False) -> dict:
    """Load only markets that finished since the last refresh (resolved markets never change)."""
    with _refresh_lock:
        mk = pd.read_sql(text("SELECT id, asset, slug, open_ts, close_ts, winner, price_to_beat, COALESCE(window,'5m') AS window "
                              "FROM markets WHERE status='resolved' AND winner IN ('UP','DOWN')"), engine)
        cur = None if full else _cache["data"]
        live = set(int(i) for i in mk.id)
        if cur is None:
            obs, ptb, seen = {}, {}, set()
        else:   # keep what we have (minus anything deleted by a reset)
            obs = {k: v for k, v in cur["obs"].items() if k in live}
            ptb = {k: v for k, v in cur["ptb"].items() if k in live}
            seen = cur["seen"] & live
        new = mk[~mk.id.isin(seen)]
        o2, p2 = _load_batch(new)
        obs.update(o2); ptb.update(p2)
        D = {"markets": mk.set_index("id"), "obs": obs, "ptb": ptb, "seen": seen | set(int(i) for i in new.id)}
        with _lock:
            _cache["data"] = D
            _cache["ts"] = time.time()
            _results.clear()
        return D


def data(force: bool = False) -> dict:
    if force or _cache["data"] is None:
        return refresh()
    return _cache["data"]          # the background task refreshes every 5 minutes without blocking tests


def status() -> dict:
    """What test data is loaded right now (for the Strategy Builder header)."""
    D = _cache.get("data")
    if not D or D.get("markets") is None or len(D["markets"]) == 0:
        return {"loaded": False}
    mk = D["markets"]
    return {"loaded": True, "markets": int(len(mk)), "markets_5m": int((mk.window == "5m").sum()),
            "markets_15m": int((mk.window == "15m").sum()), "first_ts": int(mk.open_ts.min()), "newest_ts": int(mk.close_ts.max()),
            "updated_ts": int(_cache["ts"] * 1000), "refresh_minutes": 5}


def _levels(js) -> list[tuple[float, float]]:
    try:
        return sorted((float(p), float(q)) for p, q in json.loads(js or "[]"))
    except (ValueError, TypeError):
        return []


def _f(x):
    return None if x != x else float(x)


def _lv(a: dict, key: str, i: int) -> list:
    """Parsed ask levels for row i, parsed once and kept (data is immutable once a market is resolved)."""
    c = a.get(key + "_p")
    if c is None:
        c = a[key + "_p"] = [None] * len(a["ts"])
    v = c[i]
    if v is None:
        v = c[i] = _levels(a[key][i])
    return v


def _edge_upper_bound(a: dict, ptb: float, use_fast: bool, predicted: bool, ask: np.ndarray) -> np.ndarray:
    """Vectorised flip_probability for a whole market -> an UPPER BOUND of the model edge each second
    (no fee, price = current ask; the real check uses the limit price + fee, which is never better).
    Rows that cannot reach min_model_edge are skipped without changing any result."""
    spot = a["spot"]
    if use_fast:
        fast = a["fast"]
        spot = np.where(np.isfinite(fast) & (fast != 0), fast, spot)
    t, vol, tw = a["secs"], a["vol"], a["tw"]
    with np.errstate(invalid="ignore", divide="ignore"):
        sigma = np.maximum(vol, 0.05) * 1e-4 * spot
        known = np.where(np.isfinite(tw) & (tw != 0), tw, spot)
        w = t / 60.0
        mean = np.where(t < 60, (1 - w) * (known - ptb) + w * (spot - ptb), spot - ptb)
        sd = np.where(t < 60, w * sigma * np.sqrt(np.maximum(t, 0) / 3.0), sigma * np.sqrt(np.maximum(t - 60, 0) + 20.0))
        from scipy.special import ndtr
        pu = np.clip(ndtr(mean / sd), 0.0001, 0.9999)
        pu = np.where((sd > 0) & (t > 0) & np.isfinite(spot) & (spot != 0) & np.isfinite(vol), pu, np.nan)
        if predicted:
            return np.fmax(pu - a["up_ask"], (1 - pu) - a["down_ask"])
        pw = np.where(ask == a["up_ask"], pu, 1 - pu)
        return pw - ask


def _state(m, a: dict, i: int, ptb) -> MarketState:
    ub, ua_, db, da_ = _f(a["up_bid"][i]), _f(a["up_ask"][i]), _f(a["down_bid"][i]), _f(a["down_ask"][i])
    st = MarketState(market_id=int(m.Index), asset=m.asset, slug=m.slug, condition_id=None, up_token="u", down_token="d",
                     open_ts=int(m.open_ts), close_ts=int(m.close_ts), server_ts=int(a["ts"][i]),
                     secs_remaining=float(a["secs"][i]), open_price=ptb, fee=FEE, min_order_size=5.0, tick_size=0.01,
                     up_bid=ub, up_ask=ua_, down_bid=db, down_ask=da_,
                     up_asks=_lv(a, "ua", i), down_asks=_lv(a, "da", i), book_ok=True, spot_ok=True, window=m.window,
                     features={"spot": float(a["spot"][i]), "fast_spot": _f(a["fast"][i]), "twap_window": _f(a["tw"][i]),
                               "vol_30s": _f(a["vol"][i]), "mom_10s": _f(a["mom"][i]), "ptb_exact": True})
    if ub is not None:
        liq = a["ubl"][i]
        st.up_bids = [(ub, (0.0 if liq != liq else liq) / max(ub, 0.01))]
    if db is not None:
        liq = a["dbl"][i]
        st.down_bids = [(db, (0.0 if liq != liq else liq) / max(db, 0.01))]
    return st


def _find_exit(p: dict, a: dict, side: str, j0: int, entry_px: float, m, ptb):
    """First moment after buying when the strategy would sell early: (how, ts, bid) or None = hold to the end."""
    tp, sp, zs = float(p.get("take_profit_price") or 0), float(p.get("stop_price") or 0), float(p.get("z_stop") or 0)
    rel = float(p.get("take_profit_cents") or 0) > 0 or float(p.get("stop_loss_cents") or 0) > 0
    if not (0 < tp < 1 or 0 < sp < 1 or rel):
        return None
    bids = a["up_bid"] if side == "UP" else a["down_bid"]
    for r in range(j0, len(bids)):
        bid = float(bids[r])
        if bid != bid:
            continue
        if 0 < tp < 1 and bid >= tp:
            return "sold early (take profit)", int(a["ts"][r]), bid
        x = scalp_exit(p, entry_px, bid, FEE) if rel else None
        if x == "take profit":
            return "sold early (take profit)", int(a["ts"][r]), bid
        if 0 < sp < 1 and bid <= sp:
            z = safety_z(_state(m, a, r, ptb), side, bool(p.get("use_fast")))
            if z is None or z < zs:
                return "stop-loss", int(a["ts"][r]), bid
        if x == "stop":
            return "stop-loss", int(a["ts"][r]), bid
    return None


def _key(params: dict, start_balance: float, days) -> str:
    return json.dumps([merged(params), start_balance, days], sort_keys=True, default=str)


def run(params: dict, start_balance: float = 100.0, days: float | None = None, progress=None) -> dict:
    p = merged(params)
    D = data()
    key = _key(params, start_balance, days)
    hit = _results.get(key)
    if hit and hit[0] is D:
        if progress:
            n = int(hit[1].get("markets_tested") or 0)
            progress(n, n)
        return hit[1]
    mk, obs, ptbs = D["markets"], D["obs"], D.get("ptb", {})
    if mk is None or len(mk) == 0:
        return {"error": "no recorded markets yet"}
    wins = set(p.get("windows") or ["5m"]); assets = set(p.get("assets") or [])
    sel = mk[mk.window.isin(wins) & (mk.asset.isin(assets) if assets else True)]
    if days:
        sel = sel[sel.close_ts >= sel.close_ts.max() - days * 86400_000]
    lo_p, hi_p = float(p["min_price"]), float(p["max_price"])
    t_lo, t_hi = float(p["entry_min_secs"]), float(p["entry_max_secs"])
    side_mode = p.get("side", "favourite")
    per_mkt = int(p.get("max_trades_per_market", 1) or 0)
    per_mkt = 10 ** 9 if per_mkt <= 0 else per_mkt
    cool_ms = float(p.get("reentry_cooldown_secs") or 0) * 1000
    min_edge = float(p.get("min_model_edge", -1))
    use_fast = bool(p.get("use_fast"))
    decisions, reasons = [], {}
    total = int(len(sel))
    if progress:
        progress(0, total)
    for k_, m in enumerate(sel.sort_values("close_ts").itertuples()):
        if progress and (k_ % 50 == 0 or k_ == total - 1):
            progress(k_ + 1, total)
        mid = int(m.Index)
        a = obs.get(mid); ptb = ptbs.get(mid)
        if a is None or not ptb:
            continue
        if side_mode == "favourite":
            ask = np.where(a["fav_up"], a["up_ask"], a["down_ask"])
        elif side_mode == "underdog":
            ask = np.where(a["fav_up"], a["down_ask"], a["up_ask"])
        elif side_mode in ("up", "UP"):
            ask = a["up_ask"]
        elif side_mode == "predicted":            # either side may be bought: prefilter on the cheaper rule below
            ask = np.where((a["up_ask"] >= lo_p - 1e-9) & (a["up_ask"] <= hi_p + 1e-9), a["up_ask"], a["down_ask"])
        else:
            ask = a["down_ask"]
        secs = a["secs"]
        with np.errstate(invalid="ignore"):
            ok = (secs >= t_lo) & (secs <= t_hi) & (ask >= lo_p - 1e-9) & (ask <= hi_p + 1e-9)
            if min_edge > -1 and ok.any():
                n0 = int(ok.sum())
                ok &= _edge_upper_bound(a, float(ptb), use_fast, side_mode == "predicted", ask) >= min_edge - 1e-6
                reasons["model"] = reasons.get("model", 0) + n0 - int(ok.sum())
            idx = np.flatnonzero(ok)
        ts = a["ts"]; n = len(ts)
        n_here, free_ts = 0, -1
        for i in idx:
            i = int(i)
            if ts[i] <= free_ts:                              # still holding / cooling down in this market
                continue
            dcs, why = evaluate_custom(_state(m, a, i, ptb), p)
            if dcs is None:
                r_ = why.split(" ")[0] if why else "?"
                reasons[r_] = reasons.get(r_, 0) + 1
                continue
            j = i + 1                                         # next observation (~1 s later) = our fill
            while j < n and ts[j] <= ts[i]:
                j += 1
            if j >= n:
                break
            lv = _lv(a, "ua" if dcs.side == "UP" else "da", j)
            entry_px = next((px for px, _q in lv if px <= dcs.limit_price + 1e-9), dcs.limit_price)
            ex = _find_exit(p, a, dcs.side, j + 1, entry_px, m, ptb)
            decisions.append({"mid": mid, "asset": m.asset, "window": m.window, "ts": int(ts[i]),
                              "secs": float(secs[i]), "side": dcs.side, "ask": dcs.decision_ask, "limit": dcs.limit_price,
                              "fill_levels": lv, "close": int(m.close_ts), "won": m.winner == dcs.side, "z": dcs.reasons.get("z"),
                              "model": dcs.reasons.get("model_win_prob"), "exit": ex})
            n_here += 1
            if ex is None or n_here >= per_mkt:
                break
            free_ts = ex[1] + cool_ms
    # ---- chronological money simulation
    decisions.sort(key=lambda x: x["ts"])
    bal = start_balance
    open_pos, trades, curve = [], [], [{"ts": decisions[0]["ts"] if decisions else 0, "balance": start_balance}]
    day_stats = {}
    skipped = {"no depth at our price": 0, "stake too small": 0, "guard": 0}

    def settle_until(ts):
        nonlocal bal
        for pos in sorted([x for x in open_pos if x["exit_ts"] <= ts], key=lambda x: x["exit_ts"]):
            bal += pos["proceeds"]
            open_pos.remove(pos)
            pos["trade"]["balance_after"] = round(bal, 2)
            ds = day_stats.setdefault(pos["day"], {"pnl": 0.0, "losses": 0, "trades": 0, "start": None})
            ds["pnl"] += pos["trade"]["pnl"]
            ds["losses"] += 1 if pos["trade"]["pnl"] < 0 else 0
            curve.append({"ts": pos["exit_ts"], "balance": round(bal + sum(x["cost"] for x in open_pos), 2)})

    for dcs in decisions:
        settle_until(dcs["ts"])
        day = datetime.fromtimestamp(dcs["ts"] / 1000, AMS).date().isoformat()
        ds = day_stats.setdefault(day, {"pnl": 0.0, "losses": 0, "trades": 0, "start": None})
        if ds["start"] is None:
            ds["start"] = bal + sum(x["cost"] for x in open_pos)
        equity = bal + sum(x["cost"] for x in open_pos)
        g_ok = True
        if int(p.get("max_open_positions") or 0) and len(open_pos) >= int(p["max_open_positions"]):
            g_ok = False
        if int(p.get("max_trades_per_day") or 0) and ds["trades"] >= int(p["max_trades_per_day"]):
            g_ok = False
        if int(p.get("max_losses_per_day") or 0) and ds["losses"] >= int(p["max_losses_per_day"]):
            g_ok = False
        if float(p.get("daily_loss_limit_pct") or 0) and -ds["pnl"] >= ds["start"] * float(p["daily_loss_limit_pct"]) / 100:
            g_ok = False
        if float(p.get("daily_profit_cap_pct") or 0) and ds["pnl"] >= ds["start"] * float(p["daily_profit_cap_pct"]) / 100:
            g_ok = False
        if not g_ok:
            skipped["guard"] += 1
            continue
        stake = min(stake_usd(p, equity), bal)
        shares = math.floor(stake / dcs["limit"] * 100) / 100
        if shares < 5 or shares * dcs["limit"] < 1:
            skipped["stake too small"] += 1
            continue
        got, gross = 0.0, 0.0
        for px, q in dcs["fill_levels"]:
            if px > dcs["limit"] + 1e-9:
                break
            take = min(q, shares - got); got += take; gross += take * px
            if got >= shares - 1e-9:
                break
        if got < 5 or gross < 1:
            skipped["no depth at our price"] += 1
            continue
        avg = gross / got
        fee = taker_fee(got, avg, FEE)
        cost = gross + fee
        bal -= cost
        ds["trades"] += 1
        # exits
        proceeds, how, exit_ts, sold_at = None, None, dcs["close"], None
        if dcs["exit"]:
            how, exit_ts, sold_at = dcs["exit"]
            proceeds = got * sold_at - taker_fee(got, sold_at, FEE)
        if proceeds is None:
            proceeds = got if dcs["won"] else 0.0
            how = "won" if dcs["won"] else "lost"
        tr = {"time": dcs["ts"], "coin": dcs["asset"], "window": dcs["window"], "side": dcs["side"], "secs_left": round(dcs["secs"]),
              "price": round(avg, 4), "shares": round(got, 2), "cost": round(cost, 4), "fee": round(fee, 4),
              "result": how, "payout": round(proceeds, 4), "pnl": round(proceeds - cost, 4), "z": None if dcs["z"] is None else round(dcs["z"], 2),
              "model": None if dcs["model"] is None else round(dcs["model"], 3), "would_have_won": dcs["won"], "balance_after": None,
              "sold_at": None if sold_at is None else round(sold_at, 3), "held_secs": round((exit_ts - dcs["ts"]) / 1000)}
        trades.append(tr)
        open_pos.append({"exit_ts": exit_ts, "proceeds": proceeds, "cost": cost, "trade": tr, "day": day})
    settle_until(10 ** 15)
    T = pd.DataFrame(trades)
    out = {"start_balance": start_balance, "end_balance": round(bal, 2), "markets_tested": int(len(sel)),
           "first_ts": int(sel.open_ts.min()) if len(sel) else None, "last_ts": int(sel.close_ts.max()) if len(sel) else None,
           "trades": int(len(T)), "skipped": skipped, "filter_reasons": dict(sorted(reasons.items(), key=lambda x: -x[1])[:8]),
           "curve": curve, "trade_list": trades[-500:][::-1],
           # how much data this test used (grows every 5 minutes as new markets finish)
           "markets_by_window": {w: int((sel.window == w).sum()) for w in ("5m", "15m")},
           "markets_with_signal": int(len({d_["mid"] for d_ in decisions})),
           "data_updated_ts": int(_cache["ts"] * 1000) if _cache["ts"] else None,
           "all_recorded": status()}
    if len(T):
        bal_series = pd.Series([c["balance"] for c in curve])
        streak = best = 0
        for x in T.pnl:
            streak = streak + 1 if x < 0 else 0; best = max(best, streak)
        hours = max((out["last_ts"] - out["first_ts"]) / 3_600_000, 0.01)
        wins_ = T[T.pnl > 0]; losses_ = T[T.pnl <= 0]
        out.update({"wins": int(len(wins_)), "losses": int(len(losses_)), "win_rate": round(len(wins_) / len(T), 4),
                    "pnl": round(bal - start_balance, 2), "return_pct": round((bal / start_balance - 1) * 100, 2),
                    "hours": round(hours, 1), "per_day_pct": round(((bal / start_balance) ** (24 / hours) - 1) * 100, 2) if bal > 0 else -100,
                    "avg_win": round(float(wins_.pnl.mean()), 3) if len(wins_) else 0, "avg_loss": round(float(losses_.pnl.mean()), 3) if len(losses_) else 0,
                    "biggest_loss": round(float(T.pnl.min()), 3), "fees": round(float(T.fee.sum()), 3),
                    "avg_price": round(float(T.price.mean()), 4), "avg_return_per_win_x": round(float((1 / wins_.price).mean()), 4) if len(wins_) else None,
                    "max_drawdown": round(float((bal_series - bal_series.cummax()).min()), 2), "longest_losing_streak": int(best),
                    "by_coin": T.groupby("coin").pnl.agg(["count", "sum"]).round(2).reset_index().rename(columns={"count": "trades", "sum": "pnl"}).to_dict("records"),
                    "by_result": T.groupby("result").pnl.agg(["count", "sum"]).round(2).reset_index().rename(columns={"count": "trades", "sum": "pnl"}).to_dict("records")})
    if len(_results) > 50:
        _results.clear()
    _results[key] = (D, out)
    return out


# ---------------- background test jobs (so the app can show "market X of Y")
import uuid
from concurrent.futures import ThreadPoolExecutor

_pool = ThreadPoolExecutor(max_workers=2)
JOBS: dict[str, dict] = {}


def start_job(params: dict, start_balance: float = 100.0, days: float | None = None) -> str:
    jid = uuid.uuid4().hex[:12]
    st = status()
    JOBS[jid] = {"done": False, "stage": "loading data" if not st.get("loaded") else "testing", "current": 0,
                 "total": st.get("markets") or 0, "result": None, "error": None, "started": time.time()}

    def prog(i, n):
        JOBS[jid].update(stage="testing", current=i, total=n)

    def work():
        try:
            JOBS[jid]["result"] = run(params, start_balance, days, progress=prog)
        except Exception as e:  # pragma: no cover - surfaced to the UI
            JOBS[jid]["error"] = str(e)
        finally:
            JOBS[jid]["done"] = True
            JOBS[jid]["current"] = JOBS[jid]["total"]
        # forget old jobs
        for k in [k for k, v in JOBS.items() if v["done"] and time.time() - v["started"] > 1800]:
            JOBS.pop(k, None)

    _pool.submit(work)
    return jid


def job(jid: str) -> dict | None:
    j = JOBS.get(jid)
    if j is None:
        return None
    out = {k: j[k] for k in ("done", "stage", "current", "total", "error")}
    if j["done"]:
        out["result"] = j["result"]
    return out
