import math

import pytest

from app.constants import price_bucket, probability_bucket
from app.providers.polymarket.fees import FeeSchedule, maker_fee, round_fee, taker_fee
from app.providers.polymarket.resolution import winner_from_prices
from app.services.calculator import calculate, table
from app.services.market_state import MarketState
from app.services.orderbook import TokenBook, vwap_for_usd, walk_asks
from app.services.reversal import classify
from app.services.statistics import (
    break_even_probability,
    brier_score,
    expected_value,
    log_loss,
    max_drawdown,
    wilson_interval,
)


# ------------------------------------------------------------------ fees
def test_fee_matches_documented_examples():
    s = FeeSchedule(rate=0.07, verified=True)
    assert taker_fee(100, 0.50, s) == pytest.approx(1.75)
    assert taker_fee(100, 0.05, s) == pytest.approx(0.3325)
    assert taker_fee(100, 0.99, s) == pytest.approx(0.0693)
    assert taker_fee(100, 0.30, s) == taker_fee(100, 0.70, s)


def test_fee_rounding_and_minimum():
    assert round_fee(0.000004) == 0.0
    assert round_fee(0.123456789) == 0.12346
    assert taker_fee(1, 0.001, FeeSchedule()) == 0.00007


def test_maker_pays_no_fee_and_unverified_is_estimated():
    assert maker_fee(100, 0.5, FeeSchedule(taker_only=True)) == 0.0
    assert FeeSchedule(verified=False).estimated
    assert FeeSchedule(exponent=2, verified=True).estimated


# ------------------------------------------------------------------ settlement / probability
def test_settlement_rule_ties_resolve_up():
    assert winner_from_prices(100.0, 100.0) == "UP"
    assert winner_from_prices(100.0, 100.01) == "UP"
    assert winner_from_prices(100.0, 99.99) == "DOWN"
    assert winner_from_prices(None, 1.0) is None


def _state(up_bid, up_ask, dn_bid, dn_ask):
    return MarketState(market_id=1, asset="BTC", slug="x", condition_id=None, up_token="u", down_token="d",
                       open_ts=0, close_ts=300_000, server_ts=290_000, secs_remaining=10, open_price=100.0,
                       fee=FeeSchedule(), min_order_size=5, tick_size=0.01, up_bid=up_bid, up_ask=up_ask,
                       down_bid=dn_bid, down_ask=dn_ask, book_ok=True)


def test_implied_probability_and_favourite():
    st = _state(0.97, 0.98, 0.02, 0.03)
    assert st.up_prob == pytest.approx(0.975)
    assert st.favourite == "UP" and st.underdog == "DOWN"
    assert st.fav_prob == pytest.approx(0.975)
    one_sided = _state(None, None, 0.02, 0.04)
    assert one_sided.up_prob == pytest.approx(0.97)
    # near expiry: UP has only an ask at 0.01, DOWN only a bid at 0.99 (observed live)
    extreme = _state(None, 0.01, 0.99, None)
    assert extreme.favourite == "DOWN" and extreme.underdog == "UP"
    assert extreme.fav_prob == pytest.approx(0.99)
    assert _state(None, None, None, None).favourite is None


def test_buckets():
    assert probability_bucket(0.995) == "99.5-100%"
    assert probability_bucket(1.0) == "99.5-100%"
    assert probability_bucket(0.9799) == "97-98%"
    assert price_bucket(0.005) == "<1c"
    assert price_bucket(0.03) == "3-5c"
    assert price_bucket(0.2) == "15-20c"
    assert price_bucket(0.25) is None


# ------------------------------------------------------------------ reversal classification
def test_probability_reversal():
    c = classify("UP", "DOWN", [0.9, 0.95], 100, 0.5, 101, "UP")
    assert c.favourite_lost is True and c.underdog_won is True
    assert c.price_crossover_after is False         # prices never crossed...
    assert c.settlement_reversal is True            # ...but late expectation was wrong


def test_event_types_are_distinct():
    c = classify("UP", "UP", [0.4, 0.8], 100, 1.0, 99, "UP")
    assert c.favourite_lost is False
    assert c.price_crossover_after is True          # crossed then came back
    assert c.underlying_reversal is True            # momentum up, then moved down
    assert c.settlement_reversal is False
    nores = classify("UP", None, [], None, None, None, None)
    assert nores.favourite_lost is None


# ------------------------------------------------------------------ order book
def test_book_walk_and_vwap():
    asks = [(0.03, 100.0), (0.02, 40.0), (0.05, 500.0)]
    fills = walk_asks(asks, 0.03, 120)
    assert [(f.price, f.shares) for f in fills] == [(0.02, 40.0), (0.03, 80.0)]
    assert vwap_for_usd(asks, 0.8) == pytest.approx(0.02)
    assert vwap_for_usd([(0.5, 1.0)], 10) is None   # too thin


def test_token_book_updates():
    b = TokenBook("t")
    b.apply_snapshot([{"price": "0.01", "size": "10"}, {"price": "0.02", "size": "5"}],
                     [{"price": "0.04", "size": "7"}, {"price": "0.03", "size": "9"}], 1, 2)
    assert b.best_bid == 0.02 and b.best_ask == 0.03 and b.spread == pytest.approx(0.01)
    b.apply_change("SELL", 0.03, 0, 3, 4)
    assert b.best_ask == 0.04
    b.apply_change("BUY", 0.025, 3, 3, 4)
    assert b.best_bid == 0.025


def test_order_sizing_never_below_exchange_minimum():
    from app.strategies.library import size_order
    for px in (0.01, 0.02, 0.03, 0.06, 0.07, 0.11, 0.13, 0.17, 0.19):
        sh = size_order(1.0, px, 5.0)
        assert sh * px >= 1.0 - 1e-9 and sh >= 5
    assert size_order(1.0, 0.02, 5.0) == 50.0


# ------------------------------------------------------------------ statistics / EV
def test_wilson_interval():
    lo, hi = wilson_interval(5, 100)
    assert 0.02 < lo < 0.03 and 0.11 < hi < 0.12
    assert wilson_interval(0, 0) == (None, None)
    lo0, hi0 = wilson_interval(0, 50)
    assert lo0 == 0.0 and hi0 > 0


def test_brier_logloss_drawdown():
    assert brier_score([0.9, 0.1], [1, 0]) == pytest.approx(0.01)
    assert log_loss([0.5], [1]) == pytest.approx(math.log(2))
    mdd, pct = max_drawdown([20, 22, 11, 15])
    assert mdd == 11 and pct == pytest.approx(0.5)


def test_expected_value_and_breakeven():
    assert break_even_probability(0.03, 0.002037, 0.0) == pytest.approx(0.032037)
    assert expected_value(0.05, 0.97, -0.03) == pytest.approx(0.05 * 0.97 - 0.95 * 0.03)


def test_calculator_breakeven_includes_all_costs():
    r = calculate(0.03, investment=1.0, reversal_frequency=0.05)
    assert r["shares"] == pytest.approx(1 / 0.03)
    assert r["total_cost"] == pytest.approx(1.0 + r["fee"])
    assert r["breakeven_probability"] == pytest.approx(r["total_cost"] / r["shares"])
    assert r["breakeven_probability"] > 0.03
    assert r["expected_value"] == pytest.approx(0.05 * r["net_profit_if_win"] + 0.95 * r["net_loss_if_lose"])
    rows = table(1.0)
    assert [x["price"] for x in rows] == [0.01, 0.02, 0.03, 0.04, 0.05, 0.07, 0.10, 0.15, 0.20]
    assert all(x["min_reversal_frequency"] > x["price"] for x in rows)
