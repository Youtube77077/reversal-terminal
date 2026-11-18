"""Extra free, keyless real-time exchange feeds (Coinbase, OKX, Hyperliquid).

These update every few milliseconds. Chainlink (which settles the markets) aggregates
exchange prices and publishes a little later, so a blend of these feeds shows where
Chainlink is heading a moment before it gets there. They are inputs only — never the
settlement reference.
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
from datetime import datetime

import websockets

from ...services.connections import registry
from ...services.price_store import PriceStore

log = logging.getLogger("reversal.exchanges")

COINBASE = {"BTC": "BTC-USD", "ETH": "ETH-USD", "SOL": "SOL-USD", "XRP": "XRP-USD", "DOGE": "DOGE-USD"}
OKX = {"BTC": "BTC-USDT", "ETH": "ETH-USDT", "SOL": "SOL-USDT", "XRP": "XRP-USDT", "DOGE": "DOGE-USDT",
       "BNB": "BNB-USDT", "HYPE": "HYPE-USDT"}
HYPERLIQUID = {"BTC": "BTC", "ETH": "ETH", "SOL": "SOL", "XRP": "XRP", "DOGE": "DOGE", "BNB": "BNB", "HYPE": "HYPE"}


class _Feed:
    name = "feed"
    url = ""

    def __init__(self, store: PriceStore, assets: list[str]) -> None:
        self.store = store
        self.assets = assets
        self._task: asyncio.Task | None = None
        self.connected = False
        self.attempt = 0
        self.last_message_ts = 0

    def start(self) -> None:
        if not self._task:
            self._task = asyncio.create_task(self._run(), name=f"{self.name}-spot")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()

    async def subscribe(self, ws) -> None:  # pragma: no cover - overridden
        raise NotImplementedError

    def handle(self, msg) -> None:  # pragma: no cover - overridden
        raise NotImplementedError

    async def _pinger(self, ws) -> None:
        return None

    async def _run(self) -> None:
        while True:
            try:
                async with websockets.connect(self.url, open_timeout=15, ping_interval=20, max_size=2**22) as ws:
                    await self.subscribe(ws)
                    self.connected = True
                    self.attempt = 0
                    pinger = asyncio.create_task(self._pinger(ws))
                    try:
                        async for raw in ws:
                            if raw == "pong":
                                continue
                            try:
                                msg = json.loads(raw)
                            except ValueError:
                                continue
                            try:
                                self.handle(msg)
                            except Exception:
                                continue
                    finally:
                        pinger.cancel()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                registry.fail(self.name, repr(e))
                log.warning("%s ws error: %r", self.name, e)
            self.connected = False
            self.attempt += 1
            registry.reconnect(self.name)
            await asyncio.sleep(min(60.0, 1.0 * 2 ** min(self.attempt, 6)) + random.random())

    def _add(self, asset: str, price, ts_ms: int | None) -> None:
        try:
            p = float(price)
        except (TypeError, ValueError):
            return
        if p > 0:
            self.store.add(asset, self.name, p, ts_ms)
            self.last_message_ts = ts_ms or 0
            registry.ok(self.name)


class CoinbaseFeed(_Feed):
    name = "coinbase"
    url = "wss://ws-feed.exchange.coinbase.com"

    async def subscribe(self, ws) -> None:
        self._map = {v: k for k, v in COINBASE.items() if k in self.assets}
        await ws.send(json.dumps({"type": "subscribe", "product_ids": list(self._map), "channels": ["ticker"]}))

    def handle(self, msg) -> None:
        if msg.get("type") != "ticker":
            return
        a = self._map.get(msg.get("product_id"))
        if not a:
            return
        ts = None
        if msg.get("time"):
            try:
                ts = int(datetime.fromisoformat(msg["time"].replace("Z", "+00:00")).timestamp() * 1000)
            except ValueError:
                ts = None
        self._add(a, msg.get("price"), ts)


class OkxFeed(_Feed):
    name = "okx"
    url = "wss://ws.okx.com:8443/ws/v5/public"

    async def subscribe(self, ws) -> None:
        self._map = {v: k for k, v in OKX.items() if k in self.assets}
        await ws.send(json.dumps({"op": "subscribe", "args": [{"channel": "tickers", "instId": i} for i in self._map]}))

    async def _pinger(self, ws) -> None:
        while True:
            await asyncio.sleep(20)
            await ws.send("ping")

    def handle(self, msg) -> None:
        arg = msg.get("arg") or {}
        a = self._map.get(arg.get("instId"))
        if not a:
            return
        for d in msg.get("data") or []:
            self._add(a, d.get("last"), int(d["ts"]) if d.get("ts") else None)


class HyperliquidFeed(_Feed):
    name = "hyperliquid"
    url = "wss://api.hyperliquid.xyz/ws"

    async def subscribe(self, ws) -> None:
        self._map = {v: k for k, v in HYPERLIQUID.items() if k in self.assets}
        await ws.send(json.dumps({"method": "subscribe", "subscription": {"type": "allMids"}}))

    async def _pinger(self, ws) -> None:
        while True:
            await asyncio.sleep(30)
            await ws.send(json.dumps({"method": "ping"}))

    def handle(self, msg) -> None:
        if msg.get("channel") != "allMids":
            return
        mids = (msg.get("data") or {}).get("mids") or {}
        for coin, asset in self._map.items():
            if coin in mids:
                self._add(asset, mids[coin], None)


# Hyperliquid allMids updates only every ~3s with no measurable lead (tested 2026-11-18) — recorded, not blended
FAST_SOURCES = ("binance", "coinbase", "okx")
