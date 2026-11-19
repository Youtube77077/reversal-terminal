"""Custom strategies built in the Strategy Builder (strategy key "X").

One generic, fully parameterised rule. The SAME function is used live (engine) and in the
backtest (services.custom_backtest), so test results and live paper trading are comparable.

Parameters (all optional; defaults in DEFAULTS):
  side              favourite | underdog | up | down | predicted (side the fast exchange prices say is
                    worth more than Polymarket's price right now = biggest model edge)
  min_price/max_price   ask range we are willing to pay (0-1)
  entry_min_secs/entry_max_secs   only buy while this many seconds are left
  z_min / z_max     safety margin of OUR side vs the price to beat, in standard deviations of the
                    expected move (60-second-average settlement rule). 0 = off.
  min_model_edge    model win chance - (price + fee) must be >= this (None/-1 = off)
  model_max         skip if the model's chance is above this (feeds disagree) - 1 = off
  momentum_filter   skip if the last 10s move is against our side by > momentum_mult x normal
  blackout          skip weekdays 14:25-14:45 Europe/Amsterdam (US data releases)
  stake_mode        percent | fixed      stake_value  (% of balance or $)
  max_loss_pct      LOSS PROTECTION: a full loss on one trade may cost at most this % of balance
  min_order_usd / max_order_usd
  take_profit_price sell early when our bid reaches this (0 = hold to the end)
  stop_price/z_stop sell early if bid <= stop_price AND safety margin z < z_stop (0 = off)
  take_profit_cents sell once profit per share AFTER both fees reaches this many cents (0 = off)
  stop_loss_cents   sell once the loss per share after fees reaches this many cents (0 = off)
  max_trades_per_market  buy again in the same market after selling (0 = unlimited); one open trade per market at a time
  reentry_cooldown_secs  wait this long after selling before buying again in that market
  max_open_positions, max_trades_per_day, max_losses_per_day, daily_loss_limit_pct, daily_profit_cap_pct
  windows           ["5m"] / ["15m"] / both;  assets: [] = all coins
"""
from __future__ import annotations

import math
from datetime import datetime
from zoneinfo import ZoneInfo

from ..providers.polymarket.fees import taker_fee

AMS = ZoneInfo("Europe/Amsterdam")

DEFAULTS = {
    "side": "favourite", "min_price": 0.90, "max_price": 0.95, "entry_min_secs": 30.0, "entry_max_secs": 90.0,
    "z_min": 3.0, "z_max": 0.0, "min_model_edge": -1.0, "model_max": 1.0, "momentum_filter": True, "momentum_mult": 2.0,
    "blackout": True, "use_fast": True, "stake_mode": "percent", "stake_value": 5.0, "max_loss_pct": 5.0,
    "min_order_usd": 1.0, "max_order_usd": 750.0, "limit_offset_ticks": 0, "take_profit_price": 0.0,
    "stop_price": 0.0, "z_stop": 1.0, "max_open_positions": 3, "max_trades_per_day": 0, "max_losses_per_day": 3,
    "daily_loss_limit_pct": 15.0, "daily_profit_cap_pct": 0.0, "windows": ["5m"], "assets": [],
    "take_profit_cents": 0.0, "stop_loss_cents": 0.0, "max_trades_per_market": 1, "reentry_cooldown_secs": 5.0,
    "order_type": "marketable_limit", "tif": "FAK",
}

LABELS = {
    "side": "Which side to buy", "min_price": "Lowest price to pay", "max_price": "Highest price to pay",
    "entry_min_secs": "Stop buying when fewer than … seconds are left", "entry_max_secs": "Start buying with … seconds left",
    "z_min": "Minimum safety margin (z)", "z_max": "Maximum safety margin (z)", "min_model_edge": "Minimum model edge",
    "model_max": "Skip if model chance above", "momentum_filter": "Skip if price is moving against us",
    "momentum_mult": "…moving more than × normal", "blackout": "Skip 14:25–14:45 weekdays (US news)",
    "use_fast": "Use fast exchange prices", "stake_mode": "Stake type", "stake_value": "Stake",
    "max_loss_pct": "Max loss per trade (% of balance)", "min_order_usd": "Min order $", "max_order_usd": "Max order $",
    "limit_offset_ticks": "May pay … ticks more", "take_profit_price": "Sell early at", "stop_price": "Stop-loss price",
    "z_stop": "…only if safety margin below", "max_open_positions": "Max open trades at once",
    "max_trades_per_day": "Max trades per day (0 = no limit)", "max_losses_per_day": "Stop for the day after … losses",
    "daily_loss_limit_pct": "Stop for the day after losing …%", "daily_profit_cap_pct": "Stop for the day after gaining …% (0 = off)",
    "windows": "Markets", "assets": "Coins",
    "take_profit_cents": "Take profit: + … ¢ per share after fees", "stop_loss_cents": "Stop-loss: − … ¢ per share after fees",
    "max_trades_per_market": "Max trades per market (0 = unlimited)", "reentry_cooldown_secs": "Wait … s before buying again",
}


def merged(params: dict | None) -> dict:
    p = dict(DEFAULTS)
    p.update({k: v for k, v in (params or {}).items() if v is not None})
    return p


def safety_z(st, side: str, use_fast: bool = True) -> float | None:
    """How many standard deviations the price must move (before settlement) for `side` to LOSE.

    Settlement = average of the last 60 s vs the price to beat P.
      t <= 60: f = (60-t)/60 of the window is known (average L). Final A = f*L + (1-f)*R.
               Flip needs R past R* = (P - f*L)/(1-f).  Spread of R ~ sigma*S*sqrt(t/3).
      t > 60 : the whole window is ahead; add drift variance sigma^2*S^2*(t-60).
    Positive = our side is currently winning by that many std; <= 0 = currently losing.
    """
    f_ = st.features
    S = (f_.get("fast_spot") if use_fast else None) or f_.get("spot")
    P = st.open_price
    vol = f_.get("vol_30s")
    t = st.secs_remaining
    if not S or not P or vol is None or t <= 0:
        return None
    sig = max(float(vol), 0.05) * 1e-4
    if t <= 60:
        f = (60 - t) / 60
        L = f_.get("twap_window") or S
        rstar = (P - f * L) / max(1 - f, 1e-6)
        std = sig * S * math.sqrt(max(t, 0.5) / 3)
    else:
        rstar = P
        std = math.sqrt((sig * S) ** 2 * (t - 60) + (sig * S) ** 2 * 20)
    dist = (S - rstar) if side == "UP" else (rstar - S)
    return dist / std if std > 0 else None


def pick_side(st, p: dict) -> str | None:
    s = p.get("side", "favourite")
    if s in ("up", "UP"):
        return "UP"
    if s in ("down", "DOWN"):
        return "DOWN"
    ua, da = st.up_ask, st.down_ask
    if ua is None or da is None:
        return None
    fav = "UP" if ua >= da else "DOWN"
    return fav if s == "favourite" else ("DOWN" if fav == "UP" else "UP")


def predicted_side(st, p: dict) -> str | None:
    """The side whose model chance (from the fast exchange prices, ~2 s ahead of Polymarket) is furthest
    above its price + fee: the side Polymarket has not caught up with yet."""
    from .library import flip_probability
    pu = flip_probability(st, "UP", use_fast=bool(p.get("use_fast", True)))
    if pu is None:
        return None
    best, best_e = None, -9.0
    for side, pw in (("UP", pu), ("DOWN", 1.0 - pu)):
        ask = st.ask(side)
        if ask is None or not 0 < ask < 1:
            continue
        e = pw - ask - taker_fee(1.0, ask, st.fee)
        if e > best_e:
            best, best_e = side, e
    return best


def scalp_exit(p: dict, entry_px: float, bid: float, fee) -> str | None:
    """Relative exits: profit / loss per share AFTER the buy fee and the sell fee."""
    tpc, slc = float(p.get("take_profit_cents") or 0) / 100, float(p.get("stop_loss_cents") or 0) / 100
    if tpc <= 0 and slc <= 0:
        return None
    net = bid - taker_fee(1.0, bid, fee) - (entry_px + taker_fee(1.0, entry_px, fee))
    if tpc > 0 and net >= tpc - 1e-9:
        return "take profit"
    if slc > 0 and net <= -slc + 1e-9:
        return "stop"
    return None


def in_blackout(ts_ms: int) -> bool:
    x = datetime.fromtimestamp(ts_ms / 1000, AMS)
    return x.weekday() < 5 and (14, 25) <= (x.hour, x.minute) < (14, 45)


def evaluate_custom(st, params: dict, diag: dict | None = None):
    """Return (Decision, None) or (None, reason). Imports Decision lazily to avoid a cycle."""
    from .library import Decision, _round_tick, flip_probability, size_order
    p = merged(params)
    secs = st.secs_remaining
    if not (float(p["entry_min_secs"]) <= secs <= float(p["entry_max_secs"])):
        return None, "outside entry window"
    if not st.book_ok:
        return None, "order book not ready"
    if p.get("side") == "predicted":
        side = predicted_side(st, p)
        if side is None:
            return None, "no prediction yet (missing price data)"
    else:
        side = pick_side(st, p)
    if side is None:
        return None, "no prices"
    ask = st.ask(side)
    if ask is None:
        return None, f"no sellers for {side}"
    if not (float(p["min_price"]) - 1e-9 <= ask <= float(p["max_price"]) + 1e-9):
        return None, f"{side} ask {ask:.3f} outside {p['min_price']}-{p['max_price']}"
    if p.get("blackout") and in_blackout(st.server_ts):
        return None, "news blackout window"
    z = safety_z(st, side, bool(p.get("use_fast")))
    if float(p.get("z_min") or 0) > 0 and (z is None or z < float(p["z_min"])):
        return None, f"safety margin z {z if z is None else round(z, 2)} < {p['z_min']}"
    if float(p.get("z_max") or 0) > 0 and z is not None and z > float(p["z_max"]):
        return None, f"safety margin z {z:.2f} > {p['z_max']}"
    if p.get("momentum_filter"):
        f_ = st.features
        m10, vol, S = f_.get("mom_10s"), f_.get("vol_30s"), f_.get("spot")
        if m10 is not None and vol and S:
            against = -m10 if side == "UP" else m10
            if against > float(p.get("momentum_mult", 2.0)) * max(vol, 0.05) * 1e-4 * S * math.sqrt(10):
                return None, "price moving fast against our side"
    tick = st.tick_size or 0.01
    limit = _round_tick(min(float(p["max_price"]), ask + int(p.get("limit_offset_ticks") or 0) * tick), tick)
    limit = max(limit, ask)
    stake = float(p["stake_value"]) if p.get("stake_mode") == "fixed" else float(p.get("min_order_usd") or 1.0)
    shares = size_order(max(stake, 1.0), limit, st.min_order_size)
    fee_ps = taker_fee(shares, limit, st.fee) / shares if shares else 0.0
    pw = flip_probability(st, side, use_fast=bool(p.get("use_fast")))
    edge = (pw - limit - fee_ps) if pw is not None else None
    if diag is not None:
        diag.update({"side": side, "ask": ask, "model_prob": pw, "breakeven": limit + fee_ps,
                     "edge": edge if edge is not None else -9, "secs": secs, "z": z})
    if float(p.get("min_model_edge", -1)) > -1:
        if edge is None or edge < float(p["min_model_edge"]):
            return None, f"model edge {edge if edge is None else round(edge, 3)} < {p['min_model_edge']}"
    if float(p.get("model_max", 1)) < 1 and pw is not None and pw > float(p["model_max"]):
        return None, f"model {pw:.0%} above cap {p['model_max']}"
    liq = st.ask_liquidity_usd(side, max_price=limit)
    if liq < 1.0:
        return None, "not enough sellers at our price"
    reasons = {"side": side, "ask": ask, "limit": limit, "z": z, "model_win_prob": pw, "edge": edge,
               "secs_remaining": secs, "liq_usd": liq, "custom": True}
    cost = shares * (limit + fee_ps)
    exp = {"max_cost": cost, "payout_if_win": shares, "breakeven_prob": limit + fee_ps,
           "model_win_prob": pw, "take_profit_price": float(p.get("take_profit_price") or 0)}
    return Decision(side=side, limit_price=limit, shares=shares, order_type=p["order_type"], tif=p["tif"],
                    decision_ask=ask, reasons=reasons, expected=exp), None


def stake_usd(p: dict, balance: float) -> float:
    """Stake for the next trade. Depends ONLY on the current balance and the settings
    (never on recent wins/losses: no martingale, no chasing). Capped by max_loss_pct so a
    full loss can never cost more than that share of the balance."""
    p = merged(p)
    raw = float(p["stake_value"]) if p.get("stake_mode") == "fixed" else balance * float(p["stake_value"]) / 100.0
    cap = balance * float(p.get("max_loss_pct") or 100) / 100.0
    return max(0.0, min(raw, cap, float(p.get("max_order_usd") or 1e9)))
