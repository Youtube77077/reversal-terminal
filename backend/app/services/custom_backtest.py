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
from ..strategies.custom import AMS, evaluate_custom, merged, safety_z, stake_usd
from .market_state import MarketState

_cache: dict = {"ts": 0.0, "data": None}
_lock = threading.Lock()
FEE = FeeSchedule()


def _load() -> dict:
    mk = pd.read_sql(text("SELECT id, asset, slug, open_ts, close_ts, winner, price_to_beat, COALESCE(window,'5m') AS window "
                          "FROM markets WHERE status='resolved' AND winner IN ('UP','DOWN')"), engine)
    if mk.empty:
        return {"markets": mk, "obs": {}}
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
        ptb[r.id] = v
    obs = {}
    for mid, g in ob.groupby("market_id"):
        g = g.reset_index(drop=True)
        close = int(mk.loc[mk.id == mid, "close_ts"].iloc[0])
        inwin = g.server_ts > close - 60_000
        sp = g.spot.where(inwin)
        cs = sp.fillna(0).cumsum(); cn = sp.notna().cumsum()
        g["tw"] = np.where(g.twap_window.notna(), g.twap_window, np.where(cn > 0, cs / cn.replace(0, np.nan), np.nan))
        obs[mid] = g
    return {"markets": mk.set_index("id"), "obs": obs, "ptb": ptb}


def data(force: bool = False) -> dict:
    with _lock:
        if force or _cache["data"] is None or time.time() - _cache["ts"] > 900:   # background refresh keeps it fresh
            _cache["data"] = _load()
            _cache["ts"] = time.time()
        return _cache["data"]


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


def _state(m, row, ptb) -> MarketState:
    ua, da = _levels(row.up_asks_json), _levels(row.down_asks_json)
    st = MarketState(market_id=int(row.market_id), asset=m.asset, slug=m.slug, condition_id=None, up_token="u", down_token="d",
                     open_ts=int(m.open_ts), close_ts=int(m.close_ts), server_ts=int(row.server_ts),
                     secs_remaining=float(row.secs_remaining), open_price=ptb, fee=FEE, min_order_size=5.0, tick_size=0.01,
                     up_bid=row.up_bid if row.up_bid == row.up_bid else None, up_ask=row.up_ask if row.up_ask == row.up_ask else None,
                     down_bid=row.down_bid if row.down_bid == row.down_bid else None,
                     down_ask=row.down_ask if row.down_ask == row.down_ask else None,
                     up_asks=ua, down_asks=da, book_ok=True, spot_ok=True, window=m.window,
                     features={"spot": row.spot, "fast_spot": row.fast_spot if row.fast_spot == row.fast_spot else None,
                               "twap_window": row.tw if row.tw == row.tw else None, "vol_30s": row.vol_30s if row.vol_30s == row.vol_30s else None,
                               "mom_10s": row.mom_10s if row.mom_10s == row.mom_10s else None, "ptb_exact": True})
    if st.up_bid is not None:
        st.up_bids = [(st.up_bid, (row.up_bid_liq or 0) / max(st.up_bid, 0.01))]
    if st.down_bid is not None:
        st.down_bids = [(st.down_bid, (row.down_bid_liq or 0) / max(st.down_bid, 0.01))]
    return st


def run(params: dict, start_balance: float = 100.0, days: float | None = None) -> dict:
    p = merged(params)
    D = data()
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
    decisions, reasons = [], {}
    for mid, m in sel.sort_values("close_ts").iterrows():
        g = obs.get(mid); ptb = ptbs.get(mid)
        if g is None or not ptb:
            continue
        w = g[(g.secs_remaining >= t_lo) & (g.secs_remaining <= t_hi)]
        if w.empty:
            continue
        fav_up = w.up_ask.fillna(0) >= w.down_ask.fillna(0)
        if side_mode == "favourite":
            ask = np.where(fav_up, w.up_ask, w.down_ask)
        elif side_mode == "underdog":
            ask = np.where(fav_up, w.down_ask, w.up_ask)
        elif side_mode in ("up", "UP"):
            ask = w.up_ask.to_numpy()
        else:
            ask = w.down_ask.to_numpy()
        cand = w[(ask >= lo_p - 1e-9) & (ask <= hi_p + 1e-9)]
        for row in cand.itertuples():
            st = _state(m, row, ptb)
            dcs, why = evaluate_custom(st, p)
            if dcs is None:
                reasons[why.split(" ")[0] if why else "?"] = reasons.get(why.split(" ")[0] if why else "?", 0) + 1
                continue
            nxt = g[g.server_ts > row.server_ts].head(1)
            if nxt.empty:
                break
            decisions.append({"mid": mid, "asset": m.asset, "window": m.window, "ts": int(row.server_ts),
                              "secs": float(row.secs_remaining), "side": dcs.side, "ask": dcs.decision_ask, "limit": dcs.limit_price,
                              "fill_levels": _levels(nxt.iloc[0].up_asks_json if dcs.side == "UP" else nxt.iloc[0].down_asks_json),
                              "close": int(m.close_ts), "won": m.winner == dcs.side, "z": dcs.reasons.get("z"),
                              "model": dcs.reasons.get("model_win_prob"), "after": g[g.server_ts > nxt.iloc[0].server_ts], "m": m, "ptb": ptb})
            break
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
        tp, sp, zs = float(p.get("take_profit_price") or 0), float(p.get("stop_price") or 0), float(p.get("z_stop") or 0)
        proceeds, how, exit_ts = None, None, dcs["close"]
        if 0 < tp < 1 or 0 < sp < 1:
            for r in dcs["after"].itertuples():
                bid = r.up_bid if dcs["side"] == "UP" else r.down_bid
                if bid != bid or bid is None:
                    continue
                if 0 < tp < 1 and bid >= tp:
                    proceeds, how, exit_ts = got * bid - taker_fee(got, bid, FEE), "sold early (take profit)", int(r.server_ts); break
                if 0 < sp < 1 and bid <= sp:
                    z = safety_z(_state(dcs["m"], r, dcs["ptb"]), dcs["side"], bool(p.get("use_fast")))
                    if z is None or z < zs:
                        proceeds, how, exit_ts = got * bid - taker_fee(got, bid, FEE), "stop-loss", int(r.server_ts); break
        if proceeds is None:
            proceeds = got if dcs["won"] else 0.0
            how = "won" if dcs["won"] else "lost"
        tr = {"time": dcs["ts"], "coin": dcs["asset"], "window": dcs["window"], "side": dcs["side"], "secs_left": round(dcs["secs"]),
              "price": round(avg, 4), "shares": round(got, 2), "cost": round(cost, 4), "fee": round(fee, 4),
              "result": how, "payout": round(proceeds, 4), "pnl": round(proceeds - cost, 4), "z": None if dcs["z"] is None else round(dcs["z"], 2),
              "model": None if dcs["model"] is None else round(dcs["model"], 3), "would_have_won": dcs["won"], "balance_after": None}
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
           "markets_with_signal": int(len(decisions)),
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
    return out
