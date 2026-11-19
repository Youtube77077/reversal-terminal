"""Reset statistics to zero: paper trading, live trading records, and/or research analytics.

A full database backup is written first, so a reset can always be undone by restoring it.
Resetting LIVE records only clears this app's bookkeeping — real positions and funds in
your Polymarket wallet are not touched.
"""
from __future__ import annotations

import json

from sqlalchemy import text

from ..db import now_ms, session_scope
from ..execution import accounting
from ..models import Account
from .backup import backup_now
from .collector import collector, db_write_lock
from .events import record_event


def _ids(s, mode: str) -> list[int]:
    return [r[0] for r in s.execute(text("SELECT id FROM accounts WHERE mode = :m"), {"m": mode}).all()]


def _in(ids: list[int]) -> str:
    return "(" + ",".join(str(int(i)) for i in ids) + ")" if ids else "(NULL)"


def reset(paper: bool, live: bool, research: bool, starting_balance: float = 20.0) -> dict:
    if not (paper or live or research):
        raise ValueError("choose at least one thing to reset")
    if starting_balance < 0:
        raise ValueError("starting balance cannot be negative")
    backup = backup_now()
    counts: dict[str, int] = {}
    eng = collector.engine
    with db_write_lock, session_scope() as s:
        def run(label: str, sql: str, **p) -> None:
            counts[label] = counts.get(label, 0) + (s.execute(text(sql), p).rowcount or 0)

        for flag, mode in ((paper, "paper"), (live, "live")):
            if not flag:
                continue
            ids = _ids(s, mode)
            if not ids:
                continue
            a = _in(ids)
            run("fees", f"DELETE FROM fees WHERE transaction_id IN (SELECT id FROM transactions WHERE account_id IN {a})")
            run("fills", f"DELETE FROM simulated_fills WHERE order_id IN (SELECT id FROM simulated_orders WHERE account_id IN {a})")
            run("orders", f"DELETE FROM simulated_orders WHERE account_id IN {a}")
            run("transactions", f"DELETE FROM transactions WHERE account_id IN {a}")
            run("signals", f"DELETE FROM signals WHERE account_id IN {a}")
            run("ledger", f"DELETE FROM account_ledger WHERE account_id IN {a}")
            run("balance_snapshots", f"DELETE FROM account_balances WHERE account_id IN {a}")
            run("skipped_signals", f"DELETE FROM strategy_candidates WHERE account_id IN {a}")
            for acct in s.query(Account).filter(Account.id.in_(ids)).all():
                bal = starting_balance if mode == "paper" else 0.0
                acct.cash, acct.reserved, acct.initial_balance, acct.peak_equity = bal, 0.0, bal, bal
                acct.halted_reason, acct.paused = None, False
                acct.risk_budget_mode, acct.session_start_equity, acct.session_start_ts = "off", None, None
                acct.session_end_reason = "reset"
                if mode == "paper":
                    accounting._ledger(s, acct, "initial", bal, None, "balance after stats reset", manual=True)
        if paper:
            run("experiment_reports", "DELETE FROM experiment_reports")
            run("experiments", "DELETE FROM experiments")

        if research:
            keep = {m.id for m in collector.markets.values()}
            keep_sql = _in(sorted(keep))
            for t, label in (("orderbook_snapshots", "orderbook_snapshots"), ("checkpoints", "checkpoints"),
                             ("market_observations", "observations"), ("underlying_prices", "underlying_prices"),
                             ("market_resolutions", "resolutions"), ("collector_gaps", "gaps"),
                             ("historical_markets", "historical_markets"), ("app_events", "events")):
                run(label, f"DELETE FROM {t}")
            run("markets", f"DELETE FROM markets WHERE id NOT IN {keep_sql} "
                           "AND id NOT IN (SELECT market_id FROM transactions) "
                           "AND id NOT IN (SELECT market_id FROM signals) "
                           "AND id NOT IN (SELECT market_id FROM simulated_orders)")
            s.execute(text("UPDATE markets SET observation_count = 0"))

    # in-memory state
    if eng is not None:
        eng._done.clear()
        eng._rejected.clear()
        eng.hist_cache, eng.hist_cache_ts = {}, 0
        eng.opportunities.clear()
        if paper or live:
            eng.resting.clear()
            eng.inflight.clear()
    if research:
        collector.observations_written = 0
        collector.missing_observations = 0
        collector.last_obs_ts.clear()
    what = [w for w, f in (("paper trading", paper), ("live records", live), ("analytics", research)) if f]
    record_event("experiment", f"Stats reset: {', '.join(what)} (backup {backup})", level="WARNING",
                 data={"counts": counts})
    return {"ok": True, "reset": what, "counts": counts, "backup": backup, "ts": now_ms(),
            "starting_balance": starting_balance}
