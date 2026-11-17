import pytest
from sqlalchemy import select

from app.execution import accounting, risk
from app.execution.simulator import max_cost, simulate_marketable_buy, simulate_passive_check
from app.models import Account, AccountLedger
from app.providers.polymarket.fees import FeeSchedule, taker_fee

from .fixtures import BOOK_THIN_UNDERDOG

FEE = FeeSchedule(rate=0.07, verified=True)


# ------------------------------------------------------------------ order-book execution
def test_full_fill_walks_levels():
    r = simulate_marketable_buy(BOOK_THIN_UNDERDOG, 0.03, 100, FEE)
    assert r.status == "filled"
    assert r.filled_shares == pytest.approx(100)
    assert r.vwap == pytest.approx((40 * 0.02 + 60 * 0.03) / 100)
    assert r.fees == pytest.approx(taker_fee(40, 0.02, FEE) + taker_fee(60, 0.03, FEE), abs=1e-5)


def test_partial_fill_fak():
    r = simulate_marketable_buy(BOOK_THIN_UNDERDOG, 0.02, 100, FEE, "FAK")
    assert r.status == "partially_filled" and r.filled_shares == pytest.approx(40)


def test_fok_kills_when_insufficient():
    r = simulate_marketable_buy(BOOK_THIN_UNDERDOG, 0.02, 100, FEE, "FOK")
    assert r.status == "unfilled" and r.filled_shares == 0


def test_never_fills_above_limit_or_on_empty_book():
    assert simulate_marketable_buy([(0.06, 1000)], 0.05, 20, FEE).status == "unfilled"
    assert simulate_marketable_buy([], 0.05, 20, FEE).status == "unfilled"


def test_exchange_minimums_are_enforced():
    assert simulate_marketable_buy(BOOK_THIN_UNDERDOG, 0.03, 4, FEE).status == "failed"           # < 5 shares
    assert simulate_marketable_buy(BOOK_THIN_UNDERDOG, 0.03, 10, FEE).status == "failed"          # < $1 notional
    assert simulate_marketable_buy(BOOK_THIN_UNDERDOG, 0.035, 50, FEE).status == "failed"         # off tick


def test_slippage_is_measured_from_decision_price():
    r = simulate_marketable_buy(BOOK_THIN_UNDERDOG, 0.05, 200, FEE)
    decision_ask = 0.02
    slip = sum((f.price - decision_ask) * f.shares for f in r.fills)
    assert slip == pytest.approx(100 * 0.01 + 60 * 0.03)


def test_passive_fill_rules():
    asks = [(0.03, 50.0), (0.04, 10.0)]
    assert simulate_passive_check(asks, 0.03, 20, FEE, "trade_through") == []
    f = simulate_passive_check(asks, 0.03, 20, FEE, "touch")
    assert f[0].shares == 20 and f[0].price == 0.03 and f[0].fee == 0.0 and f[0].role == "maker"
    f2 = simulate_passive_check([(0.02, 5.0)], 0.03, 20, FEE)
    assert f2[0].shares == 5    # partial


# ------------------------------------------------------------------ accounting / balances
def _acct(session, bal=20.0) -> Account:
    a = Account(name="t", strategy_key="A", params_json="{}", risk_json="{}", initial_balance=bal, cash=bal,
                reserved=0.0, peak_equity=bal, created_ts=0)
    session.add(a)
    session.flush()
    return a


def _seed_strategy(session):
    from app.models import Strategy
    if not session.get(Strategy, "A"):
        session.add(Strategy(key="A", name="A", description="", default_params_json="{}"))
        session.flush()


def test_reserve_fill_release_settle_balances(session):
    _seed_strategy(session)
    a = _acct(session)
    cost_cap = max_cost(0.03, 100, FEE)
    accounting.reserve(session, a, cost_cap, "TX-1")
    assert a.cash == pytest.approx(20 - cost_cap) and a.reserved == pytest.approx(cost_cap)
    r = simulate_marketable_buy(BOOK_THIN_UNDERDOG, 0.03, 100, FEE)
    paid = r.notional + r.fees
    accounting.debit_fill(session, a, paid, "TX-1", "fill")
    accounting.release(session, a, cost_cap - paid, "TX-1")
    assert a.reserved == pytest.approx(0, abs=1e-9)
    assert a.cash == pytest.approx(20 - paid)
    accounting.credit_settlement(session, a, 100.0, "TX-1", "won")
    assert a.cash == pytest.approx(20 - paid + 100)
    session.flush()
    kinds = [l.kind for l in session.scalars(select(AccountLedger).where(AccountLedger.account_id == a.id))]
    assert kinds == ["reserve", "trade_debit", "release", "settlement_credit"]


def test_balance_never_negative(session):
    _seed_strategy(session)
    a = _acct(session, 1.0)
    with pytest.raises(accounting.InsufficientFunds):
        accounting.reserve(session, a, 1.5, "TX-2")
    with pytest.raises(accounting.InsufficientFunds):
        accounting.withdraw(session, a, 2.0)
    assert a.cash == 1.0


def test_manual_adjustments_are_ledgered(session):
    _seed_strategy(session)
    a = _acct(session)
    accounting.deposit(session, a, 5)
    accounting.withdraw(session, a, 3)
    accounting.reset(session, a, 50)
    session.flush()
    rows = session.scalars(select(AccountLedger).where(AccountLedger.account_id == a.id)).all()
    assert [r.kind for r in rows] == ["deposit", "withdrawal", "reset"]
    assert all(r.manual for r in rows)
    assert a.cash == 50 and a.initial_balance == 50


def test_risk_blocks_zero_balance_and_limits(session):
    _seed_strategy(session)
    a = _acct(session, 0.0)
    d = risk.check(session, a, 1, 1.0, 10, 0.01, None, None, 0.0)
    assert not d.ok and "insufficient funds" in d.reason
    b = _acct(session, 20.0)
    d2 = risk.check(session, b, 1, 5.0, 10, 0.01, None, None, 20.0)
    assert not d2.ok and "max per trade" in d2.reason
    d3 = risk.check(session, b, 1, 1.0, 0.5, 0.01, None, None, 20.0)
    assert not d3.ok and "liquidity" in d3.reason
    assert risk.check(session, b, 1, 1.0, 10, 0.01, None, None, 20.0).ok
