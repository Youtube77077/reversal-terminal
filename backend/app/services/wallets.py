"""Simple wallet system: Main 1 (cannot be deleted) + any number of testing wallets.

Each wallet owns one practice (paper) account and, once Polymarket keys are saved for it,
one live account. Practice money starts at $0; add funds yourself.
"""
from __future__ import annotations

import json

from sqlalchemy import select

from ..db import now_ms, session_scope
from ..execution import accounting
from ..execution.risk import DEFAULT_RISK
from ..models import Account, Wallet
from .collector import db_write_lock

WALLET_RISK = {**DEFAULT_RISK, "max_investment_per_trade": 1000.0, "max_total_exposure": 100000.0,
               "max_simultaneous_positions": 20, "max_daily_loss": 100000.0, "max_drawdown_pct": 1.0}


# Real money: hard caps so one bad day can't wipe the wallet (editable per account in Trading Engine)
LIVE_RISK = {"max_investment_per_trade": 5.0, "max_total_exposure": 25.0, "max_daily_loss": 25.0,
             "max_simultaneous_positions": 7}


def key(w: Wallet) -> str:
    return "main" if w.is_main else f"w{w.id}"


def _paper(s, w: Wallet) -> Account:
    a = s.scalar(select(Account).where(Account.wallet_id == w.id, Account.mode == "paper", Account.archived.is_(False)))
    if a is None:
        a = Account(name=f"{w.name} · practice", wallet_id=w.id, mode="paper", strategy_key="K", params_json="{}",
                    risk_json=json.dumps(WALLET_RISK), initial_balance=0.0, cash=0.0, reserved=0.0, peak_equity=0.0,
                    created_ts=now_ms())
        s.add(a)
        s.flush()
    return a


def live_account(s, w: Wallet, create: bool = False) -> Account | None:
    a = s.scalar(select(Account).where(Account.wallet_id == w.id, Account.mode == "live", Account.archived.is_(False)))
    if a is None and create:
        a = Account(name=f"{w.name} · live", wallet_id=w.id, mode="live", strategy_key="K", params_json="{}",
                    risk_json=json.dumps({**WALLET_RISK, **LIVE_RISK}), initial_balance=0.0,
                    cash=0.0, reserved=0.0, peak_equity=0.0, created_ts=now_ms())
        s.add(a)
        s.flush()
    return a


def seed() -> None:
    with db_write_lock, session_scope() as s:
        if s.scalar(select(Wallet).limit(1)):
            return
        main = Wallet(name="Main 1", is_main=True, created_ts=now_ms())
        s.add_all([main, Wallet(name="Testing 1", created_ts=now_ms()), Wallet(name="Testing 2", created_ts=now_ms())])
        s.flush()
        for a in s.scalars(select(Account).where(Account.mode == "live", Account.wallet_id.is_(None))).all():
            a.wallet_id = main.id
            a.name = "Main 1 · live"
        for w in s.scalars(select(Wallet)).all():
            _paper(s, w)


def _dict(s, w: Wallet) -> dict:
    from ..services import credentials
    from ..execution.session import session_status
    p = _paper(s, w)
    lv = live_account(s, w)
    out = {"id": w.id, "name": w.name, "is_main": w.is_main, "key": key(w), "keys": credentials.masked(key(w)),
           "paper": {"id": p.id, "cash": p.cash, "reserved": p.reserved, "strategy_key": p.strategy_key,
                     "session": session_status(s, p), "halted_reason": p.halted_reason},
           "live": None}
    if lv:
        out["live"] = {"id": lv.id, "cash": lv.cash, "reserved": lv.reserved, "strategy_key": lv.strategy_key,
                       "session": session_status(s, lv), "halted_reason": lv.halted_reason}
    return out


def list_wallets() -> list[dict]:
    with db_write_lock, session_scope() as s:
        return [_dict(s, w) for w in s.scalars(select(Wallet).where(Wallet.deleted.is_(False)).order_by(Wallet.id)).all()]


def create(name: str) -> dict:
    name = (name or "").strip()[:40] or "New wallet"
    with db_write_lock, session_scope() as s:
        w = Wallet(name=name, created_ts=now_ms())
        s.add(w)
        s.flush()
        _paper(s, w)
        return _dict(s, w)


def rename(wid: int, name: str) -> dict:
    name = (name or "").strip()[:40]
    if not name:
        raise ValueError("name cannot be empty")
    with db_write_lock, session_scope() as s:
        w = s.get(Wallet, wid)
        if not w or w.deleted:
            raise ValueError("wallet not found")
        w.name = name
        for a in s.scalars(select(Account).where(Account.wallet_id == wid)).all():
            a.name = f"{name} · {'live' if a.mode == 'live' else 'practice'}"
        return _dict(s, w)


def delete(wid: int) -> None:
    from ..execution.session import session_status
    from . import credentials
    with db_write_lock, session_scope() as s:
        w = s.get(Wallet, wid)
        if not w or w.deleted:
            raise ValueError("wallet not found")
        if w.is_main:
            raise ValueError("The main wallet can't be deleted (you can rename it)")
        accts = s.scalars(select(Account).where(Account.wallet_id == wid)).all()
        if any(session_status(s, a)["active"] for a in accts):
            raise ValueError("stop this wallet's bot first")
        if any(accounting.open_positions(s, a.id) for a in accts):
            raise ValueError("this wallet still has open trades; wait until they settle")
        for a in accts:
            a.archived, a.active = True, False
        w.deleted = True
        k = key(w)
    credentials.delete(k)


def wallet_key_for_account(s, acct: Account) -> str:
    if not acct.wallet_id:
        return "main"
    w = s.get(Wallet, acct.wallet_id)
    return key(w) if w else "main"
