"""Experiment manager: persistent, restart-safe experiments and default account seeding."""
from __future__ import annotations

import asyncio
import json
import logging
import secrets
from datetime import datetime, timezone

from sqlalchemy import func, select

from ..config import get_settings
from ..constants import ASSETS
from ..db import now_ms, session_scope
from ..execution import accounting
from ..execution.risk import DEFAULT_RISK
from ..models import Account, Experiment, MarketObservation, Strategy, Transaction
from ..strategies.library import STRATEGIES, default_params
from .collector import db_write_lock
from .events import record_event

log = logging.getLogger("reversal.experiments")

DURATIONS = {"1h": 1, "2h": 2, "6h": 6, "12h": 12, "24h": 24, "48h": 48, "unlimited": None}


def seed_strategies_and_accounts(starting_balance: float = 20.0) -> None:
    with db_write_lock, session_scope() as s:
        for k, meta in STRATEGIES.items():
            row = s.get(Strategy, k)
            if row is None:
                s.add(Strategy(key=k, name=meta["name"], description=meta["description"],
                               default_params_json=json.dumps(default_params(k))))
            else:
                row.name, row.description = meta["name"], meta["description"]
                row.default_params_json = json.dumps(default_params(k))
        s.flush()
        if s.scalar(select(func.count()).select_from(Account)):
            have = set(s.scalars(select(Account.strategy_key)).all())
            for k, meta in STRATEGIES.items():
                if k not in have:
                    rk = {**DEFAULT_RISK, "max_investment_per_trade": 6.0, "max_total_exposure": 30.0}                         if k in ("K", "L", "M") else DEFAULT_RISK
                    a = Account(name=f"{k} · {meta['name']}", strategy_key=k, params_json="{}",
                                risk_json=json.dumps(rk), initial_balance=starting_balance,
                                cash=starting_balance, reserved=0.0, peak_equity=starting_balance, created_ts=now_ms())
                    s.add(a)
                    s.flush()
                    accounting._ledger(s, a, "initial", starting_balance, None, "initial virtual balance", manual=True)
            return
        specs: list[tuple[str, str, dict]] = []
        for k, meta in STRATEGIES.items():
            if k == "F":
                for t in (30, 15, 10, 5, 3, 1):
                    specs.append((f"F · T-{t}", "F", {"entry_t": t}))
            else:
                specs.append((f"{k} · {meta['name']}", k, {}))
        for name, key, params in specs:
            a = Account(name=name, strategy_key=key, params_json=json.dumps(params), risk_json=json.dumps(DEFAULT_RISK),
                        initial_balance=starting_balance, cash=starting_balance, reserved=0.0,
                        peak_equity=starting_balance, created_ts=now_ms())
            s.add(a)
            s.flush()
            accounting._ledger(s, a, "initial", starting_balance, None, "initial virtual balance", manual=True)


def _exp_id() -> str:
    return "EXP-" + datetime.now(timezone.utc).strftime("%y%m%d-%H%M") + "-" + secrets.token_hex(2).upper()


def start_experiment(name: str | None, duration: str, assets: list[str], account_ids: list[int],
                     starting_balance: float | None, reset_accounts: bool) -> dict:
    if duration not in DURATIONS:
        raise ValueError(f"duration must be one of {list(DURATIONS)}")
    assets = [a for a in assets if a in ASSETS] or list(ASSETS)
    with db_write_lock, session_scope() as s:
        if s.scalar(select(Experiment).where(Experiment.status.in_(("running", "paused")))):
            raise ValueError("An experiment is already running or paused. Stop it first.")
        accts = s.scalars(select(Account).where(Account.id.in_(account_ids))).all() if account_ids else \
            s.scalars(select(Account).where(Account.archived.is_(False), Account.active.is_(True))).all()
        if not accts:
            raise ValueError("No accounts selected")
        if reset_accounts and starting_balance is not None:
            for a in accts:
                if accounting.open_positions(s, a.id):
                    raise ValueError(f"Account '{a.name}' has open positions; wait for settlement before resetting")
                accounting.reset(s, a, starting_balance)
        for a in accts:
            a.halted_reason = None
        hours = DURATIONS[duration]
        start = now_ms()
        st = get_settings()
        cfg = {
            "duration": duration, "assets": assets,
            "accounts": [{"id": a.id, "name": a.name, "strategy": a.strategy_key, "params": json.loads(a.params_json),
                          "risk": json.loads(a.risk_json), "balance": a.cash} for a in accts],
            "paper_latency_ms": st.paper_latency_ms, "min_order_shares": st.paper_min_order_shares,
            "min_marketable_notional": st.paper_min_marketable_notional,
            "observation_interval_ms": st.observation_interval_ms,
            "fee_model": "fee = shares x rate x p x (1-p), rate from live market feeSchedule (0.07 crypto)",
            "settlement": "official Gamma outcomePrices only; crypto-price API used as cross-check",
        }
        e = Experiment(id=_exp_id(), name=name or f"{duration} reversal experiment", status="running",
                       started_ts=start, duration_hours=hours, ends_ts=(start + int(hours * 3600 * 1000)) if hours else None,
                       starting_balance=round(sum(a.cash + a.reserved for a in accts), 6),
                       assets_json=json.dumps(assets), account_ids_json=json.dumps([a.id for a in accts]),
                       config_json=json.dumps(cfg, default=str))
        s.add(e)
        out = experiment_dict(e)
    record_event("experiment", f"Experiment {out['id']} started ({duration})", data=out)
    return out


def set_status(exp_id: str, action: str) -> dict:
    with db_write_lock, session_scope() as s:
        e = s.get(Experiment, exp_id)
        if not e:
            raise ValueError("experiment not found")
        now = now_ms()
        if action == "pause" and e.status == "running":
            e.status, e.paused_ts = "paused", now
        elif action == "resume" and e.status == "paused":
            if e.ends_ts and e.paused_ts:
                e.ends_ts += now - e.paused_ts  # paused time does not count towards duration
            e.status, e.paused_ts = "running", None
        elif action == "stop" and e.status in ("running", "paused"):
            e.status = "stopped"
            e.completed_ts = now
        else:
            raise ValueError(f"cannot {action} an experiment that is {e.status}")
        out = experiment_dict(e)
    if action == "stop":
        finalize(exp_id)
    return out


def finalize(exp_id: str) -> None:
    from .reports import generate_report
    with db_write_lock, session_scope() as s:
        e = s.get(Experiment, exp_id)
        ids = json.loads(e.account_ids_json)
        accts = s.scalars(select(Account).where(Account.id.in_(ids))).all()
        e.ending_balance = round(sum(a.cash + a.reserved for a in accts), 6)
        e.net_profit = float(s.scalar(select(func.coalesce(func.sum(Transaction.net_profit), 0.0))
                                      .where(Transaction.experiment_id == exp_id)) or 0.0)
        end = e.completed_ts or now_ms()
        e.observation_count = int(s.scalar(select(func.count()).select_from(MarketObservation)
                                           .where(MarketObservation.server_ts.between(e.started_ts, end))) or 0)
    try:
        rid = generate_report(exp_id)
        with db_write_lock, session_scope() as s:
            s.get(Experiment, exp_id).report_id = rid
    except Exception as ex:
        log.exception("report generation failed")
        record_event("experiment", f"Report generation failed for {exp_id}: {ex!r}", level="ERROR")
    record_event("experiment_completed", f"Experiment {exp_id} finished — report ready", data={"id": exp_id})


async def experiment_watchdog() -> None:
    """Completes experiments whose time has elapsed (also after restarts/sleep)."""
    while True:
        try:
            due = []
            with session_scope() as s:
                for e in s.scalars(select(Experiment).where(Experiment.status == "running")).all():
                    if e.ends_ts and now_ms() >= e.ends_ts:
                        due.append(e.id)
            for eid in due:
                with db_write_lock, session_scope() as s:
                    e = s.get(Experiment, eid)
                    e.status, e.completed_ts = "completed", e.ends_ts
                await asyncio.to_thread(finalize, eid)
        except Exception:
            log.exception("watchdog error")
        await asyncio.sleep(10)


def experiment_dict(e: Experiment) -> dict:
    now = now_ms()
    elapsed = ((e.completed_ts or (e.paused_ts if e.status == "paused" else now)) - e.started_ts) / 1000
    return {
        "id": e.id, "name": e.name, "status": e.status, "started_ts": e.started_ts,
        "duration_hours": e.duration_hours, "ends_ts": e.ends_ts, "completed_ts": e.completed_ts,
        "elapsed_seconds": elapsed,
        "remaining_seconds": max(0, (e.ends_ts - now) / 1000) if (e.ends_ts and e.status == "running") else None,
        "starting_balance": e.starting_balance, "ending_balance": e.ending_balance, "net_profit": e.net_profit,
        "assets": json.loads(e.assets_json), "account_ids": json.loads(e.account_ids_json),
        "config": json.loads(e.config_json), "observation_count": e.observation_count,
        "signal_count": e.signal_count, "trade_count": e.trade_count, "win_count": e.win_count,
        "loss_count": e.loss_count, "report_id": e.report_id,
    }
