"""Source registry: which provider supplies which field, and live connection health."""
from __future__ import annotations

import threading

from ..db import now_ms, session_scope
from ..models import ApiConnection

SOURCES: list[dict] = [
    {
        "key": "gamma",
        "provider": "Polymarket Gamma API",
        "purpose": "Market discovery: event/market ids, condition id, UP/DOWN token ids, open/close times, "
                   "resolution source, fee schedule, tick size, official resolution (outcomePrices).",
        "base_url": "https://gamma-api.polymarket.com",
        "auth": "none (public)",
        "api_key_required": False,
        "websocket": False,
        "rate_limit": "/events 500 req/10s, /markets 300 req/10s, general 4000 req/10s (Cloudflare, throttled)",
        "fields_supplied": "market ids, token ids, open/close timestamps, resolutionSource, feeSchedule, "
                           "orderMinSize, orderPriceMinTickSize, outcomePrices (official winner)",
    },
    {
        "key": "clob_ws",
        "provider": "Polymarket CLOB WebSocket (market channel)",
        "purpose": "Real-time L2 order books, price changes, last trade prices, tick size changes.",
        "base_url": "wss://ws-subscriptions-clob.polymarket.com/ws/market",
        "auth": "none (public)",
        "api_key_required": False,
        "websocket": True,
        "rate_limit": "No documented subscription cap (100-token limit removed 2025-05-28); PING every 10s",
        "fields_supplied": "best bid/ask, depth, sizes, last trade price, tick size, exchange timestamps",
    },
    {
        "key": "clob_rest",
        "provider": "Polymarket CLOB REST",
        "purpose": "Order book snapshots (fallback/resync), fee-rate check, price history for historical ingest.",
        "base_url": "https://clob.polymarket.com",
        "auth": "none for market data (L1/L2 auth only for trading)",
        "api_key_required": False,
        "websocket": False,
        "rate_limit": "/book 1500 req/10s, /books 500 req/10s, /prices-history (general CLOB limits)",
        "fields_supplied": "book snapshots, base_fee, prices-history (1-minute fidelity)",
    },
    {
        "key": "rtds",
        "provider": "Polymarket Real-Time Data Socket (Chainlink prices)",
        "purpose": "Underlying Chainlink reference prices — same oracle family used to settle these markets.",
        "base_url": "wss://ws-live-data.polymarket.com",
        "auth": "none (public)",
        "api_key_required": False,
        "websocket": True,
        "rate_limit": "Not documented; one connection, all 7 symbols",
        "fields_supplied": "spot price (Chainlink), oracle timestamp",
    },
    {
        "key": "crypto_price",
        "provider": "Polymarket crypto-price endpoint",
        "purpose": "Opening reference price and final settlement reference price per 5-minute window.",
        "base_url": "https://polymarket.com/api/crypto/crypto-price",
        "auth": "none (public, undocumented web endpoint)",
        "api_key_required": False,
        "websocket": False,
        "rate_limit": "Not documented — polled conservatively",
        "fields_supplied": "openPrice, closePrice, completed flag",
    },
    {
        "key": "binance",
        "provider": "Binance public market data",
        "purpose": "Secondary spot reference / cross-check of Chainlink feed (not the settlement source).",
        "base_url": "wss://stream.binance.com:9443",
        "auth": "none (public)",
        "api_key_required": False,
        "websocket": True,
        "rate_limit": "5 incoming msgs/s per connection, 1024 streams per connection",
        "fields_supplied": "spot last price, exchange event time",
    },
    {
        "key": "geoblock",
        "provider": "Polymarket geoblock check",
        "purpose": "Eligibility: determines whether the current location may place orders.",
        "base_url": "https://polymarket.com/api/geoblock",
        "auth": "none (public)",
        "api_key_required": False,
        "websocket": False,
        "rate_limit": "Called on startup and on demand",
        "fields_supplied": "blocked flag, country, region",
    },
    {
        "key": "clob_trading",
        "provider": "Polymarket CLOB trading (L2 authenticated)",
        "purpose": "Live order placement — DISABLED (Netherlands is a restricted jurisdiction).",
        "base_url": "https://clob.polymarket.com",
        "auth": "EIP-712 wallet signature (L1) + API key/secret/passphrase HMAC (L2)",
        "api_key_required": True,
        "websocket": True,
        "rate_limit": "Per-signer token buckets (trading-rate-limits docs)",
        "fields_supplied": "n/a — not used",
    },
]


class ConnectionRegistry:
    """Thread-safe in-memory health counters, flushed to the DB periodically."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.state: dict[str, dict] = {s["key"]: {"status": "unknown", "last_success_ts": None, "last_error_ts": None,
                                                    "last_error": None, "failures": 0, "reconnects": 0,
                                                    "messages": 0} for s in SOURCES}
        self.state["clob_trading"]["status"] = "disabled"

    def ok(self, key: str, n: int = 1) -> None:
        with self._lock:
            st = self.state.setdefault(key, {"failures": 0, "reconnects": 0, "messages": 0})
            st["status"] = "ok"
            st["last_success_ts"] = now_ms()
            st["messages"] = st.get("messages", 0) + n

    def fail(self, key: str, err: str) -> None:
        with self._lock:
            st = self.state.setdefault(key, {"failures": 0, "reconnects": 0, "messages": 0})
            st["failures"] = st.get("failures", 0) + 1
            st["last_error"] = str(err)[:500]
            st["last_error_ts"] = now_ms()
            last_ok = st.get("last_success_ts") or 0
            st["status"] = "degraded" if now_ms() - last_ok < 60_000 else "down"

    def reconnect(self, key: str) -> None:
        with self._lock:
            st = self.state.setdefault(key, {"failures": 0, "reconnects": 0, "messages": 0})
            st["reconnects"] = st.get("reconnects", 0) + 1

    def snapshot(self) -> dict[str, dict]:
        with self._lock:
            return {k: dict(v) for k, v in self.state.items()}

    def flush(self) -> None:
        snap = self.snapshot()
        with session_scope() as s:
            for k, st in snap.items():
                row = s.get(ApiConnection, k)
                if not row:
                    continue
                row.status = st.get("status", "unknown")
                row.last_success_ts = st.get("last_success_ts")
                row.last_error_ts = st.get("last_error_ts")
                row.last_error = st.get("last_error")
                row.failures = st.get("failures", 0)
                row.reconnects = st.get("reconnects", 0)
                row.messages = st.get("messages", 0)


registry = ConnectionRegistry()


def seed_connections() -> None:
    with session_scope() as s:
        for src in SOURCES:
            row = s.get(ApiConnection, src["key"])
            if row is None:
                row = ApiConnection(key=src["key"])
                s.add(row)
            for f in ("provider", "purpose", "base_url", "auth", "api_key_required", "websocket", "rate_limit",
                      "fields_supplied"):
                setattr(row, f, src[f])
            if src["key"] == "clob_trading":
                row.status = "disabled"
