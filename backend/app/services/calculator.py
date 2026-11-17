"""Profitability calculator — break-even includes every applicable cost."""
from __future__ import annotations

from ..constants import CALCULATOR_PRICES
from ..providers.polymarket.fees import FeeSchedule, taker_fee


def calculate(entry_price: float, investment: float | None = None, quantity: float | None = None,
              fee_override: float | None = None, slippage_per_share: float = 0.0, other_costs: float = 0.0,
              reversal_frequency: float | None = None, fee_rate: float = 0.07) -> dict:
    if not (0 < entry_price < 1):
        raise ValueError("entry price must be between 0 and 1")
    if quantity is None:
        if not investment or investment <= 0:
            raise ValueError("provide investment or quantity")
        quantity = investment / (entry_price + slippage_per_share)
    sched = FeeSchedule(rate=fee_rate, verified=True)
    fill_px = entry_price + slippage_per_share
    fee = fee_override if fee_override is not None else taker_fee(quantity, min(0.999, fill_px), sched)
    gross = quantity * entry_price
    slip = quantity * slippage_per_share
    total = gross + slip + fee + other_costs
    payout = quantity * 1.0
    net_win = payout - total
    net_loss = -total
    be = total / payout
    out = {
        "shares": quantity, "gross_cost": gross, "slippage": slip, "fee": fee,
        "fee_estimated": fee_override is None and False, "other_costs": other_costs, "total_cost": total,
        "payout_if_win": payout, "net_profit_if_win": net_win, "net_loss_if_lose": net_loss,
        "breakeven_probability": be, "breakeven_note": "includes trading fee, slippage and other costs",
        "fee_formula": sched.describe(),
    }
    if reversal_frequency is not None:
        p = reversal_frequency
        ev = p * net_win + (1 - p) * net_loss
        out.update({"expected_value": ev, "expected_roi": ev / total if total else None,
                    "edge_vs_breakeven": p - be})
    return out


def table(investment: float = 1.0, slippage_per_share: float = 0.0, fee_rate: float = 0.07) -> list[dict]:
    rows = []
    for p in CALCULATOR_PRICES:
        r = calculate(p, investment=investment, slippage_per_share=slippage_per_share, fee_rate=fee_rate)
        rows.append({"price": p, "shares": r["shares"], "fee": r["fee"], "total_cost": r["total_cost"],
                     "payout_if_win": r["payout_if_win"], "net_profit_if_win": r["net_profit_if_win"],
                     "min_reversal_frequency": r["breakeven_probability"],
                     "odds_multiple": r["payout_if_win"] / r["total_cost"]})
    return rows
