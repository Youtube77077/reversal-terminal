"""Smart Future Trading (O) and early-exit helpers."""
from app.execution.engine import _bids_fills
from app.providers.polymarket.fees import FeeSchedule
from app.services.market_state import MarketState
from app.strategies.library import StrategyContext, evaluate


def _st(secs, spot, twap_window, fast=None, up_ask=0.06, exact=True, vol=0.6):
    """UP is the underdog at ``up_ask``; price to beat is 100.0."""
    dn_bid = round(1 - up_ask - 0.01, 2)
    return MarketState(
        market_id=1, asset="BTC", slug="x", condition_id=None, up_token="u", down_token="d",
        open_ts=0, close_ts=300_000, server_ts=300_000 - int(secs * 1000), secs_remaining=secs, open_price=100.0,
        fee=FeeSchedule(), min_order_size=5, tick_size=0.01,
        up_bid=round(up_ask - 0.01, 2), up_ask=up_ask, down_bid=dn_bid, down_ask=round(1 - up_ask + 0.01, 2),
        up_asks=[(up_ask, 500.0)], down_asks=[(round(1 - up_ask + 0.01, 2), 500.0)],
        up_bids=[(round(up_ask - 0.01, 2), 500.0)], down_bids=[(dn_bid, 500.0)], book_ok=True, spot_ok=True,
        features={"spot": spot, "fast_spot": fast, "twap_window": twap_window, "vol_30s": vol, "ptb_exact": exact})


def test_buys_cheap_underdog_just_after_cross():
    # 45s left, coin just above the price to beat, window average a bit above too -> model ~ 50-60%
    d, why = evaluate("O", _st(45, 100.004, 100.001), {}, StrategyContext())
    assert d is not None, why
    assert d.side == "UP" and d.limit_price == 0.06


def test_skips_when_not_crossed():
    d, why = evaluate("O", _st(45, 99.99, 99.99), {}, StrategyContext())
    assert d is None and "crossed" in why


def test_skips_when_model_far_above_market():
    # coin far above the line but market still prices UP at 6c -> our feed likely wrong, skip
    d, why = evaluate("O", _st(45, 100.5, 100.4), {}, StrategyContext())
    assert d is None and "too far" in why


def test_skips_outside_window_price_and_without_exact_reference():
    assert evaluate("O", _st(20, 100.004, 100.001), {}, StrategyContext())[0] is None       # last 30s
    assert evaluate("O", _st(45, 100.004, 100.001, up_ask=0.02), {}, StrategyContext())[0] is None  # < 3c
    assert evaluate("O", _st(45, 100.004, 100.001, up_ask=0.15), {}, StrategyContext())[0] is None  # > 10c
    d, why = evaluate("O", _st(45, 100.004, 100.001, exact=False), {}, StrategyContext())
    assert d is None and "price to beat" in why


def test_uses_fast_price_when_available():
    # Chainlink still below the line, fast exchanges already above -> cross is seen early
    d, _ = evaluate("O", _st(45, 99.999, 100.001, fast=100.004), {}, StrategyContext())
    assert d is not None
    d2, _ = evaluate("O", _st(45, 99.999, 100.001, fast=100.004), {"use_fast": False}, StrategyContext())
    assert d2 is None


def test_bids_fills_only_full_and_above_target():
    assert _bids_fills([(0.92, 10), (0.91, 10)], 15, 0.90) == [(0.92, 10), (0.91, 5)]
    assert _bids_fills([(0.92, 5), (0.85, 100)], 15, 0.90) is None   # not enough depth at >= 90c
    assert _bids_fills([], 5, 0.9) is None
