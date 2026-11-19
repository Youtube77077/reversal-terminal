"""Account-level risk controls. Strategies cannot bypass these."""
from __future__ import annotations

import time
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Account, Transaction

DEFAULT_RISK = {
    "max_investment_per_trade": 2.0,
    "max_total_exposure": 10.0,
    "max_trades_per_market": 1,
    "max_simultaneous_positions": 7,
    "max_daily_loss": 10.0,
    "max_drawdown_pct": 0.75,
    "min_liquidity_usd": 1.0,
    "max_spread": 0.05,
    "min_expected_edge": -1.0,      # disabled by default (research wants the raw sample)
    "min_sample_size": 0,
}


@dataclass
class RiskDecision:
    ok: bool
    reason: str | None = None


def merged_risk(acct: Account) -> dict:
    import json
    r = dict(DEFAULT_RISK)
    try:
        r.update(json.loads(acct.risk_json or "{}"))
    except ValueError:
        pass
    return r


def _utc_day_start_ms() -> int:
    t = time.time()
    return int((t - t % 86400) * 1000)


def check(s: Session, acct: Account, market_id: int, cost: float, liquidity: float | None, spread: float | None,
          expected_edge: float | None, sample_size: int | None, equity: float,
          per_market_limit: int | None = None) -> RiskDecision:
    r = merged_risk(acct)
    if per_market_limit is not None:
        r = {**r, "max_trades_per_market": per_market_limit}
    if acct.paused:
        return RiskDecision(False, "account paused")
    if acct.halted_reason:
        return RiskDecision(False, f"account halted: {acct.halted_reason}")
    if acct.cash <= 0.0:
        return RiskDecision(False, "insufficient funds: virtual balance is zero")
    if cost > acct.cash + 1e-9:
        return RiskDecision(False, f"insufficient funds: need ${cost:.2f}, available ${acct.cash:.2f}")
    if cost > r["max_investment_per_trade"] + 1e-9:
        return RiskDecision(False, f"cost ${cost:.2f} > max per trade ${r['max_investment_per_trade']:.2f}")
    open_q = select(Transaction).where(Transaction.account_id == acct.id, Transaction.source == "live",
                                       Transaction.status.in_(("pending", "partially_filled", "filled")))
    open_tx = s.scalars(open_q).all()
    exposure = sum((t.total_cost if t.filled_shares > 0 else 0.0) for t in open_tx) + acct.reserved
    if exposure + cost > r["max_total_exposure"] + 1e-9:
        return RiskDecision(False, f"exposure ${exposure + cost:.2f} > max ${r['max_total_exposure']:.2f}")
    if len(open_tx) >= int(r["max_simultaneous_positions"]):
        return RiskDecision(False, f"{len(open_tx)} open positions >= max {int(r['max_simultaneous_positions'])}")
    n_mkt = s.scalar(select(func.count()).select_from(Transaction)
                     .where(Transaction.account_id == acct.id, Transaction.market_id == market_id,
                            Transaction.source == "live",
                            Transaction.status.notin_(("cancelled", "expired")))) or 0
    if n_mkt >= int(r["max_trades_per_market"]):
        return RiskDecision(False, f"already {n_mkt} trade(s) in this market")
    day_loss = -(s.scalar(select(func.coalesce(func.sum(Transaction.net_profit), 0.0))
                          .where(Transaction.account_id == acct.id, Transaction.source == "live",
                                 Transaction.settled_ts >= _utc_day_start_ms())) or 0.0)
    if day_loss >= r["max_daily_loss"]:
        return RiskDecision(False, f"daily loss ${day_loss:.2f} reached limit ${r['max_daily_loss']:.2f}")
    peak = acct.peak_equity or equity
    if peak > 0 and (peak - equity) / peak >= r["max_drawdown_pct"]:
        return RiskDecision(False, f"drawdown {(peak - equity) / peak:.0%} reached limit {r['max_drawdown_pct']:.0%}")
    if liquidity is not None and liquidity < r["min_liquidity_usd"]:
        return RiskDecision(False, f"liquidity ${liquidity:.2f} < min ${r['min_liquidity_usd']:.2f}")
    if spread is not None and spread > r["max_spread"] + 1e-9:
        return RiskDecision(False, f"spread {spread:.3f} > max {r['max_spread']:.3f}")
    if r["min_expected_edge"] > -1 and (expected_edge is None or expected_edge < r["min_expected_edge"]):
        return RiskDecision(False, f"expected edge {expected_edge} < min {r['min_expected_edge']}")
    if r["min_sample_size"] > 0 and (sample_size or 0) < r["min_sample_size"]:
        return RiskDecision(False, f"statistical sample {sample_size or 0} < min {r['min_sample_size']}")
    from .session import session_status
    ss = session_status(s, acct)
    if acct.mode == "live" and not ss["active"]:
        return RiskDecision(False, "live account requires a running session with a risk budget and stop loss")
    if ss["active"]:
        if ss["state"] == "stop_loss_hit":
            return RiskDecision(False, f"stop loss reached: lost ${ss['loss_so_far']:.2f} of ${ss['stop_loss_limit']:.2f}")
        if ss["state"] == "take_profit_hit":
            return RiskDecision(False, f"take profit reached: +${ss['realized_pnl']:.2f}")
        if cost > ss["remaining_risk"] + 1e-9:
            return RiskDecision(False, f"risk budget: order ${cost:.2f} > remaining ${ss['remaining_risk']:.2f}")
    return RiskDecision(True)
