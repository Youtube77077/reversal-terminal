import pytest
from sqlalchemy import func, select

from app.db import now_ms, session_scope
from app.models import Account, AccountLedger, Asset, Checkpoint, Market, Strategy, Transaction
from app.services import credentials
from app.services.reset import reset


def _seed():
    with session_scope() as s:
        if not s.get(Strategy, "A"):
            s.add(Strategy(key="A", name="A", description="", default_params_json="{}"))
        if not s.get(Asset, "BTC"):
            s.add(Asset(symbol="BTC", name="Bitcoin", slug_prefix="btc", chainlink_symbol="btc/usd"))
        a = Account(name="r", strategy_key="A", params_json="{}", risk_json="{}", initial_balance=20, cash=3.0,
                    reserved=0.0, peak_equity=20, created_ts=0)
        s.add(a)
        m = Market(asset="BTC", slug=f"btc-updown-5m-r{now_ms()}", open_ts=0, close_ts=1000, status="resolved")
        s.add(m)
        s.flush()
        s.add(Transaction(id=f"TX-R{now_ms()}"[:24], account_id=a.id, strategy_key="A", market_id=m.id, asset="BTC",
                          outcome="UP", order_type="marketable_limit", limit_price=0.02, requested_shares=50,
                          filled_shares=50, total_cost=1.07, status="lost", created_ts=1, net_profit=-1.07))
        s.add(Checkpoint(market_id=m.id, asset="BTC", t_minus=10, server_ts=1, actual_secs_remaining=10, valid=True))
        return a.id


def test_reset_paper_trading_zeroes_stats_and_restores_balance():
    aid = _seed()
    out = reset(paper=True, live=False, research=False, starting_balance=50)
    assert out["ok"] and out["backup"]
    with session_scope() as s:
        assert s.scalar(select(func.count()).select_from(Transaction).where(Transaction.account_id == aid)) == 0
        a = s.get(Account, aid)
        assert a.cash == 50 and a.initial_balance == 50 and a.reserved == 0
        kinds = s.scalars(select(AccountLedger.kind).where(AccountLedger.account_id == aid)).all()
        assert kinds == ["initial"]
        assert s.scalar(select(func.count()).select_from(Checkpoint)) >= 1   # research untouched


def test_reset_research_clears_analytics():
    _seed()
    reset(paper=False, live=False, research=True)
    with session_scope() as s:
        assert s.scalar(select(func.count()).select_from(Checkpoint)) == 0


def test_reset_requires_a_scope():
    with pytest.raises(ValueError):
        reset(False, False, False)


def test_credentials_encrypted_roundtrip_and_masking():
    pk = "0x" + "ab" * 32
    credentials.save({"private_key": pk, "wallet_address": "0x" + "12" * 20, "relayer_key": "rk"})
    raw = credentials._path().read_bytes()
    assert pk.encode() not in raw and b"abab" not in raw       # not stored in plain text
    assert credentials.load()["private_key"] == pk
    m = credentials.masked()
    assert m["configured"] and m["private_key"].startswith("0xabab") and "…" in m["private_key"]
    assert m["gasless"] is True and pk not in str(m)
    credentials.delete()
    assert credentials.masked() == {"configured": False}


def test_credentials_validation():
    with pytest.raises(ValueError):
        credentials.validate({"private_key": "nothex"})
    with pytest.raises(ValueError):
        credentials.validate({"private_key": "ab" * 32, "builder_key": "x"})   # builder needs all three
    v = credentials.validate({"private_key": "ab" * 32})
    assert v["private_key"].startswith("0x")
