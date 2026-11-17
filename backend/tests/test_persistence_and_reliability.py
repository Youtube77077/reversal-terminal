import asyncio
import json

import pytest
from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.db import session_scope
from app.models import Asset, Experiment, Market, MarketObservation
from app.services.price_store import PriceStore
from app.strategies.library import StrategyContext, evaluate


def _market(s, slug="btc-updown-5m-100") -> Market:
    if not s.get(Asset, "BTC"):
        s.add(Asset(symbol="BTC", name="Bitcoin", slug_prefix="btc", chainlink_symbol="btc/usd"))
    m = Market(asset="BTC", slug=slug, open_ts=100_000, close_ts=400_000, status="active")
    s.add(m)
    s.flush()
    return m


def test_database_persistence_roundtrip():
    with session_scope() as s:
        mid = _market(s, "btc-updown-5m-200").id
    with session_scope() as s:
        assert s.get(Market, mid).slug == "btc-updown-5m-200"


def test_duplicate_observations_are_prevented():
    with session_scope() as s:
        mid = _market(s, "btc-updown-5m-300").id
    row = {"market_id": mid, "asset": "BTC", "ts_sec": 123, "server_ts": 123000, "secs_remaining": 10.0,
           "book_ok": True, "spot_ok": True}
    for _ in range(3):
        with session_scope() as s:
            s.execute(sqlite_insert(MarketObservation).values([row]).on_conflict_do_nothing())
    with session_scope() as s:
        assert s.scalar(select(func.count()).select_from(MarketObservation)
                        .where(MarketObservation.market_id == mid)) == 1


def test_experiment_survives_restart_and_completes():
    """Experiments are rows in the DB: a 'restart' (new session) sees them and the watchdog completes them."""
    from app.services import experiments as ex

    ex.seed_strategies_and_accounts()
    out = ex.start_experiment("t", "1h", ["BTC"], [], 20.0, True)
    with session_scope() as s:
        e = s.get(Experiment, out["id"])
        assert e.status == "running"
        e.ends_ts = 1  # pretend the machine slept through the end time

    async def one_pass():
        task = asyncio.create_task(ex.experiment_watchdog())
        await asyncio.sleep(1.5)
        task.cancel()

    asyncio.run(one_pass())
    with session_scope() as s:
        e = s.get(Experiment, out["id"])
        assert e.status == "completed" and e.report_id is not None


def test_price_store_no_lookahead_and_momentum():
    ps = PriceStore()
    for i in range(70):
        ps.add("BTC", "chainlink", 100 + i * 0.1, None, server_ts=1_000_000 + i * 1000)
    f = ps.features("BTC", "chainlink", at=1_000_000 + 60_000, open_price=100.0)
    assert f["spot"] == pytest.approx(106.0)          # value at t=60s, NOT the later ticks
    assert f["mom_10s"] == pytest.approx(1.0)
    assert f["dist_bps"] == pytest.approx(600.0)
    assert f["twap60_est"] == pytest.approx(103.0, abs=0.06)


def test_websocket_reconnects_with_backoff(monkeypatch):
    """MarketChannel must reconnect after a dropped connection and resubscribe."""
    from app.providers.polymarket import market_ws

    attempts = {"n": 0}

    class FakeWS:
        def __init__(self):
            self.sent = []

        async def __aenter__(self):
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise ConnectionError("simulated drop")
            return self

        async def __aexit__(self, *a):
            return False

        async def send(self, m):
            self.sent.append(m)

        def __aiter__(self):
            return self

        async def __anext__(self):
            await asyncio.sleep(0.05)
            raise StopAsyncIteration

        async def close(self):
            pass

    monkeypatch.setattr(market_ws.websockets, "connect", lambda *a, **k: FakeWS())
    monkeypatch.setattr(market_ws.random, "random", lambda: 0.0)

    async def run():
        ch = market_ws.MarketChannel("wss://example.invalid")
        await ch.track(["111", "222"])
        ch.start()
        await asyncio.sleep(2.5)
        await ch.stop()
        return ch

    ch = asyncio.run(run())
    assert attempts["n"] >= 2
    assert ch.attempt >= 1


def test_strategy_uses_only_present_information():
    from app.providers.polymarket.fees import FeeSchedule
    from app.services.market_state import MarketState

    st = MarketState(market_id=1, asset="BTC", slug="x", condition_id=None, up_token="u", down_token="d", open_ts=0,
                     close_ts=300_000, server_ts=290_000, secs_remaining=10.0, open_price=100.0, fee=FeeSchedule(),
                     min_order_size=5, tick_size=0.01, up_bid=0.96, up_ask=0.97, down_bid=0.03, down_ask=0.04,
                     down_asks=[(0.04, 500.0)], up_asks=[(0.97, 500.0)], book_ok=True)
    d, why = evaluate("A", st, {"max_price": 0.05}, StrategyContext())
    assert d is not None and d.side == "DOWN" and d.limit_price == 0.04 and d.shares >= 25
    d2, why2 = evaluate("A", st, {"max_price": 0.03}, StrategyContext())
    assert d2 is None and "max" in why2
    # Strategy I refuses to trade without enough historical (pre-decision) evidence
    d3, why3 = evaluate("I", st, {}, StrategyContext(hist_lookup=lambda a, t, p: (1, 10)))
    assert d3 is None and "sample" in why3
    d4, _ = evaluate("I", st, {"use_lower_ci": False, "min_edge": 0.0},
                     StrategyContext(hist_lookup=lambda a, t, p: (30, 200)))
    assert d4 is not None  # 15% observed vs ~4.3% break-even
