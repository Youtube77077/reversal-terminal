"""Trading API: accounts & balances, transactions, strategies, engine controls, experiments."""
from __future__ import annotations

import asyncio
import io
import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select

from ..db import now_ms, session_scope
from ..execution import accounting
from ..execution.risk import DEFAULT_RISK, merged_risk
from ..execution.session import session_status, start_session, stop_session
from ..models import (
    Account,
    AccountBalanceSnapshot,
    AccountLedger,
    Experiment,
    ExperimentReport,
    FeeRecord,
    Market,
    OrderBookSnapshot,
    Signal,
    SimFill,
    SimOrder,
    Strategy,
    Transaction,
)
from ..services import analytics
from ..services.collector import collector, db_write_lock
from ..services.experiments import experiment_dict, set_status, start_experiment
from ..strategies.library import STRATEGIES, default_params

router = APIRouter(prefix="/api")


def _eng():
    return collector.engine


# ================================================================ accounts
class AccountIn(BaseModel):
    name: str
    strategy_key: str = "A"
    balance: float = Field(20.0, ge=0)
    params: dict = {}
    risk: dict = {}


class AmountIn(BaseModel):
    amount: float = Field(..., gt=0)
    note: str | None = None


class ResetIn(BaseModel):
    balance: float = Field(20.0, ge=0)


class AccountPatch(BaseModel):
    name: str | None = None
    params: dict | None = None
    risk: dict | None = None
    active: bool | None = None
    paused: bool | None = None
    archived: bool | None = None


def _acct_dict(s, a: Account) -> dict:
    eng = _eng()
    sm = accounting.account_summary(s, a, eng.mark_prices(s, a.id) if eng else {})
    return {"id": a.id, "name": a.name, "mode": a.mode, "strategy_key": a.strategy_key,
            "strategy_name": STRATEGIES.get(a.strategy_key, {}).get("name"),
            "params": {**default_params(a.strategy_key), **json.loads(a.params_json or "{}")},
            "risk": merged_risk(a), "active": a.active, "paused": a.paused, "archived": a.archived,
            "halted_reason": a.halted_reason, "peak_equity": a.peak_equity, "created_ts": a.created_ts,
            "summary": sm, "session": session_status(s, a)}


@router.get("/accounts")
def accounts(include_archived: bool = False):
    with session_scope() as s:
        q = select(Account)
        if not include_archived:
            q = q.where(Account.archived.is_(False))
        return [_acct_dict(s, a) for a in s.scalars(q.order_by(Account.id)).all()]


@router.post("/accounts")
def create_account(body: AccountIn):
    if body.strategy_key not in STRATEGIES:
        raise HTTPException(400, "unknown strategy")
    with db_write_lock, session_scope() as s:
        a = Account(name=body.name, strategy_key=body.strategy_key, params_json=json.dumps(body.params),
                    risk_json=json.dumps({**DEFAULT_RISK, **body.risk}), initial_balance=body.balance,
                    cash=body.balance, reserved=0.0, peak_equity=body.balance, created_ts=now_ms())
        s.add(a)
        s.flush()
        accounting._ledger(s, a, "initial", body.balance, None, "initial virtual balance", manual=True)
        return _acct_dict(s, a)


@router.get("/accounts/{aid}")
def account(aid: int):
    with session_scope() as s:
        a = s.get(Account, aid)
        if not a:
            raise HTTPException(404)
        return _acct_dict(s, a)


@router.patch("/accounts/{aid}")
def patch_account(aid: int, body: AccountPatch):
    with db_write_lock, session_scope() as s:
        a = s.get(Account, aid)
        if not a:
            raise HTTPException(404)
        if body.name is not None:
            a.name = body.name
        if body.params is not None:
            a.params_json = json.dumps(body.params)
        if body.risk is not None:
            a.risk_json = json.dumps({**merged_risk(a), **body.risk})
        for f in ("active", "paused", "archived"):
            v = getattr(body, f)
            if v is not None:
                setattr(a, f, v)
        return _acct_dict(s, a)


@router.post("/accounts/{aid}/{action}")
def account_action(aid: int, action: str, body: dict | None = None):
    body = body or {}
    with db_write_lock, session_scope() as s:
        a = s.get(Account, aid)
        if not a:
            raise HTTPException(404)
        try:
            if action == "deposit":
                accounting.deposit(s, a, float(AmountIn(**body).amount), body.get("note"))
            elif action == "withdraw":
                accounting.withdraw(s, a, float(AmountIn(**body).amount), body.get("note"))
            elif action == "reset":
                accounting.reset(s, a, float(ResetIn(**body).balance))
            elif action == "pause":
                a.paused = True
            elif action == "resume":
                a.paused = False
                a.halted_reason = None if (a.halted_reason and a.cash > 0) else a.halted_reason
            elif action == "clear-halt":
                a.halted_reason = None
            else:
                raise HTTPException(400, "unknown action")
        except (ValueError, accounting.InsufficientFunds) as e:
            raise HTTPException(400, str(e))
        accounting.snapshot_balance(s, a)
        return _acct_dict(s, a)


@router.get("/accounts/{aid}/ledger")
def ledger(aid: int, limit: int = 500):
    with session_scope() as s:
        rows = s.scalars(select(AccountLedger).where(AccountLedger.account_id == aid)
                         .order_by(AccountLedger.ts.desc()).limit(limit)).all()
        return [{c.name: getattr(r, c.name) for c in AccountLedger.__table__.columns} for r in rows]


@router.get("/accounts/{aid}/balance-history")
def balance_history(aid: int):
    with session_scope() as s:
        rows = s.scalars(select(AccountBalanceSnapshot).where(AccountBalanceSnapshot.account_id == aid)
                         .order_by(AccountBalanceSnapshot.ts)).all()
        return [{c.name: getattr(r, c.name) for c in AccountBalanceSnapshot.__table__.columns} for r in rows]


# ================================================================ transactions
TX_COLS = [c.name for c in Transaction.__table__.columns if c.name != "entry_snapshot_json"]


def _tx_query(asset, status, strategy, account_id, result, min_price, max_price, min_secs, max_secs, start, end,
              experiment_id, q):
    qq = select(Transaction).where(Transaction.source == "live")
    if asset:
        qq = qq.where(Transaction.asset == asset)
    if status:
        qq = qq.where(Transaction.status.in_(status.split(",")))
    if strategy:
        qq = qq.where(Transaction.strategy_key == strategy)
    if account_id:
        qq = qq.where(Transaction.account_id == account_id)
    if result == "win":
        qq = qq.where(Transaction.status == "won")
    elif result == "loss":
        qq = qq.where(Transaction.status == "lost")
    if min_price is not None:
        qq = qq.where(Transaction.entry_price >= min_price)
    if max_price is not None:
        qq = qq.where(Transaction.entry_price <= max_price)
    if min_secs is not None:
        qq = qq.where(Transaction.entry_secs_remaining >= min_secs)
    if max_secs is not None:
        qq = qq.where(Transaction.entry_secs_remaining <= max_secs)
    if start:
        qq = qq.where(Transaction.created_ts >= start)
    if end:
        qq = qq.where(Transaction.created_ts <= end)
    if experiment_id:
        qq = qq.where(Transaction.experiment_id == experiment_id)
    if q:
        qq = qq.where(or_(Transaction.id.like(f"%{q}%"), Transaction.asset.like(f"%{q}%")))
    return qq


@router.get("/transactions")
def transactions(asset: str | None = None, status: str | None = None, strategy: str | None = None,
                       account_id: int | None = None, result: str | None = None, min_price: float | None = None,
                       max_price: float | None = None, min_secs: float | None = None, max_secs: float | None = None,
                       start: int | None = None, end: int | None = None, experiment_id: str | None = None,
                       q: str | None = None, limit: int = 200, offset: int = 0):
    with session_scope() as s:
        qq = _tx_query(asset, status, strategy, account_id, result, min_price, max_price, min_secs, max_secs, start,
                       end, experiment_id, q)
        total = s.scalar(select(func.count()).select_from(qq.subquery()))
        rows = s.scalars(qq.order_by(Transaction.created_ts.desc()).limit(min(limit, 2000)).offset(offset)).all()
        names = dict(s.execute(select(Account.id, Account.name)).all())
        slugs = dict(s.execute(select(Market.id, Market.slug).where(Market.id.in_([r.market_id for r in rows])))
                     .all()) if rows else {}
        out = []
        for r in rows:
            d = {c: getattr(r, c) for c in TX_COLS}
            d["account_name"] = names.get(r.account_id)
            d["market_slug"] = slugs.get(r.market_id)
            out.append(d)
        return {"total": total, "rows": out}


@router.get("/transactions/export")
def export_transactions(fmt: str = "csv", asset: str | None = None, status: str | None = None,
                              strategy: str | None = None, account_id: int | None = None, result: str | None = None,
                              experiment_id: str | None = None):
    with session_scope() as s:
        qq = _tx_query(asset, status, strategy, account_id, result, None, None, None, None, None, None,
                       experiment_id, None)
        rows = s.scalars(qq.order_by(Transaction.created_ts)).all()
        data = [{c: getattr(r, c) for c in TX_COLS} for r in rows]
    if fmt == "json":
        return Response(json.dumps(data, default=str, indent=1), media_type="application/json",
                        headers={"Content-Disposition": 'attachment; filename="transactions.json"'})
    import csv
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=TX_COLS)
    w.writeheader()
    w.writerows(data)
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="transactions.csv"'})


@router.get("/transactions/{txid}")
def transaction_detail(txid: str):
    with session_scope() as s:
        t = s.get(Transaction, txid)
        if not t:
            raise HTTPException(404)
        d = {c.name: getattr(t, c.name) for c in Transaction.__table__.columns}
        d["entry_snapshot"] = json.loads(t.entry_snapshot_json) if t.entry_snapshot_json else None
        d.pop("entry_snapshot_json", None)
        acct = s.get(Account, t.account_id)
        d["account_name"] = acct.name if acct else None
        m = s.get(Market, t.market_id)
        d["market"] = {k: getattr(m, k) for k in ("id", "slug", "question", "open_ts", "close_ts", "status", "winner",
                                                  "open_price", "close_price", "resolution_source",
                                                  "settlement_method", "condition_id", "up_token_id",
                                                  "down_token_id")} if m else None
        o = s.get(SimOrder, t.order_id) if t.order_id else None
        d["order"] = {c.name: getattr(o, c.name) for c in SimOrder.__table__.columns} if o else None
        d["fills"] = [{c.name: getattr(f, c.name) for c in SimFill.__table__.columns}
                      for f in s.scalars(select(SimFill).where(SimFill.order_id == t.order_id))] if o else []
        d["fees"] = [{c.name: getattr(f, c.name) for c in FeeRecord.__table__.columns}
                     for f in s.scalars(select(FeeRecord).where(FeeRecord.transaction_id == txid))]
        sig = s.get(Signal, t.signal_id) if t.signal_id else None
        d["signal"] = {c.name: getattr(sig, c.name) for c in Signal.__table__.columns} if sig else None
        books = {}
        for k, bid in (("decision", o.decision_book_id if o else None), ("execution", o.execution_book_id if o else None)):
            b = s.get(OrderBookSnapshot, bid) if bid else None
            if b:
                books[k] = {"server_ts": b.server_ts, "exchange_ts": b.exchange_ts, "up_bids": json.loads(b.up_bids_json),
                            "up_asks": json.loads(b.up_asks_json), "down_bids": json.loads(b.down_bids_json),
                            "down_asks": json.loads(b.down_asks_json)}
        d["books"] = books
        led = s.scalars(select(AccountLedger).where(AccountLedger.transaction_id == txid)
                        .order_by(AccountLedger.ts)).all()
        d["ledger"] = [{c.name: getattr(r, c.name) for c in AccountLedger.__table__.columns} for r in led]
        d["profit_calculation"] = {
            "gross_cost": t.gross_cost, "trading_fee": t.trading_fee, "gas_fee": t.gas_fee,
            "network_fee": t.network_fee, "total_cost": t.total_cost, "slippage_included_in_gross": t.slippage,
            "spread_cost_vs_mid_included_in_gross": t.spread_cost, "potential_payout": t.potential_payout,
            "potential_net_if_win": (t.potential_payout - t.total_cost) if t.filled_shares else None,
            "actual_payout": t.gross_payout, "net_profit": t.net_profit, "roi": t.roi,
            "realised": t.status in ("won", "lost", "cancelled"),
        }
        return d


# ================================================================ strategies / engine
@router.get("/strategies")
def strategies():
    with session_scope() as s:
        rows = s.scalars(select(Strategy)).all()
        return [{"key": r.key, "name": r.name, "description": r.description,
                 "default_params": json.loads(r.default_params_json)} for r in rows]


@router.get("/strategies/compare")
async def strategies_compare(experiment_id: str | None = None):
    return await asyncio.to_thread(analytics.strategy_comparison, experiment_id)


@router.post("/engine/{action}")
def engine_action(action: str):
    eng = _eng()
    if action == "pause-all":
        eng.paused = True
    elif action == "resume-all":
        eng.paused = False
    elif action == "emergency-stop":
        eng.paused = True
        with db_write_lock, session_scope() as s:
            for a in s.scalars(select(Account)).all():
                a.paused = True
    else:
        raise HTTPException(400, "unknown action")
    return {"paused": eng.paused}


@router.get("/signals")
def signals(limit: int = 200, account_id: int | None = None, decision: str | None = None):
    with session_scope() as s:
        q = select(Signal)
        if account_id:
            q = q.where(Signal.account_id == account_id)
        if decision:
            q = q.where(Signal.decision == decision)
        rows = s.scalars(q.order_by(Signal.ts.desc()).limit(limit)).all()
        return [{c.name: getattr(r, c.name) for c in Signal.__table__.columns if c.name != "detail_json"} for r in rows]


@router.get("/orders")
def orders(limit: int = 200, status: str | None = None):
    with session_scope() as s:
        q = select(SimOrder)
        if status:
            q = q.where(SimOrder.status == status)
        rows = s.scalars(q.order_by(SimOrder.decision_ts.desc()).limit(limit)).all()
        return [{c.name: getattr(r, c.name) for c in SimOrder.__table__.columns} for r in rows]


@router.get("/opportunities/live")
def live_opportunities():
    eng = _eng()
    return sorted(eng.opportunities.values(), key=lambda o: o["secs_remaining"]) if eng else []


# ================================================================ experiments
class ExperimentIn(BaseModel):
    name: str | None = None
    duration: str = "24h"
    assets: list[str] = []
    account_ids: list[int] = []
    starting_balance: float | None = 20.0
    reset_accounts: bool = True


@router.get("/experiments")
def experiments():
    with session_scope() as s:
        return [experiment_dict(e) for e in s.scalars(select(Experiment).order_by(Experiment.started_ts.desc()))]


@router.post("/experiments")
async def create_experiment(body: ExperimentIn):
    try:
        return await asyncio.to_thread(start_experiment, body.name, body.duration, body.assets, body.account_ids,
                                       body.starting_balance, body.reset_accounts)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/experiments/{eid}/{action}")
async def experiment_action(eid: str, action: str):
    if action not in ("pause", "resume", "stop"):
        raise HTTPException(400, "action must be pause|resume|stop")
    try:
        return await asyncio.to_thread(set_status, eid, action)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/experiments/{eid}")
async def experiment(eid: str):
    with session_scope() as s:
        e = s.get(Experiment, eid)
        if not e:
            raise HTTPException(404)
        d = experiment_dict(e)
        reps = s.scalars(select(ExperimentReport).where(ExperimentReport.experiment_id == eid)
                         .order_by(ExperimentReport.created_ts.desc())).all()
        d["reports"] = [{"id": r.id, "created_ts": r.created_ts} for r in reps]
    d["live_performance"] = await asyncio.to_thread(analytics.strategy_comparison, eid)
    return d


@router.post("/experiments/{eid}/report")
async def regenerate_report(eid: str):
    from ..services.reports import generate_report
    rid = await asyncio.to_thread(generate_report, eid)
    return {"report_id": rid}


@router.get("/reports/{rid}")
def report(rid: int):
    with session_scope() as s:
        r = s.get(ExperimentReport, rid)
        if not r:
            raise HTTPException(404)
        return {"id": r.id, "experiment_id": r.experiment_id, "created_ts": r.created_ts,
                "summary": json.loads(r.summary_json)}


@router.get("/reports/{rid}/html")
def report_html(rid: int):
    with session_scope() as s:
        r = s.get(ExperimentReport, rid)
        if not r or not r.html_path:
            raise HTTPException(404)
        return FileResponse(r.html_path, media_type="text/html", filename=f"report_{r.experiment_id}.html")


@router.get("/reports/{rid}/csv")
def report_csv(rid: int):
    with session_scope() as s:
        r = s.get(ExperimentReport, rid)
        if not r or not r.csv_path:
            raise HTTPException(404)
        return FileResponse(r.csv_path, media_type="text/csv", filename=f"report_{r.experiment_id}.csv")


# ================================================================ bot sessions (risk budget / SL / TP)
class SessionIn(BaseModel):
    risk_budget_mode: str = "percent"     # percent | amount
    risk_budget_value: float = 25.0
    stop_loss_pct: float = 100.0          # % of the risk budget; 100 = until the budget is $0
    take_profit_mode: str = "off"         # off | percent | amount
    take_profit_value: float = 0.0
    strategy_key: str | None = None
    params: dict | None = None


@router.post("/accounts/{aid}/session")
async def session_start(aid: int, body: SessionIn):
    from ..config import get_settings
    from ..services.events import record_event
    st = get_settings()
    live_balance = None
    with session_scope() as s:
        a = s.get(Account, aid)
        if not a:
            raise HTTPException(404)
        mode = a.mode
    if mode == "live":
        bal = await _eng().live.balance() if _eng() else None
        if bal is None:
            raise HTTPException(400, "Live executor unavailable: cannot read the real wallet balance")
        live_balance = bal
    with db_write_lock, session_scope() as s:
        a = s.get(Account, aid)
        if body.strategy_key:
            if body.strategy_key not in STRATEGIES:
                raise HTTPException(400, "unknown strategy")
            a.strategy_key = body.strategy_key
        if body.params is not None:
            a.params_json = json.dumps(body.params)
        if live_balance is not None:
            budget = (live_balance * body.risk_budget_value / 100 if body.risk_budget_mode == "percent"
                      else body.risk_budget_value)
            if budget > st.live_max_session_budget_usd + 1e-9:
                raise HTTPException(400, "live risk budget $%.2f exceeds LIVE_MAX_SESSION_BUDGET_USD $%.2f"
                                    % (budget, st.live_max_session_budget_usd))
            delta = live_balance - (a.cash + a.reserved)
            a.cash = round(max(0.0, live_balance - a.reserved), 6)
            accounting._ledger(s, a, "wallet_sync", delta, None, "synced to on-chain balance $%.2f" % live_balance)
        try:
            start_session(s, a, body.risk_budget_mode, body.risk_budget_value, body.stop_loss_pct,
                          body.take_profit_mode, body.take_profit_value)
        except ValueError as e:
            raise HTTPException(400, str(e))
        if _eng():
            _eng()._done = {k for k in _eng()._done if k[0] != aid}
        out = _acct_dict(s, a)
    unit = "%" if body.risk_budget_mode == "percent" else "$"
    record_event("experiment", "Bot started on '%s' (%s): budget %s%s, SL %s%%, TP %s %s" % (
        out["name"], out["mode"], body.risk_budget_value, unit, body.stop_loss_pct, body.take_profit_mode,
        body.take_profit_value))
    return out


@router.post("/accounts/{aid}/session/stop")
def session_stop(aid: int):
    with db_write_lock, session_scope() as s:
        a = s.get(Account, aid)
        if not a:
            raise HTTPException(404)
        stop_session(a)
        return _acct_dict(s, a)


# ================================================================ live trading
class ArmIn(BaseModel):
    password: str = ""
    confirm: bool = False


@router.get("/live/status")
async def live_status():
    from ..execution.eligibility import check_eligibility
    el = await check_eligibility()
    eng = _eng()
    with session_scope() as s:
        live = [_acct_dict(s, a) for a in s.scalars(select(Account).where(Account.mode == "live",
                                                                          Account.archived.is_(False)))]
    return {**el, "armed": bool(eng and eng.live_armed), "accounts": live}


@router.post("/live/arm")
async def live_arm(body: ArmIn):
    import hmac
    from ..config import get_settings
    from ..execution.eligibility import check_eligibility
    from ..services import app_settings
    from ..services.events import record_event
    st = get_settings()
    if not body.confirm:
        raise HTTPException(400, "confirm=true required: you are enabling REAL-MONEY trading")
    if st.app_password and not hmac.compare_digest(body.password.encode(), st.app_password.encode()):
        raise HTTPException(403, "wrong password")
    el = await check_eligibility(force=True)
    if not el["eligible"]:
        raise HTTPException(400, "Live trading unavailable: " + " | ".join(el["reasons"]))
    eng = _eng()
    eng.live_eligible, eng.live_armed = True, True
    app_settings.update({"live_armed": True})
    record_event("experiment", "LIVE trading ARMED (real money)", level="WARNING")
    return {"armed": True}


@router.post("/live/disarm")
def live_disarm():
    from ..services import app_settings
    from ..services.events import record_event
    eng = _eng()
    if eng:
        eng.live_armed = False
    app_settings.update({"live_armed": False})
    record_event("experiment", "LIVE trading disarmed", level="WARNING")
    return {"armed": False}


class LiveAccountIn(BaseModel):
    name: str = "LIVE · Polymarket"
    strategy_key: str = "B"
    params: dict = {}


@router.post("/live/account")
def live_account(body: LiveAccountIn):
    if body.strategy_key not in STRATEGIES:
        raise HTTPException(400, "unknown strategy")
    with db_write_lock, session_scope() as s:
        if s.scalar(select(Account).where(Account.mode == "live", Account.archived.is_(False))):
            raise HTTPException(400, "a live account already exists")
        risk_cfg = {**DEFAULT_RISK, "max_investment_per_trade": 2.0, "max_total_exposure": 10.0}
        a = Account(name=body.name, mode="live", strategy_key=body.strategy_key, params_json=json.dumps(body.params),
                    risk_json=json.dumps(risk_cfg), initial_balance=0.0, cash=0.0, reserved=0.0, peak_equity=0.0,
                    created_ts=now_ms())
        s.add(a)
        s.flush()
        return _acct_dict(s, a)
