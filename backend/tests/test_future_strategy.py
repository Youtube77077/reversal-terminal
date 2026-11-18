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
    # 90s left, coin just above the price to beat -> model ~ 50-60%, underdog priced at 6c
    d, why = evaluate("O", _st(90, 100.002, 100.001), {}, StrategyContext())
    assert d is not None, why
    assert d.side == "UP" and d.decision_ask == 0.06 and d.limit_price == 0.07   # may pay 1 tick more to get filled


def test_skips_when_not_crossed_if_rule_on():
    d, why = evaluate("O", _st(90, 99.995, 99.995), {"require_cross": True}, StrategyContext())
    assert d is None and "crossed" in why
    d2, _ = evaluate("O", _st(90, 99.995, 99.995), {}, StrategyContext())   # default: model decides
    assert d2 is not None


def test_skips_when_model_far_above_market():
    # coin far above the line but market still prices UP at 6c -> our feed likely wrong, skip
    d, why = evaluate("O", _st(90, 100.5, 100.4), {}, StrategyContext())
    assert d is None and "too far" in why


def test_skips_outside_window_price_and_without_exact_reference():
    assert evaluate("O", _st(45, 100.002, 100.001), {}, StrategyContext())[0] is None       # last 60s
    assert evaluate("O", _st(90, 100.002, 100.001, up_ask=0.02), {}, StrategyContext())[0] is None  # < 3c
    assert evaluate("O", _st(90, 100.002, 100.001, up_ask=0.20), {}, StrategyContext())[0] is None  # > 15c
    d, why = evaluate("O", _st(90, 100.002, 100.001, exact=False), {}, StrategyContext())
    assert d is None and "price to beat" in why


def test_uses_fast_price_when_available():
    # Chainlink still below the line, fast exchanges already above -> cross is seen early
    d, _ = evaluate("O", _st(90, 99.99, 99.99, fast=100.002), {"require_cross": True}, StrategyContext())
    assert d is not None
    d2, _ = evaluate("O", _st(90, 99.99, 99.99, fast=100.002), {"require_cross": True, "use_fast": False},
                     StrategyContext())
    assert d2 is None


def test_bids_fills_only_full_and_above_target():
    assert _bids_fills([(0.92, 10), (0.91, 10)], 15, 0.90) == [(0.92, 10), (0.91, 5)]
    assert _bids_fills([(0.92, 5), (0.85, 100)], 15, 0.90) is None   # not enough depth at >= 90c
    assert _bids_fills([], 5, 0.9) is None


def test_window_labels_and_slugs():
    from app.providers.polymarket.discovery import label_of, slug_for, window_start
    assert slug_for("BTC", 1795009500, "15m") == "btc-updown-15m-1795009500"
    assert label_of("btc-updown-15m-1795009500") == "15m"
    assert label_of("eth-updown-5m-1795009500") == "5m"
    assert window_start(1795009999, 900) == 1795009500
