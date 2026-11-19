"""Strategy Builder: loss protection, sizing, share codes, safety margin."""
from app.providers.polymarket.fees import FeeSchedule
from app.services.custom_strategies import from_code, to_code
from app.services.market_state import MarketState
from app.strategies.custom import evaluate_custom, safety_z, stake_usd


def test_stake_depends_only_on_balance_and_is_capped_by_max_loss():
    p = {"stake_mode": "percent", "stake_value": 20, "max_loss_pct": 5}
    assert stake_usd(p, 100) == 5.0          # 20% wanted, but one loss may cost at most 5%
    assert stake_usd(p, 200) == 10.0         # scales with balance only
    assert stake_usd({"stake_mode": "fixed", "stake_value": 3, "max_loss_pct": 50}, 100) == 3.0
    assert stake_usd({"stake_mode": "fixed", "stake_value": 3, "max_loss_pct": 50, "max_order_usd": 2}, 100) == 2.0


def test_share_code_roundtrip_and_link():
    params = {"side": "favourite", "min_price": 0.95, "max_price": 0.97, "z_min": 4}
    code = to_code("My strat", params)
    d = from_code(code)
    assert d["name"] == "My strat" and d["params"]["min_price"] == 0.95 and d["params"]["z_min"] == 4
    assert from_code(f"https://x.io/strategies/?code={code}")["params"]["max_price"] == 0.97


def _st(secs, spot, ptb=100.0, up_ask=0.96, tw=None):
    dn = round(1 - up_ask, 2)
    return MarketState(market_id=1, asset="BTC", slug="x", condition_id=None, up_token="u", down_token="d", open_ts=0,
                       close_ts=300_000, server_ts=1795000000000, secs_remaining=secs, open_price=ptb, fee=FeeSchedule(),
                       min_order_size=5, tick_size=0.01, up_bid=up_ask - 0.01, up_ask=up_ask, down_bid=dn - 0.01, down_ask=dn,
                       up_asks=[(up_ask, 500.0)], down_asks=[(dn, 500.0)], book_ok=True, spot_ok=True,
                       features={"spot": spot, "vol_30s": 0.5, "twap_window": tw, "mom_10s": 0.0})


def test_safety_margin_cases():
    assert safety_z(_st(90, 100.5), "UP") > 0                 # above the line -> UP safe
    assert safety_z(_st(90, 99.5), "UP") <= 0                 # below the line -> UP losing
    far, near = safety_z(_st(30, 100.5, tw=100.5), "UP"), safety_z(_st(30, 100.05, tw=100.05), "UP")
    assert far > near > 0                                     # further from the line = bigger margin


def test_custom_favourite_buys_and_filters():
    p = {"side": "favourite", "min_price": 0.95, "max_price": 0.97, "entry_min_secs": 40, "entry_max_secs": 75,
         "z_min": 4, "blackout": False}
    d, why = evaluate_custom(_st(60, 100.5, tw=100.5), p)
    assert d is not None, why
    assert d.side == "UP" and d.limit_price == 0.96
    assert evaluate_custom(_st(60, 100.01, tw=100.01), p)[0] is None      # too close to flipping (z < 4)
    assert evaluate_custom(_st(20, 100.5, tw=100.5), p)[0] is None        # outside the time window
    assert evaluate_custom(_st(60, 100.5, up_ask=0.90, tw=100.5), p)[0] is None   # price outside range



def test_predicted_side_buys_what_fast_prices_favour():
    from app.strategies.custom import predicted_side
    st = _st(120, 100.0, up_ask=0.50)
    st.features["fast_spot"] = 100.4             # exchanges already moved up, Polymarket still 50/50
    assert predicted_side(st, {"use_fast": True}) == "UP"
    st.features["fast_spot"] = 99.6
    assert predicted_side(st, {"use_fast": True}) == "DOWN"


def test_scalp_exit_counts_both_fees():
    from app.strategies.custom import scalp_exit
    fee = FeeSchedule()
    p = {"take_profit_cents": 4, "stop_loss_cents": 6}
    assert scalp_exit(p, 0.60, 0.64, fee) is None          # +4c gross is eaten by ~3.4c of fees
    assert scalp_exit(p, 0.60, 0.68, fee) == "take profit"
    assert scalp_exit(p, 0.60, 0.52, fee) == "stop"
    assert scalp_exit({}, 0.60, 0.99, fee) is None         # off by default
