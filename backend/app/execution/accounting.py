"""Paper account accounting. Every cent moves through the ledger.

cash      = funds available for new orders
reserved  = funds locked by pending/resting orders (max possible cost)
equity    = cash + reserved + mark value of open positions

Manual adjustments (deposit / withdrawal / reset) are ledger entries flagged
``manual=True`` and never touch historical transactions.
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import now_ms
from ..models import Account, AccountBalanceSnapshot, AccountLedger, Transaction

EPS = 1e-9
OPEN_STATUSES = ("pending", "partially_filled", "filled")


class InsufficientFunds(Exception):
    pass


def _ledger(s: Session, acct: Account, kind: str, amount: float, txid: str | None = None, note: str | None = None,
            manual: bool = False) -> None:
    s.add(AccountLedger(account_id=acct.id, ts=now_ms(), kind=kind, amount=round(amount, 6),
                        cash_after=round(acct.cash, 6), reserved_after=round(acct.reserved, 6),
                        transaction_id=txid, manual=manual, note=note))


def reserve(s: Session, acct: Account, amount: float, txid: str) -> None:
    if amount <= 0:
        raise ValueError("reserve amount must be positive")
    if acct.cash + EPS < amount:
        raise InsufficientFunds(f"available ${acct.cash:.4f} < required ${amount:.4f}")
    acct.cash = round(acct.cash - amount, 6)
    acct.reserved = round(acct.reserved + amount, 6)
    _ledger(s, acct, "reserve", -amount, txid, "funds locked for order")


def release(s: Session, acct: Account, amount: float, txid: str, note: str = "unused reservation released") -> None:
    amount = min(amount, acct.reserved)
    if amount <= EPS:
        return
    acct.reserved = round(acct.reserved - amount, 6)
    acct.cash = round(acct.cash + amount, 6)
    _ledger(s, acct, "release", amount, txid, note)


def debit_fill(s: Session, acct: Account, cost: float, txid: str, note: str) -> None:
    """Pay for a fill out of reserved funds (cost <= reservation by construction)."""
    from_reserved = min(cost, acct.reserved)
    acct.reserved = round(acct.reserved - from_reserved, 6)
    rest = cost - from_reserved
    if rest > EPS:
        if acct.cash + EPS < rest:
            raise InsufficientFunds("fill cost exceeds reserved + available funds")
        acct.cash = round(acct.cash - rest, 6)
    # record as a release of the reservation followed by the actual debit, so the
    # ledger shows the true cash impact of the fill
    _ledger(s, acct, "trade_debit", -cost, txid, note)


def credit_settlement(s: Session, acct: Account, amount: float, txid: str, note: str) -> None:
    acct.cash = round(acct.cash + amount, 6)
    _ledger(s, acct, "settlement_credit", amount, txid, note)


def deposit(s: Session, acct: Account, amount: float, note: str | None = None) -> None:
    if amount <= 0:
        raise ValueError("deposit must be positive")
    acct.cash = round(acct.cash + amount, 6)
    _ledger(s, acct, "deposit", amount, None, note or "manual virtual deposit", manual=True)
    if acct.halted_reason and "balance" in (acct.halted_reason or ""):
        acct.halted_reason = None


def withdraw(s: Session, acct: Account, amount: float, note: str | None = None) -> None:
    if amount <= 0:
        raise ValueError("withdrawal must be positive")
    if amount > acct.cash + EPS:
        raise InsufficientFunds(f"cannot withdraw ${amount:.2f}; available ${acct.cash:.2f}")
    acct.cash = round(acct.cash - amount, 6)
    _ledger(s, acct, "withdrawal", -amount, None, note or "manual virtual withdrawal", manual=True)


def reset(s: Session, acct: Account, new_balance: float) -> None:
    """Reset the virtual balance. Open positions are left to settle; history is preserved."""
    if new_balance < 0:
        raise ValueError("balance cannot be negative")
    delta = new_balance - acct.cash
    acct.cash = round(new_balance, 6)
    acct.initial_balance = new_balance
    acct.peak_equity = new_balance + acct.reserved
    acct.halted_reason = None
    _ledger(s, acct, "reset", delta, None, f"balance reset to ${new_balance:.2f}", manual=True)


def open_positions(s: Session, account_id: int) -> list[Transaction]:
    return list(s.scalars(select(Transaction).where(Transaction.account_id == account_id,
                                                    Transaction.status.in_(OPEN_STATUSES),
                                                    Transaction.source == "live")).all())


def realized_pnl(s: Session, account_id: int) -> float:
    v = s.scalar(select(func.coalesce(func.sum(Transaction.net_profit), 0.0))
                 .where(Transaction.account_id == account_id, Transaction.source == "live",
                        Transaction.status.in_(("won", "lost", "cancelled"))))
    return float(v or 0.0)


def account_summary(s: Session, acct: Account, mark: dict[str, float] | None = None) -> dict:
    """Balance breakdown. ``mark`` maps transaction_id -> current best bid (mark price)."""
    mark = mark or {}
    pos = open_positions(s, acct.id)
    open_cost = sum(t.total_cost for t in pos if t.filled_shares > 0)
    mark_value = 0.0
    for t in pos:
        if t.filled_shares > 0:
            mark_value += t.filled_shares * mark.get(t.id, 0.0)
    unreal = mark_value - open_cost
    led = s.execute(select(AccountLedger.kind, func.sum(AccountLedger.amount))
                    .where(AccountLedger.account_id == acct.id).group_by(AccountLedger.kind)).all()
    by = {k: float(v or 0) for k, v in led}
    realized = realized_pnl(s, acct.id)
    equity = acct.cash + acct.reserved + mark_value
    return {
        "account_id": acct.id,
        "initial_balance": acct.initial_balance,
        "deposited": by.get("deposit", 0.0),
        "withdrawn": -by.get("withdrawal", 0.0),
        "resets_net": by.get("reset", 0.0),
        "available": round(acct.cash, 6),
        "reserved": round(acct.reserved, 6),
        "open_position_cost": round(open_cost, 6),
        "open_position_mark_value": round(mark_value, 6),
        "unrealized_pnl": round(unreal, 6),
        "unrealized_is_estimate": True,
        "realized_pnl": round(realized, 6),
        "equity": round(equity, 6),
        "open_positions": len(pos),
    }


def snapshot_balance(s: Session, acct: Account, mark: dict[str, float] | None = None) -> None:
    sm = account_summary(s, acct, mark)
    s.add(AccountBalanceSnapshot(account_id=acct.id, ts=now_ms(), cash=sm["available"], reserved=sm["reserved"],
                                 open_cost=sm["open_position_cost"], unrealized=sm["unrealized_pnl"],
                                 equity=sm["equity"], realized=sm["realized_pnl"]))
    acct.peak_equity = max(acct.peak_equity or 0.0, sm["equity"])
