from app.providers.polymarket.discovery import parse_event, slug_for, window_start

from .fixtures import GAMMA_EVENT, resolved_event


def test_window_alignment_and_slug():
    assert window_start(1794933345.7) == 1794933300
    assert window_start(1794933300) == 1794933300
    assert slug_for("BTC", 1794933300) == "btc-updown-5m-1794933300"
    assert slug_for("HYPE", 1794933300) == "hype-updown-5m-1794933300"


def test_market_identification():
    dm = parse_event("BTC", "btc-updown-5m-1794933300", GAMMA_EVENT)
    assert dm.condition_id == "0xabc"
    assert dm.open_ts == 1794933300 * 1000
    assert dm.close_ts - dm.open_ts == 300_000
    assert dm.status == "active"
    assert dm.twap_lookback_s == 60
    assert "TWAP" in dm.settlement_method
    assert dm.resolution_source.endswith("btc-usd-twap-60s-streams")
    assert dm.min_order_size == 5 and dm.tick_size == 0.01
    assert dm.substitution_note is None


def test_outcome_identification_by_label():
    dm = parse_event("BTC", "btc-updown-5m-1794933300", GAMMA_EVENT)
    assert dm.up_token_id == "111" and dm.down_token_id == "222"
    swapped = resolved_event("UP", swap_outcomes=True)
    dm2 = parse_event("BTC", "btc-updown-5m-1794933300", swapped)
    assert dm2.up_token_id == "111" and dm2.down_token_id == "222"   # mapped by label, not position
    assert "mapped by label" in dm2.substitution_note
    assert dm2.official_winner == "UP"


def test_official_winner_only_when_resolved():
    dm = parse_event("BTC", "btc-updown-5m-1794933300", GAMMA_EVENT)
    assert dm.official_winner is None
    assert parse_event("BTC", "btc-updown-5m-1794933300", resolved_event("DOWN")).official_winner == "DOWN"


def test_substitution_is_recorded():
    ev = resolved_event("UP")
    ev["markets"][0]["slug"] = "btc-updown-5m-1794933000"
    dm = parse_event("BTC", "btc-updown-5m-1794933300", ev)
    assert "SUBSTITUTION" in dm.substitution_note


def test_fee_schedule_read_from_market():
    dm = parse_event("BTC", "btc-updown-5m-1794933300", GAMMA_EVENT)
    assert dm.fee.verified and dm.fee.rate == 0.07 and dm.fee.exponent == 1 and dm.fee.taker_only
    assert not dm.fee.estimated
