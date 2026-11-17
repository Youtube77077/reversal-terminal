"""Bot "run" sessions: risk budget, stop loss and take profit per account.

* Risk budget = a % of the account balance at session start, or a fixed $ amount.
* Stop loss %  = share of the risk budget that may be lost. 100 % means the bot keeps
  trading until the whole risk budget is gone ($0 left of it). The check is
  conservative: realised losses + money tied up in open positions + reserved funds
  + the next order's cost can never exceed the stop-loss limit, so the worst case
  loss is bounded by it even if every open position loses.
* Take profit = stop when realised session profit reaches a % of the risk budget
  or a fixed $ amount.
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import now_ms
from ..models import Account, Transaction


def _equity_cost_basis(s: Session, acct: Account) -> float:
    open_cost = s.scalar(select(func.coalesce(func.sum(Transaction.total_cost), 0.0))
                         .where(Transaction.account_id == acct.id,
                                Transaction.status.in_(("filled", "partially_filled", "pending", "unresolved")))) or 0.0
    return float(acct.cash + acct.reserved + open_cost)


def start_session(s: Session, acct: Account, budget_mode: str, budget_value: float, stop_loss_pct: float,
                  tp_mode: str, tp_value: float) -> None:
    if budget_mode not in ("percent", "amount"):
        raise ValueError("risk budget mode must be 'percent' or 'amount'")
    if budget_value <= 0:
        raise ValueError("risk budget must be > 0")
    if budget_mode == "percent" and budget_value > 100:
        raise ValueError("risk budget % cannot exceed 100")
    if not (0 < stop_loss_pct <= 100):
        raise ValueError("stop loss must be between 0 and 100 %")
    if tp_mode not in ("off", "percent", "amount"):
        raise ValueError("take profit mode must be off, percent or amount")
    if tp_mode != "off" and tp_value <= 0:
        raise ValueError("take profit must be > 0")
    acct.risk_budget_mode, acct.risk_budget_value = budget_mode, float(budget_value)
    acct.stop_loss_pct = float(stop_loss_pct)
    acct.take_profit_mode, acct.take_profit_value = tp_mode, float(tp_value or 0)
    acct.session_start_equity = _equity_cost_basis(s, acct)
    acct.session_start_ts = now_ms()
    acct.session_end_reason = None
    acct.halted_reason = None
    acct.paused = False


def stop_session(acct: Account, reason: str = "stopped by user") -> None:
    acct.risk_budget_mode = "off"
    acct.session_end_reason = reason


def session_status(s: Session, acct: Account) -> dict:
    if acct.risk_budget_mode not in ("percent", "amount") or acct.session_start_equity is None:
        return {"active": False, "state": "off", "end_reason": acct.session_end_reason}
    base = acct.session_start_equity
    budget = base * acct.risk_budget_value / 100 if acct.risk_budget_mode == "percent" else min(acct.risk_budget_value, base)
    sl_limit = budget * acct.stop_loss_pct / 100
    start = acct.session_start_ts or 0
    realized = float(s.scalar(select(func.coalesce(func.sum(Transaction.net_profit), 0.0))
                              .where(Transaction.account_id == acct.id, Transaction.settled_ts >= start,
                                     Transaction.status.in_(("won", "lost", "cancelled")))) or 0.0)
    open_cost = float(s.scalar(select(func.coalesce(func.sum(Transaction.total_cost), 0.0))
                               .where(Transaction.account_id == acct.id, Transaction.created_ts >= start,
                                      Transaction.status.in_(("filled", "partially_filled", "pending",
                                                              "unresolved")))) or 0.0)
    at_risk = open_cost + acct.reserved
    loss = max(0.0, -realized)
    remaining = max(0.0, sl_limit - loss - at_risk)
    if acct.take_profit_mode == "percent":
        tp = budget * acct.take_profit_value / 100
    elif acct.take_profit_mode == "amount":
        tp = acct.take_profit_value
    else:
        tp = None
    if tp is not None and realized >= tp - 1e-9:
        state = "take_profit_hit"
    elif loss >= sl_limit - 1e-9:
        state = "stop_loss_hit"
    else:
        state = "running"
    return {
        "active": True, "state": state, "started_ts": start, "start_equity": base,
        "budget_mode": acct.risk_budget_mode, "budget_value": acct.risk_budget_value, "risk_budget": budget,
        "stop_loss_pct": acct.stop_loss_pct, "stop_loss_limit": sl_limit,
        "take_profit_mode": acct.take_profit_mode, "take_profit_value": acct.take_profit_value,
        "take_profit_target": tp, "realized_pnl": realized, "open_at_risk": at_risk, "loss_so_far": loss,
        "remaining_risk": remaining, "budget_used_pct": ((loss + at_risk) / sl_limit) if sl_limit else None,
        "tp_progress_pct": (max(0.0, realized) / tp) if tp else None, "end_reason": acct.session_end_reason,
    }
