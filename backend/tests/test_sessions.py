import pytest

from app.db import now_ms
from app.execution import risk
from app.execution.session import session_status, start_session, stop_session
from app.models import Account, Asset, Market, Strategy, Transaction


def _setup(session, cash=20.0):
    if not session.get(Strategy, "A"):
        session.add(Strategy(key="A", name="A", description="", default_params_json="{}"))
    if not session.get(Asset, "BTC"):
        session.add(Asset(symbol="BTC", name="Bitcoin", slug_prefix="btc", chainlink_symbol="btc/usd"))
    a = Account(name="s", strategy_key="A", params_json="{}", risk_json="{}", initial_balance=cash, cash=cash,
                reserved=0.0, peak_equity=cash, created_ts=0)
    session.add(a)
    m = Market(asset="BTC", slug=f"btc-updown-5m-s{now_ms()}{id(a)}", open_ts=0, close_ts=300_000, status="resolved")
    session.add(m)
    session.flush()
    return a, m


def _tx(session, a, m, status, cost, pnl=None):
    t = Transaction(id=f"TX-T{now_ms()}{cost}{status}{id(a)}"[:24], account_id=a.id, strategy_key="A", market_id=m.id,
                    asset="BTC", outcome="UP", order_type="marketable_limit", limit_price=0.02, requested_shares=50,
                    filled_shares=50, total_cost=cost, status=status, created_ts=now_ms(),
                    settled_ts=now_ms() if pnl is not None else None, net_profit=pnl)
    session.add(t)
    session.flush()
    return t


def test_percent_budget_and_stop_loss_bound(session):
    a, m = _setup(session, 20.0)
    start_session(session, a, "percent", 25, 100, "off", 0)
    st = session_status(session, a)
    assert st["risk_budget"] == pytest.approx(5.0) and st["stop_loss_limit"] == pytest.approx(5.0)
    assert st["state"] == "running" and st["remaining_risk"] == pytest.approx(5.0)
    _tx(session, a, m, "lost", 1.07, -1.07)
    _tx(session, a, m, "filled", 1.07)                     # open position counts as fully at risk
    st = session_status(session, a)
    assert st["remaining_risk"] == pytest.approx(5.0 - 2.14)
    _tx(session, a, m, "filled", 1.07)
    d = risk.check(session, a, m.id + 999, 1.9, 10, 0.01, None, None, 20.0)
    assert not d.ok and "risk budget" in d.reason          # 1.90 > 1.79 remaining


def test_stop_loss_hit_blocks_trading(session):
    a, m = _setup(session, 20.0)
    start_session(session, a, "amount", 2.0, 50, "off", 0)   # may lose 50% of $2 = $1
    _tx(session, a, m, "lost", 1.07, -1.07)
    st = session_status(session, a)
    assert st["state"] == "stop_loss_hit"
    d = risk.check(session, a, m.id + 999, 1.0, 10, 0.01, None, None, 18.9)
    assert not d.ok and "stop loss" in d.reason


def test_take_profit_hit(session):
    a, m = _setup(session, 20.0)
    start_session(session, a, "amount", 5.0, 100, "percent", 100)   # TP = 100% of $5 budget
    _tx(session, a, m, "won", 1.07, 48.93)
    assert session_status(session, a)["state"] == "take_profit_hit"
    d = risk.check(session, a, m.id + 999, 1.0, 10, 0.01, None, None, 68.0)
    assert not d.ok and "take profit" in d.reason


def test_session_validation_and_stop(session):
    a, _ = _setup(session)
    with pytest.raises(ValueError):
        start_session(session, a, "percent", 150, 100, "off", 0)
    with pytest.raises(ValueError):
        start_session(session, a, "amount", 5, 0, "off", 0)
    start_session(session, a, "amount", 5, 100, "off", 0)
    stop_session(a)
    assert session_status(session, a)["active"] is False


def test_live_account_requires_session(session):
    a, m = _setup(session)
    a.mode = "live"
    d = risk.check(session, a, m.id + 999, 1.0, 10, 0.01, None, None, 20.0)
    assert not d.ok and "live account requires" in d.reason
