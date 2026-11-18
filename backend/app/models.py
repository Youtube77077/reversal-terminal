"""SQLAlchemy ORM models. All timestamps are UTC epoch milliseconds (BigInteger)."""
from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


# ---------------------------------------------------------------- reference
class Asset(Base):
    __tablename__ = "assets"
    symbol: Mapped[str] = mapped_column(String(8), primary_key=True)
    name: Mapped[str] = mapped_column(String(32))
    slug_prefix: Mapped[str] = mapped_column(String(16))
    chainlink_symbol: Mapped[str] = mapped_column(String(16))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    paused: Mapped[bool] = mapped_column(Boolean, default=False)  # trading pause only
    status: Mapped[str] = mapped_column(String(16), default="unknown")  # live|unavailable|offline
    status_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    current_market_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_ts: Mapped[int] = mapped_column(BigInteger, default=0)


class Market(Base):
    __tablename__ = "markets"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    asset: Mapped[str] = mapped_column(String(8), ForeignKey("assets.symbol"), index=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    window: Mapped[str] = mapped_column(String(4), default="5m")
    gamma_event_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    gamma_market_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    condition_id: Mapped[str | None] = mapped_column(String(80), index=True, nullable=True)
    question_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    question: Mapped[str | None] = mapped_column(Text, nullable=True)
    up_token_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    down_token_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    open_ts: Mapped[int] = mapped_column(BigInteger, index=True)
    close_ts: Mapped[int] = mapped_column(BigInteger, index=True)
    status: Mapped[str] = mapped_column(String(16), default="upcoming", index=True)
    # upcoming|active|closed|resolved|cancelled|unavailable
    resolution_source: Mapped[str | None] = mapped_column(Text, nullable=True)
    settlement_method: Mapped[str | None] = mapped_column(Text, nullable=True)
    twap_lookback_s: Mapped[int | None] = mapped_column(Integer, nullable=True)
    open_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    close_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    open_price_source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    winner: Mapped[str | None] = mapped_column(String(4), nullable=True)
    resolved_ts: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    fee_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    fee_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    fee_exponent: Mapped[float | None] = mapped_column(Float, nullable=True)
    fee_taker_only: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    fee_rebate_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    fee_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    tick_size: Mapped[float | None] = mapped_column(Float, nullable=True)
    min_order_size: Mapped[float | None] = mapped_column(Float, nullable=True)
    neg_risk: Mapped[bool] = mapped_column(Boolean, default=False)
    restricted: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    substitution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    observation_count: Mapped[int] = mapped_column(Integer, default=0)
    discovered_ts: Mapped[int] = mapped_column(BigInteger, default=0)
    raw_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (Index("ix_markets_asset_open", "asset", "open_ts"),)


class MarketObservation(Base):
    """One per market per second (unique on market_id + ts_sec)."""

    __tablename__ = "market_observations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market_id: Mapped[int] = mapped_column(Integer, ForeignKey("markets.id"), index=True)
    asset: Mapped[str] = mapped_column(String(8))
    ts_sec: Mapped[int] = mapped_column(BigInteger)
    server_ts: Mapped[int] = mapped_column(BigInteger, index=True)
    book_exchange_ts: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    secs_remaining: Mapped[float] = mapped_column(Float)
    up_bid: Mapped[float | None] = mapped_column(Float, nullable=True)
    up_ask: Mapped[float | None] = mapped_column(Float, nullable=True)
    down_bid: Mapped[float | None] = mapped_column(Float, nullable=True)
    down_ask: Mapped[float | None] = mapped_column(Float, nullable=True)
    up_mid: Mapped[float | None] = mapped_column(Float, nullable=True)
    down_mid: Mapped[float | None] = mapped_column(Float, nullable=True)
    up_bid_size: Mapped[float | None] = mapped_column(Float, nullable=True)
    up_ask_size: Mapped[float | None] = mapped_column(Float, nullable=True)
    down_bid_size: Mapped[float | None] = mapped_column(Float, nullable=True)
    down_ask_size: Mapped[float | None] = mapped_column(Float, nullable=True)
    up_ask_liq: Mapped[float | None] = mapped_column(Float, nullable=True)
    down_ask_liq: Mapped[float | None] = mapped_column(Float, nullable=True)
    up_bid_liq: Mapped[float | None] = mapped_column(Float, nullable=True)
    down_bid_liq: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_trade_up: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_trade_down: Mapped[float | None] = mapped_column(Float, nullable=True)
    trade_volume: Mapped[float | None] = mapped_column(Float, nullable=True)  # shares traded since prev obs
    spot: Mapped[float | None] = mapped_column(Float, nullable=True)
    spot_exchange_ts: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    spot_source: Mapped[str | None] = mapped_column(String(16), nullable=True)
    twap60_est: Mapped[float | None] = mapped_column(Float, nullable=True)
    open_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    dist_abs: Mapped[float | None] = mapped_column(Float, nullable=True)
    dist_bps: Mapped[float | None] = mapped_column(Float, nullable=True)
    mom_1s: Mapped[float | None] = mapped_column(Float, nullable=True)
    mom_3s: Mapped[float | None] = mapped_column(Float, nullable=True)
    mom_5s: Mapped[float | None] = mapped_column(Float, nullable=True)
    mom_10s: Mapped[float | None] = mapped_column(Float, nullable=True)
    mom_30s: Mapped[float | None] = mapped_column(Float, nullable=True)
    mom_60s: Mapped[float | None] = mapped_column(Float, nullable=True)
    vol_30s: Mapped[float | None] = mapped_column(Float, nullable=True)
    accel: Mapped[float | None] = mapped_column(Float, nullable=True)
    up_asks_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    down_asks_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    book_ok: Mapped[bool] = mapped_column(Boolean, default=False)
    spot_ok: Mapped[bool] = mapped_column(Boolean, default=False)

    __table_args__ = (UniqueConstraint("market_id", "ts_sec", name="uq_obs_market_sec"),)


class Checkpoint(Base):
    """Market state captured at an exact T-minus checkpoint (never pooled)."""

    __tablename__ = "checkpoints"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market_id: Mapped[int] = mapped_column(Integer, ForeignKey("markets.id"), index=True)
    asset: Mapped[str] = mapped_column(String(8), index=True)
    t_minus: Mapped[int] = mapped_column(Integer, index=True)
    server_ts: Mapped[int] = mapped_column(BigInteger)
    actual_secs_remaining: Mapped[float] = mapped_column(Float)
    favourite: Mapped[str | None] = mapped_column(String(4), nullable=True)
    fav_prob: Mapped[float | None] = mapped_column(Float, nullable=True)
    fav_bid: Mapped[float | None] = mapped_column(Float, nullable=True)
    fav_ask: Mapped[float | None] = mapped_column(Float, nullable=True)
    dog_bid: Mapped[float | None] = mapped_column(Float, nullable=True)
    dog_ask: Mapped[float | None] = mapped_column(Float, nullable=True)
    dog_ask_size: Mapped[float | None] = mapped_column(Float, nullable=True)
    dog_ask_liq: Mapped[float | None] = mapped_column(Float, nullable=True)
    dog_spread: Mapped[float | None] = mapped_column(Float, nullable=True)
    dog_vwap_10usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    spot: Mapped[float | None] = mapped_column(Float, nullable=True)
    open_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    dist_bps: Mapped[float | None] = mapped_column(Float, nullable=True)
    mom_10s: Mapped[float | None] = mapped_column(Float, nullable=True)
    mom_30s: Mapped[float | None] = mapped_column(Float, nullable=True)
    momentum_toward_dog: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    valid: Mapped[bool] = mapped_column(Boolean, default=False)
    invalid_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # filled in after official resolution
    winner: Mapped[str | None] = mapped_column(String(4), nullable=True)
    favourite_lost: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    price_crossover_after: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    underlying_reversal: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    settlement_reversal: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    source: Mapped[str] = mapped_column(String(16), default="live")  # live|historical

    __table_args__ = (UniqueConstraint("market_id", "t_minus", "source", name="uq_ckpt"),)


class OrderBookSnapshot(Base):
    __tablename__ = "orderbook_snapshots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market_id: Mapped[int] = mapped_column(Integer, ForeignKey("markets.id"), index=True)
    server_ts: Mapped[int] = mapped_column(BigInteger, index=True)
    exchange_ts: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    reason: Mapped[str] = mapped_column(String(24))  # checkpoint|order|periodic
    t_minus: Mapped[int | None] = mapped_column(Integer, nullable=True)
    up_bids_json: Mapped[str] = mapped_column(Text, default="[]")
    up_asks_json: Mapped[str] = mapped_column(Text, default="[]")
    down_bids_json: Mapped[str] = mapped_column(Text, default="[]")
    down_asks_json: Mapped[str] = mapped_column(Text, default="[]")


class UnderlyingPrice(Base):
    """Down-sampled (1/s) underlying price per asset and source."""

    __tablename__ = "underlying_prices"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    asset: Mapped[str] = mapped_column(String(8))
    source: Mapped[str] = mapped_column(String(16))
    ts_sec: Mapped[int] = mapped_column(BigInteger)
    exchange_ts: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    price: Mapped[float] = mapped_column(Float)
    __table_args__ = (
        UniqueConstraint("asset", "source", "ts_sec", name="uq_px"),
        Index("ix_px_asset_ts", "asset", "ts_sec"),
    )


class MarketResolution(Base):
    __tablename__ = "market_resolutions"
    market_id: Mapped[int] = mapped_column(Integer, ForeignKey("markets.id"), primary_key=True)
    winner: Mapped[str | None] = mapped_column(String(4), nullable=True)
    open_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    close_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    official: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|provisional|resolved|cancelled
    gamma_outcome_prices: Mapped[str | None] = mapped_column(String(64), nullable=True)
    uma_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    price_api_winner: Mapped[str | None] = mapped_column(String(4), nullable=True)
    sources_agree: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    resolved_ts: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    checked_ts: Mapped[int] = mapped_column(BigInteger, default=0)
    attempts: Mapped[int] = mapped_column(Integer, default=0)


# ---------------------------------------------------------------- trading
class Strategy(Base):
    __tablename__ = "strategies"
    key: Mapped[str] = mapped_column(String(4), primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(Text)
    default_params_json: Mapped[str] = mapped_column(Text)


class Wallet(Base):
    """User-facing wallet: its own practice money, its own (optional) Polymarket keys."""
    __tablename__ = "wallets"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(48))
    is_main: Mapped[bool] = mapped_column(Boolean, default=False)
    created_ts: Mapped[int] = mapped_column(BigInteger, default=0)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)


class Account(Base):
    __tablename__ = "accounts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wallet_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(64))
    mode: Mapped[str] = mapped_column(String(8), default="paper")  # paper only (live disabled)
    strategy_key: Mapped[str] = mapped_column(String(4), ForeignKey("strategies.key"))
    params_json: Mapped[str] = mapped_column(Text, default="{}")
    risk_json: Mapped[str] = mapped_column(Text, default="{}")
    initial_balance: Mapped[float] = mapped_column(Float, default=20.0)
    cash: Mapped[float] = mapped_column(Float, default=20.0)  # available + reserved excluded
    reserved: Mapped[float] = mapped_column(Float, default=0.0)  # locked in pending orders
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    paused: Mapped[bool] = mapped_column(Boolean, default=False)
    halted_reason: Mapped[str | None] = mapped_column(String(128), nullable=True)
    peak_equity: Mapped[float] = mapped_column(Float, default=20.0)
    created_ts: Mapped[int] = mapped_column(BigInteger, default=0)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    # --- session risk budget / stop loss / take profit -----------------------------
    risk_budget_mode: Mapped[str] = mapped_column(String(8), default="off", server_default="off")  # off|percent|amount
    risk_budget_value: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    stop_loss_pct: Mapped[float] = mapped_column(Float, default=100.0, server_default="100")  # % of risk budget
    take_profit_mode: Mapped[str] = mapped_column(String(8), default="off", server_default="off")  # off|percent|amount
    take_profit_value: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    session_start_equity: Mapped[float | None] = mapped_column(Float, nullable=True)
    session_start_ts: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    session_end_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)


class AccountLedger(Base):
    """Every cash movement. Manual adjustments never modify transactions."""

    __tablename__ = "account_ledger"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(Integer, ForeignKey("accounts.id"), index=True)
    ts: Mapped[int] = mapped_column(BigInteger, index=True)
    kind: Mapped[str] = mapped_column(String(24))
    # initial|deposit|withdrawal|reset|reserve|release|trade_debit|settlement_credit
    amount: Mapped[float] = mapped_column(Float)
    cash_after: Mapped[float] = mapped_column(Float)
    reserved_after: Mapped[float] = mapped_column(Float, default=0.0)
    transaction_id: Mapped[str | None] = mapped_column(String(24), nullable=True)
    manual: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class AccountBalanceSnapshot(Base):
    __tablename__ = "account_balances"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(Integer, ForeignKey("accounts.id"), index=True)
    ts: Mapped[int] = mapped_column(BigInteger, index=True)
    cash: Mapped[float] = mapped_column(Float)
    reserved: Mapped[float] = mapped_column(Float)
    open_cost: Mapped[float] = mapped_column(Float)
    unrealized: Mapped[float] = mapped_column(Float)
    equity: Mapped[float] = mapped_column(Float)
    realized: Mapped[float] = mapped_column(Float)


class Signal(Base):
    __tablename__ = "signals"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[int] = mapped_column(BigInteger, index=True)
    account_id: Mapped[int] = mapped_column(Integer, ForeignKey("accounts.id"), index=True)
    strategy_key: Mapped[str] = mapped_column(String(4), index=True)
    experiment_id: Mapped[str | None] = mapped_column(String(24), index=True, nullable=True)
    market_id: Mapped[int] = mapped_column(Integer, ForeignKey("markets.id"), index=True)
    asset: Mapped[str] = mapped_column(String(8))
    side: Mapped[str] = mapped_column(String(4))
    secs_remaining: Mapped[float] = mapped_column(Float)
    fav_prob: Mapped[float | None] = mapped_column(Float, nullable=True)
    entry_ask: Mapped[float | None] = mapped_column(Float, nullable=True)
    ask_liq: Mapped[float | None] = mapped_column(Float, nullable=True)
    spread: Mapped[float | None] = mapped_column(Float, nullable=True)
    dist_bps: Mapped[float | None] = mapped_column(Float, nullable=True)
    decision: Mapped[str] = mapped_column(String(12))  # accepted|rejected
    reject_reason: Mapped[str | None] = mapped_column(String(128), nullable=True)
    detail_json: Mapped[str | None] = mapped_column(Text, nullable=True)


class SimOrder(Base):
    __tablename__ = "simulated_orders"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(Integer, ForeignKey("accounts.id"), index=True)
    signal_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("signals.id"), nullable=True)
    transaction_id: Mapped[str | None] = mapped_column(String(24), index=True, nullable=True)
    market_id: Mapped[int] = mapped_column(Integer, ForeignKey("markets.id"), index=True)
    token_id: Mapped[str] = mapped_column(String(100))
    side: Mapped[str] = mapped_column(String(4))  # UP|DOWN
    action: Mapped[str] = mapped_column(String(4), default="BUY")
    order_type: Mapped[str] = mapped_column(String(20))  # marketable_limit|passive_limit
    tif: Mapped[str] = mapped_column(String(4), default="FAK")  # FAK|FOK|GTD
    limit_price: Mapped[float] = mapped_column(Float)
    requested_shares: Mapped[float] = mapped_column(Float)
    filled_shares: Mapped[float] = mapped_column(Float, default=0.0)
    reserved_amount: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    # pending|partially_filled|filled|cancelled|expired|failed|unfilled
    decision_ts: Mapped[int] = mapped_column(BigInteger)
    executed_ts: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    expire_ts: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(String(160), nullable=True)
    decision_book_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    execution_book_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class SimFill(Base):
    __tablename__ = "simulated_fills"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(Integer, ForeignKey("simulated_orders.id"), index=True)
    ts: Mapped[int] = mapped_column(BigInteger)
    price: Mapped[float] = mapped_column(Float)
    shares: Mapped[float] = mapped_column(Float)
    notional: Mapped[float] = mapped_column(Float)
    fee: Mapped[float] = mapped_column(Float)
    role: Mapped[str] = mapped_column(String(8))  # taker|maker


class Transaction(Base):
    """A simulated position, from signal to settlement."""

    __tablename__ = "transactions"
    id: Mapped[str] = mapped_column(String(24), primary_key=True)
    account_id: Mapped[int] = mapped_column(Integer, ForeignKey("accounts.id"), index=True)
    experiment_id: Mapped[str | None] = mapped_column(String(24), index=True, nullable=True)
    strategy_key: Mapped[str] = mapped_column(String(4), index=True)
    mode: Mapped[str] = mapped_column(String(8), default="paper")
    source: Mapped[str] = mapped_column(String(12), default="live")  # live|backtest
    signal_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    order_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    market_id: Mapped[int] = mapped_column(Integer, ForeignKey("markets.id"), index=True)
    asset: Mapped[str] = mapped_column(String(8), index=True)
    market_duration: Mapped[str] = mapped_column(String(4), default="5m")
    position: Mapped[str] = mapped_column(String(8), default="LONG")
    outcome: Mapped[str] = mapped_column(String(4))  # UP|DOWN
    order_type: Mapped[str] = mapped_column(String(20))
    limit_price: Mapped[float] = mapped_column(Float)
    decision_ask: Mapped[float | None] = mapped_column(Float, nullable=True)
    entry_price: Mapped[float | None] = mapped_column(Float, nullable=True)  # VWAP of fills
    requested_shares: Mapped[float] = mapped_column(Float)
    filled_shares: Mapped[float] = mapped_column(Float, default=0.0)
    unfilled_shares: Mapped[float] = mapped_column(Float, default=0.0)
    gross_cost: Mapped[float] = mapped_column(Float, default=0.0)
    trading_fee: Mapped[float] = mapped_column(Float, default=0.0)
    gas_fee: Mapped[float] = mapped_column(Float, default=0.0)
    network_fee: Mapped[float] = mapped_column(Float, default=0.0)
    slippage: Mapped[float] = mapped_column(Float, default=0.0)
    spread_cost: Mapped[float] = mapped_column(Float, default=0.0)
    total_cost: Mapped[float] = mapped_column(Float, default=0.0)
    fee_estimated: Mapped[bool] = mapped_column(Boolean, default=False)
    potential_payout: Mapped[float] = mapped_column(Float, default=0.0)
    settlement_outcome: Mapped[str | None] = mapped_column(String(4), nullable=True)
    gross_payout: Mapped[float | None] = mapped_column(Float, nullable=True)
    net_profit: Mapped[float | None] = mapped_column(Float, nullable=True)
    roi: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="signal", index=True)
    # signal|pending|partially_filled|filled|won|lost|cancelled|expired|unresolved
    created_ts: Mapped[int] = mapped_column(BigInteger, index=True)
    entry_ts: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    entry_secs_remaining: Mapped[float | None] = mapped_column(Float, nullable=True)
    settled_ts: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    holding_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    entry_snapshot_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class FeeRecord(Base):
    __tablename__ = "fees"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    transaction_id: Mapped[str] = mapped_column(String(24), ForeignKey("transactions.id"), index=True)
    fill_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    kind: Mapped[str] = mapped_column(String(16))  # trading|gas|network|spread|slippage
    amount: Mapped[float] = mapped_column(Float)
    estimated: Mapped[bool] = mapped_column(Boolean, default=False)
    formula: Mapped[str | None] = mapped_column(Text, nullable=True)


# ---------------------------------------------------------------- experiments
class Experiment(Base):
    __tablename__ = "experiments"
    id: Mapped[str] = mapped_column(String(24), primary_key=True)
    name: Mapped[str] = mapped_column(String(96))
    status: Mapped[str] = mapped_column(String(12), index=True)  # running|paused|completed|stopped
    started_ts: Mapped[int] = mapped_column(BigInteger)
    duration_hours: Mapped[float | None] = mapped_column(Float, nullable=True)  # None = unlimited
    ends_ts: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    paused_ts: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    completed_ts: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    starting_balance: Mapped[float] = mapped_column(Float)
    assets_json: Mapped[str] = mapped_column(Text)
    account_ids_json: Mapped[str] = mapped_column(Text)
    config_json: Mapped[str] = mapped_column(Text)
    observation_count: Mapped[int] = mapped_column(Integer, default=0)
    signal_count: Mapped[int] = mapped_column(Integer, default=0)
    trade_count: Mapped[int] = mapped_column(Integer, default=0)
    win_count: Mapped[int] = mapped_column(Integer, default=0)
    loss_count: Mapped[int] = mapped_column(Integer, default=0)
    ending_balance: Mapped[float | None] = mapped_column(Float, nullable=True)
    net_profit: Mapped[float | None] = mapped_column(Float, nullable=True)
    report_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class ExperimentReport(Base):
    __tablename__ = "experiment_reports"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    experiment_id: Mapped[str] = mapped_column(String(24), ForeignKey("experiments.id"), index=True)
    created_ts: Mapped[int] = mapped_column(BigInteger)
    summary_json: Mapped[str] = mapped_column(Text)
    html_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    csv_path: Mapped[str | None] = mapped_column(Text, nullable=True)


# ---------------------------------------------------------------- ops
class ApiConnection(Base):
    __tablename__ = "api_connections"
    key: Mapped[str] = mapped_column(String(48), primary_key=True)
    provider: Mapped[str] = mapped_column(String(48))
    purpose: Mapped[str] = mapped_column(Text)
    base_url: Mapped[str] = mapped_column(Text)
    auth: Mapped[str] = mapped_column(String(48))
    api_key_required: Mapped[bool] = mapped_column(Boolean, default=False)
    websocket: Mapped[bool] = mapped_column(Boolean, default=False)
    rate_limit: Mapped[str] = mapped_column(Text, default="")
    fields_supplied: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="unknown")  # ok|degraded|down|unknown|disabled
    last_success_ts: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    last_error_ts: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    failures: Mapped[int] = mapped_column(Integer, default=0)
    reconnects: Mapped[int] = mapped_column(Integer, default=0)
    messages: Mapped[int] = mapped_column(BigInteger, default=0)


class AppEvent(Base):
    __tablename__ = "app_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[int] = mapped_column(BigInteger, index=True)
    level: Mapped[str] = mapped_column(String(8))
    category: Mapped[str] = mapped_column(String(32), index=True)
    message: Mapped[str] = mapped_column(Text)
    data_json: Mapped[str | None] = mapped_column(Text, nullable=True)


class CollectorGap(Base):
    __tablename__ = "collector_gaps"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    asset: Mapped[str] = mapped_column(String(8), index=True)
    start_ts: Mapped[int] = mapped_column(BigInteger)
    end_ts: Mapped[int] = mapped_column(BigInteger)
    missing_seconds: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(64))


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value_json: Mapped[str] = mapped_column(Text)


class HistoricalMarket(Base):
    """Past markets ingested from public history endpoints (kept separate from live data)."""

    __tablename__ = "historical_markets"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    asset: Mapped[str] = mapped_column(String(8), index=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    open_ts: Mapped[int] = mapped_column(BigInteger, index=True)
    close_ts: Mapped[int] = mapped_column(BigInteger)
    winner: Mapped[str | None] = mapped_column(String(4), nullable=True)
    open_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    close_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    up_token_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    price_points: Mapped[int] = mapped_column(Integer, default=0)
    history_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # [[t, p_up], ...]
    ingested_ts: Mapped[int] = mapped_column(BigInteger, default=0)
    source: Mapped[str] = mapped_column(String(48), default="clob_prices_history")
