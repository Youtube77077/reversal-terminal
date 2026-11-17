"""Strategy library (A–J). Every strategy buys the cheap (underdog) outcome.

Strategies only *propose* trades. Sizing limits, funds and risk controls are
enforced afterwards by the engine at account level and cannot be bypassed.
Each strategy is independently configurable through its params dict and is
run on its own paper account so its statistics stay separate.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable

from ..constants import CHECKPOINTS
from ..providers.polymarket.fees import taker_fee
from ..services.market_state import MarketState
from ..services.statistics import wilson_interval

COMMON_DEFAULTS = {
    "stake_usd": 1.0,              # target notional per trade (>= $1 CLOB minimum for marketable orders)
    "entry_min_secs": 1.0,
    "entry_max_secs": 30.0,
    "max_price": 0.10,             # max underdog ask
    "limit_offset_ticks": 0,       # 0 = never pay more than the decision ask
    "order_type": "marketable_limit",  # or passive_limit
    "tif": "FAK",
    "passive_fill_rule": "trade_through",
}

STRATEGIES: dict[str, dict] = {
    "A": {"name": "Cheapest Outcome", "description": "Buy the cheaper outcome when its ask is below a configurable price.",
          "params": {"max_price": 0.05}},
    "B": {"name": "Extreme Probability", "description": "Only trade when the favourite's implied probability exceeds a "
                                                       "threshold (95/97/98/99%).",
          "params": {"min_fav_prob": 0.97, "max_price": 0.05}},
    "C": {"name": "Settlement Proximity", "description": "Trade only when the underlying is close to the settlement "
                                                        "threshold (opening reference price).",
          "params": {"max_dist_bps": 3.0, "max_price": 0.10}},
    "D": {"name": "Price Momentum", "description": "Require the underlying to be moving towards the threshold "
                                                  "(i.e. in the underdog's favour).",
          "params": {"momentum_horizon": "mom_10s", "min_momentum_bps": 0.5, "max_price": 0.10}},
    "E": {"name": "Momentum Acceleration", "description": "Detect rapid acceleration of short-term price movement "
                                                         "in the underdog's favour.",
          "params": {"min_accel_bps": 1.0, "max_price": 0.10}},
    "F": {"name": "Time-Based Entry", "description": "Enter at one exact checkpoint (T-30/15/10/5/3/1) to compare "
                                                    "entry timing.",
          "params": {"entry_t": 10, "max_price": 0.10}},
    "G": {"name": "Liquidity Filter", "description": "Require a minimum executable liquidity at or below the limit price.",
          "params": {"min_liquidity_usd": 10.0, "max_price": 0.10}},
    "H": {"name": "Spread Filter", "description": "Reject opportunities where the underdog spread is too wide.",
          "params": {"max_spread": 0.02, "max_price": 0.10}},
    "I": {"name": "Statistical Edge", "description": "Trade only when the historical observed underdog win rate exceeds "
                                                    "the fee-adjusted break-even probability by a margin "
                                                    "(uses only data available before the decision).",
          "params": {"min_edge": 0.01, "min_sample": 50, "use_lower_ci": True, "max_price": 0.20}},
    "J": {"name": "Combined", "description": "Probability + momentum + settlement distance + liquidity + historical "
                                           "reversal statistics.",
          "params": {"min_fav_prob": 0.90, "max_dist_bps": 5.0, "min_liquidity_usd": 5.0, "max_spread": 0.03,
                     "require_momentum": True, "min_edge": 0.0, "min_sample": 30, "max_price": 0.10}},
    "K": {"name": "Favourite Carry", "description": "Buy the favourite late when it is very likely to win and the price "
                                                    "is clearly away from the line.",
          "params": {"stake_usd": 5.0, "min_fav_prob": 0.95, "min_price": 0.90, "max_price": 0.98, "min_dist_bps": 2.0,
                     "min_liquidity_usd": 5.0}},
    "L": {"name": "Trend Rider", "description": "Buy the favourite mid-window (T-90..T-30) when 30 s momentum agrees.",
          "params": {"stake_usd": 5.0, "entry_min_secs": 30.0, "entry_max_secs": 90.0, "min_fav_prob": 0.80, "max_fav_prob": 0.95,
                     "min_price": 0.75, "max_price": 0.95, "momentum_horizon": "mom_30s", "min_momentum_bps": 1.0}},
    "M": {"name": "Statistical Favourite", "description": "Buy the favourite only when its historical win rate "
                                                          "(pessimistic 95% bound) beats price + fee.",
          "params": {"stake_usd": 5.0, "min_price": 0.85, "max_price": 0.99, "min_edge": 0.0, "min_sample": 50, "use_lower_ci": True}},
}

FAVOURITE_KEYS = {"K", "L", "M"}


def default_params(key: str) -> dict:
    p = dict(COMMON_DEFAULTS)
    p.update(STRATEGIES[key]["params"])
    return p


@dataclass
class Decision:
    side: str
    limit_price: float
    shares: float
    order_type: str
    tif: str
    decision_ask: float
    reasons: dict = field(default_factory=dict)
    expected: dict = field(default_factory=dict)


@dataclass
class StrategyContext:
    """Information available at decision time (no look-ahead)."""
    hist_lookup: Callable[[str, int, float], tuple[int, int]] | None = None  # (asset, t_minus, price) -> (wins, n)


def nearest_checkpoint(secs: float) -> int:
    return min(CHECKPOINTS, key=lambda c: abs(c - secs))


def _round_tick(p: float, tick: float) -> float:
    return round(round(p / tick) * tick, 6)


def size_order(stake: float, limit: float, min_shares: float, min_notional: float = 1.0) -> float:
    """Shares for a target stake, rounded UP to 0.01 so notional never falls below the stake / $1 CLOB minimum."""
    target = max(stake, min_notional)
    shares = math.ceil(round(target / limit * 100, 6)) / 100.0
    return max(shares, min_shares)


def evaluate(key: str, st: MarketState, params: dict, ctx: StrategyContext) -> tuple[Decision | None, str | None]:
    """Return (decision, None) to trade, or (None, reason) when conditions are not met."""
    p = {**default_params(key), **(params or {})}
    secs = st.secs_remaining
    if key in FAVOURITE_KEYS:
        return _evaluate_favourite(key, st, p, ctx)
    if key == "F":
        t = float(p["entry_t"])
        if abs(secs - t) > 0.5:
            return None, "outside entry second"
    elif not (p["entry_min_secs"] <= secs <= p["entry_max_secs"]):
        return None, "outside entry window"
    if not st.book_ok:
        return None, "book not synced"
    fav, dog = st.favourite, st.underdog
    if fav is None or dog is None:
        return None, "no favourite"
    ask = st.ask(dog)
    if ask is None:
        return None, "underdog has no asks"
    if ask > p["max_price"] + 1e-12:
        return None, f"underdog ask {ask} > max {p['max_price']}"
    fav_prob = st.fav_prob or 0.0
    tick = st.tick_size or 0.01
    limit = _round_tick(min(0.99, ask + p["limit_offset_ticks"] * tick), tick)
    if limit <= 0:
        return None, "invalid limit"
    shares = size_order(p["stake_usd"], limit, st.min_order_size)
    liq = st.ask_liquidity_usd(dog, max_price=limit)
    spread = st.spread(dog)
    dist = st.dist_bps
    mom_toward = st.momentum_toward(dog, p.get("momentum_horizon", "mom_10s"))
    reasons = {"fav": fav, "fav_prob": fav_prob, "dog": dog, "dog_ask": ask, "limit": limit, "liq_usd": liq,
               "spread": spread, "dist_bps": dist, "mom_toward_dog": mom_toward, "secs_remaining": secs}

    hist = None
    if ctx.hist_lookup and key in ("I", "J"):
        k, n = ctx.hist_lookup(st.asset, nearest_checkpoint(secs), ask)
        hist = (k, n)
        reasons["hist_wins"], reasons["hist_n"] = k, n

    if key == "B" and fav_prob < p["min_fav_prob"]:
        return None, f"favourite prob {fav_prob:.3f} < {p['min_fav_prob']}"
    if key == "C":
        if dist is None:
            return None, "no settlement distance (missing spot/open price)"
        if abs(dist) > p["max_dist_bps"]:
            return None, f"distance {abs(dist):.2f}bp > {p['max_dist_bps']}bp"
    if key == "D":
        m = st.features.get(p["momentum_horizon"])
        if m is None or not st.open_price:
            return None, "no momentum data"
        m_bps = m / st.open_price * 1e4
        toward = (m_bps > 0) if dog == "UP" else (m_bps < 0)
        if not toward or abs(m_bps) < p["min_momentum_bps"]:
            return None, f"momentum {m_bps:.2f}bp not toward underdog by {p['min_momentum_bps']}bp"
        reasons["momentum_bps"] = m_bps
    if key == "E":
        a = st.features.get("accel")
        m5 = st.features.get("mom_5s")
        if a is None or m5 is None or not st.open_price:
            return None, "no acceleration data"
        a_bps = a / st.open_price * 1e4
        toward = (a_bps > 0 and m5 > 0) if dog == "UP" else (a_bps < 0 and m5 < 0)
        if not toward or abs(a_bps) < p["min_accel_bps"]:
            return None, f"acceleration {a_bps:.2f}bp not toward underdog"
        reasons["accel_bps"] = a_bps
    if key == "G" and liq < p["min_liquidity_usd"]:
        return None, f"liquidity ${liq:.2f} < ${p['min_liquidity_usd']}"
    if key == "H" and (spread is None or spread > p["max_spread"] + 1e-12):
        return None, f"spread {spread} > {p['max_spread']}"

    fee_ps = taker_fee(shares, limit, st.fee) / shares if shares else 0.0
    breakeven = limit + fee_ps
    reasons["breakeven"] = breakeven

    if key in ("I", "J"):
        if not hist or hist[1] < p["min_sample"]:
            return None, f"historical sample {hist[1] if hist else 0} < {p['min_sample']}"
        k, n = hist
        lo, _hi = wilson_interval(k, n)
        p_hat = (lo if p.get("use_lower_ci", key == "I") else k / n) or 0.0
        reasons["hist_p"] = p_hat
        if p_hat - breakeven < p["min_edge"]:
            return None, f"historical edge {p_hat - breakeven:+.4f} < {p['min_edge']}"
    if key == "J":
        if fav_prob < p["min_fav_prob"]:
            return None, f"favourite prob {fav_prob:.3f} < {p['min_fav_prob']}"
        if dist is None or abs(dist) > p["max_dist_bps"]:
            return None, "settlement distance filter"
        if liq < p["min_liquidity_usd"]:
            return None, "liquidity filter"
        if spread is None or spread > p["max_spread"] + 1e-12:
            return None, "spread filter"
        if p["require_momentum"] and mom_toward is not True:
            return None, "momentum not toward underdog"

    cost = shares * limit + fee_ps * shares
    exp = {"max_cost": cost, "payout_if_win": shares, "net_if_win": shares - cost, "net_if_loss": -cost,
           "breakeven_prob": breakeven}
    if hist and hist[1] > 0:
        pw = hist[0] / hist[1]
        exp["hist_win_prob"] = pw
        exp["expected_value"] = pw * (shares - cost) - (1 - pw) * cost
    return Decision(side=dog, limit_price=limit, shares=shares, order_type=p["order_type"], tif=p["tif"],
                    decision_ask=ask, reasons=reasons, expected=exp), None


def _evaluate_favourite(key: str, st: MarketState, p: dict, ctx: StrategyContext) -> tuple[Decision | None, str | None]:
    """Strategies K/L/M buy the FAVOURITE (expensive side) instead of the underdog."""
    secs = st.secs_remaining
    if not (p["entry_min_secs"] <= secs <= p["entry_max_secs"]):
        return None, "outside entry window"
    if not st.book_ok:
        return None, "book not synced"
    fav, dog = st.favourite, st.underdog
    if fav is None:
        return None, "no favourite"
    ask = st.ask(fav)
    if ask is None:
        return None, "favourite has no asks"
    if ask > p["max_price"] + 1e-12 or ask < p.get("min_price", 0.0) - 1e-12:
        return None, f"favourite ask {ask} outside [{p.get('min_price', 0)}, {p['max_price']}]"
    fav_prob = st.fav_prob or 0.0
    if fav_prob < p.get("min_fav_prob", 0.0):
        return None, f"favourite prob {fav_prob:.3f} < {p.get('min_fav_prob')}"
    if "max_fav_prob" in p and fav_prob > p["max_fav_prob"]:
        return None, f"favourite prob {fav_prob:.3f} > {p['max_fav_prob']}"
    tick = st.tick_size or 0.01
    limit = _round_tick(min(0.99, ask + p["limit_offset_ticks"] * tick), tick)
    shares = size_order(p["stake_usd"], limit, st.min_order_size)
    liq = st.ask_liquidity_usd(fav, max_price=limit)
    dist = st.dist_bps
    reasons = {"fav": fav, "fav_prob": fav_prob, "side": "favourite", "fav_ask": ask, "limit": limit, "liq_usd": liq,
               "spread": st.spread(fav), "dist_bps": dist, "secs_remaining": secs}
    if key == "K":
        if dist is None or abs(dist) < p["min_dist_bps"]:
            return None, f"too close to the line ({dist} bp)"
        if liq < p["min_liquidity_usd"]:
            return None, f"liquidity ${liq:.2f} < ${p['min_liquidity_usd']}"
    if key == "L":
        m = st.features.get(p["momentum_horizon"])
        if m is None or not st.open_price:
            return None, "no momentum data"
        m_bps = m / st.open_price * 1e4
        agrees = (m_bps > 0) if fav == "UP" else (m_bps < 0)
        if not agrees or abs(m_bps) < p["min_momentum_bps"]:
            return None, f"momentum {m_bps:.2f}bp does not confirm the favourite"
        reasons["momentum_bps"] = m_bps
    fee_ps = taker_fee(shares, limit, st.fee) / shares if shares else 0.0
    breakeven = limit + fee_ps
    reasons["breakeven"] = breakeven
    exp = {"max_cost": shares * breakeven, "payout_if_win": shares, "net_if_win": shares - shares * breakeven,
           "net_if_loss": -shares * breakeven, "breakeven_prob": breakeven}
    if ctx.hist_lookup:
        dog_px = st.ask(dog) if dog and st.ask(dog) is not None else max(0.001, 1 - ask)
        k, n = ctx.hist_lookup(st.asset, nearest_checkpoint(secs), dog_px)
        reasons["hist_fav_wins"], reasons["hist_n"] = n - k, n
        if n:
            pw = (n - k) / n
            exp["hist_win_prob"] = pw
            exp["expected_value"] = pw * exp["net_if_win"] + (1 - pw) * exp["net_if_loss"]
        if key == "M":
            if n < p["min_sample"]:
                return None, f"historical sample {n} < {p['min_sample']}"
            lo, _ = wilson_interval(n - k, n)
            p_hat = (lo if p.get("use_lower_ci", True) else (n - k) / n) or 0.0
            if p_hat - breakeven < p["min_edge"]:
                return None, f"historical edge {p_hat - breakeven:+.4f} < {p['min_edge']}"
    return Decision(side=fav, limit_price=limit, shares=shares, order_type=p["order_type"], tif=p["tif"],
                    decision_ask=ask, reasons=reasons, expected=exp), None
