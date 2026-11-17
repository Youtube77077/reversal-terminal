"""Pure, deterministic order-execution simulation against an order book.

Used by the live paper engine (against the real-time book after a latency
delay) and by the backtester (against recorded book levels). Never assumes a
fill at the displayed price: it walks actual ask levels, respects the limit
price, minimum order size, minimum marketable notional and time-in-force.
"""
from __future__ import annotations

from ..providers.polymarket.fees import FeeSchedule, maker_fee, taker_fee
from ..services.orderbook import walk_asks
from .base import ExecutionReport, FillReport


def validate_order(limit_price: float, shares: float, min_shares: float, min_notional: float,
                   tick_size: float, marketable: bool) -> str | None:
    if shares <= 0:
        return "non-positive size"
    if not (0 < limit_price < 1):
        return "limit price outside (0, 1)"
    ticks = round(limit_price / tick_size)
    if abs(ticks * tick_size - limit_price) > 1e-9:
        return f"limit price {limit_price} not on tick {tick_size}"
    if shares + 1e-9 < min_shares:
        return f"size {shares:.2f} below market minimum {min_shares:g} shares"
    if marketable and limit_price * shares + 1e-9 < min_notional:
        return f"marketable order notional ${limit_price * shares:.2f} below ${min_notional:.2f} minimum"
    return None


def simulate_marketable_buy(asks: list[tuple[float, float]], limit_price: float, shares: float,
                            fee: FeeSchedule, tif: str = "FAK", min_shares: float = 5.0,
                            min_notional: float = 1.0, tick_size: float = 0.01) -> ExecutionReport:
    """Taker BUY that sweeps asks up to ``limit_price``.

    FAK (fill-and-kill): fills what is available, the remainder is cancelled.
    FOK (fill-or-kill): fills completely or not at all.
    """
    err = validate_order(limit_price, shares, min_shares, min_notional, tick_size, marketable=True)
    best = min((p for p, s in asks), default=None)
    if err:
        return ExecutionReport("failed", [], shares, reason=err, best_ask_at_execution=best)
    if best is None:
        return ExecutionReport("unfilled", [], shares, reason="no asks on book", best_ask_at_execution=None)
    if best > limit_price + 1e-12:
        return ExecutionReport("unfilled", [], shares, reason=f"best ask {best} above limit {limit_price}",
                               best_ask_at_execution=best)
    levels = walk_asks(asks, limit_price, shares)
    got = sum(l.shares for l in levels)
    if tif == "FOK" and got + 1e-9 < shares:
        return ExecutionReport("unfilled", [], shares,
                               reason=f"FOK killed: only {got:.2f}/{shares:.2f} shares available <= {limit_price}",
                               best_ask_at_execution=best)
    fills = [FillReport(price=l.price, shares=l.shares, fee=taker_fee(l.shares, l.price, fee), role="taker")
             for l in levels]
    status = "filled" if got + 1e-9 >= shares else "partially_filled"
    reason = None if status == "filled" else f"liquidity exhausted at limit: {got:.2f}/{shares:.2f} filled, rest cancelled"
    return ExecutionReport(status, fills, shares, reason=reason, best_ask_at_execution=best)


def simulate_passive_check(asks: list[tuple[float, float]], limit_price: float, remaining: float,
                           fee: FeeSchedule, rule: str = "trade_through") -> list[FillReport]:
    """Check whether a resting BUY at ``limit_price`` would have been filled.

    We cannot see our queue position in the real book, so we are conservative:

    * ``trade_through`` (default): fill only when sellers offer strictly BELOW our
      price, i.e. the market has clearly traded through our level.
    * ``touch``: fill when the best ask reaches our price (optimistic).

    Fills execute at our limit price as a maker (no taker fee when takerOnly).
    """
    eligible = [(p, s) for p, s in asks if (p < limit_price - 1e-12 if rule == "trade_through" else p <= limit_price + 1e-12)]
    avail = sum(s for _, s in eligible)
    take = min(avail, remaining)
    if take <= 1e-9:
        return []
    return [FillReport(price=limit_price, shares=take, fee=maker_fee(take, limit_price, fee), role="maker")]


def max_cost(limit_price: float, shares: float, fee: FeeSchedule) -> float:
    """Upper bound on cash needed (used to reserve funds before submission)."""
    return round(limit_price * shares + taker_fee(shares, limit_price, fee) + 1e-6, 6)
