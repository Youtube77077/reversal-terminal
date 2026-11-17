"""Polymarket Real-Time Data Socket — Chainlink crypto prices (public).

The same subscription used by the reference bot's ticker
(``topic: crypto_prices_chainlink``), verified against the RTDS docs. A single
connection carries all seven symbols. Prices flow into ``PriceStore``.
"""
from __future__ import annotations

import asyncio
import json
import logging
import random

import websockets

from ...constants import ASSETS
from ...db import now_ms
from ...services.connections import registry
from ...services.price_store import PriceStore

log = logging.getLogger("reversal.rtds")


class ChainlinkFeed:
    def __init__(self, url: str, store: PriceStore, assets: list[str]) -> None:
        self.url = url
        self.store = store
        self.assets = assets
        self._sym_to_asset = {ASSETS[a]["chainlink"]: a for a in assets}
        self._task: asyncio.Task | None = None
        self.connected = False
        self.attempt = 0
        self.last_message_ts: int | None = None

    def start(self) -> None:
        if not self._task:
            self._task = asyncio.create_task(self._run(), name="rtds-chainlink")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()

    async def _run(self) -> None:
        while True:
            try:
                async with websockets.connect(self.url, ping_interval=None, open_timeout=15) as ws:
                    self.connected = True
                    self.attempt = 0
                    subs = [{"topic": "crypto_prices_chainlink", "type": "*", "filters": ""}]
                    await ws.send(json.dumps({"action": "subscribe", "subscriptions": subs}))
                    hb = asyncio.create_task(self._heartbeat(ws))
                    try:
                        async for raw in ws:
                            self._handle(raw)
                    finally:
                        hb.cancel()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                registry.fail("rtds", repr(e))
                log.warning("rtds error: %r", e)
            self.connected = False
            self.attempt += 1
            registry.reconnect("rtds")
            await asyncio.sleep(min(30.0, 0.5 * 2 ** min(self.attempt, 6)) + random.random() * 0.5)

    async def _heartbeat(self, ws) -> None:
        while True:
            await asyncio.sleep(5)
            try:
                await ws.send("PING")
            except Exception:
                return
            if self.last_message_ts and now_ms() - self.last_message_ts > 30_000:
                log.warning("rtds silent 30s — reconnecting")
                await ws.close()
                return

    def _handle(self, raw) -> None:
        if not raw or raw in ("PONG", b"PONG", "pong"):
            return
        try:
            msg = json.loads(raw)
        except (TypeError, ValueError):
            return
        payload = msg.get("payload") or {}
        sym = str(payload.get("symbol", "")).lower()
        asset = self._sym_to_asset.get(sym)
        self.last_message_ts = now_ms()
        if asset is None:
            # initial dumps may carry {"symbol":..., "data":[{timestamp,value},...]}
            return
        if "data" in payload and isinstance(payload["data"], list):
            for pt in payload["data"][-5:]:
                v, t = pt.get("value"), pt.get("timestamp")
                if v:
                    self.store.add(asset, "chainlink", float(v), int(t) if t else None)
            registry.ok("rtds")
            return
        v = payload.get("value")
        if v is None:
            return
        ex_ts = payload.get("timestamp") or msg.get("timestamp")
        self.store.add(asset, "chainlink", float(v), int(ex_ts) if ex_ts else None)
        registry.ok("rtds")
