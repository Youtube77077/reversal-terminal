"""Binance public combined trade stream — secondary spot reference (not the settlement source)."""
from __future__ import annotations

import asyncio
import json
import logging
import random

import websockets

from ...constants import ASSETS
from ...services.connections import registry
from ...services.price_store import PriceStore

log = logging.getLogger("reversal.binance")


class BinanceFeed:
    def __init__(self, base_url: str, store: PriceStore, assets: list[str]) -> None:
        streams = "/".join(f"{ASSETS[a]['binance']}@aggTrade" for a in assets)
        self.url = f"{base_url}?streams={streams}"
        self.store = store
        self._map = {ASSETS[a]["binance"].upper(): a for a in assets}
        self._task: asyncio.Task | None = None
        self.connected = False
        self.attempt = 0

    def start(self) -> None:
        if not self._task:
            self._task = asyncio.create_task(self._run(), name="binance-spot")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()

    async def _run(self) -> None:
        while True:
            try:
                async with websockets.connect(self.url, open_timeout=15, ping_interval=20) as ws:
                    self.connected = True
                    self.attempt = 0
                    async for raw in ws:
                        try:
                            msg = json.loads(raw).get("data") or {}
                        except ValueError:
                            continue
                        a = self._map.get(str(msg.get("s", "")).upper())
                        if a and msg.get("p"):
                            self.store.add(a, "binance", float(msg["p"]), int(msg.get("T") or msg.get("E") or 0) or None)
                            registry.ok("binance")
            except asyncio.CancelledError:
                raise
            except Exception as e:
                registry.fail("binance", repr(e))
                log.warning("binance ws error: %r", e)
            self.connected = False
            self.attempt += 1
            registry.reconnect("binance")
            await asyncio.sleep(min(60.0, 1.0 * 2 ** min(self.attempt, 6)) + random.random())
