"""Application configuration, loaded from environment variables / .env.

Secrets are never hard-coded. The paper-trading research system needs NO
credentials: every data source it uses is a free public endpoint.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[2]  # project root (Polymarket5min)
BACKEND_DIR = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(ROOT_DIR / ".env"), str(BACKEND_DIR / ".env")),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- core -------------------------------------------------------------
    database_url: str = f"sqlite:///{(BACKEND_DIR / 'data' / 'reversal_terminal.db').as_posix()}"
    data_dir: str = str(BACKEND_DIR / "data")
    log_level: str = "INFO"
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    # --- providers --------------------------------------------------------
    market_data_provider: str = "polymarket"
    gamma_base_url: str = "https://gamma-api.polymarket.com"
    clob_base_url: str = "https://clob.polymarket.com"
    clob_market_ws_url: str = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
    rtds_ws_url: str = "wss://ws-live-data.polymarket.com"
    crypto_price_url: str = "https://polymarket.com/api/crypto/crypto-price"
    geoblock_url: str = "https://polymarket.com/api/geoblock"
    binance_ws_url: str = "wss://stream.binance.com:9443/stream"
    binance_rest_url: str = "https://api.binance.com"
    coinbase_rest_url: str = "https://api.exchange.coinbase.com"

    # Which spot reference to use per asset: "chainlink" (Polymarket RTDS, same
    # oracle family used for settlement), "binance" or "coinbase".
    btc_price_provider: str = "chainlink"
    eth_price_provider: str = "chainlink"
    sol_price_provider: str = "chainlink"
    xrp_price_provider: str = "chainlink"
    doge_price_provider: str = "chainlink"
    hype_price_provider: str = "chainlink"
    bnb_price_provider: str = "chainlink"

    optional_data_api_key: str = ""
    optional_data_api_secret: str = ""

    # --- collector --------------------------------------------------------
    enabled_assets: str = "BTC,ETH,SOL,XRP,DOGE,HYPE,BNB"
    observation_interval_ms: int = 1000
    resolution_poll_seconds: int = 15
    discovery_poll_seconds: int = 20

    # --- paper execution realism -----------------------------------------
    # Network + matching latency applied before a simulated order touches
    # the book. Polymarket documents a 150 ms taker delay on crypto markets.
    paper_latency_ms: int = 400
    paper_min_order_shares: float = 5.0  # Gamma orderMinSize for these markets
    paper_min_marketable_notional: float = 1.0  # CLOB rejects marketable buys < $1

    # --- eligibility / live trading ------------------------------------------
    # ISO-3166 alpha-2 country you trade from. Polymarket's geoblock policy lists NL
    # as "close-only on the frontend; the API itself is not restricted".
    user_country: str = "NL"
    # Master switch. Live orders are impossible unless this is true AND the live
    # executor holds credentials AND live mode is armed in the UI.
    live_trading_enabled: bool = False
    executor_url: str = "http://127.0.0.1:8787"
    executor_token: str = ""
    live_max_order_usd: float = 5.0          # hard cap per live order, regardless of strategy
    live_max_session_budget_usd: float = 100.0  # hard cap on any live risk budget

    # --- remote access ---------------------------------------------------------
    # Password for the website / iPhone app. Empty = no login (local only).
    app_password: str = ""
    session_secret: str = ""  # random string; derived from app_password if empty
    serve_frontend: bool = True  # serve the exported UI from this server (single origin)

    # --- backups ----------------------------------------------------------
    backup_interval_hours: int = 6
    backup_keep: int = 8

    @property
    def assets(self) -> list[str]:
        return [a.strip().upper() for a in self.enabled_assets.split(",") if a.strip()]

    def price_provider_for(self, asset: str) -> str:
        return getattr(self, f"{asset.lower()}_price_provider", "chainlink") or "chainlink"


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    Path(s.data_dir).mkdir(parents=True, exist_ok=True)
    (Path(s.data_dir) / "reports").mkdir(exist_ok=True)
    (Path(s.data_dir) / "backups").mkdir(exist_ok=True)
    (Path(s.data_dir) / "exports").mkdir(exist_ok=True)
    return s
