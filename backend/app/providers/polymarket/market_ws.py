"""Polymarket CLOB market-channel websocket (public, no auth).

Docs: https://docs.polymarket.com/api-reference/wss/market
  URL:        wss://ws-subscriptions-clob.polymarket.com/ws/market
  subscribe:  {"assets_ids": [...], "type": "market"}
  dynamic:    {"assets_ids": [...], "operation": "subscribe" | "unsubscribe"}
  heartbeat:  send "PING" every 10 s, server replies "PONG"

Messages handled: ``book`` (full snapshot), ``price_change`` (level deltas),
``last_trade_price``, ``tick_size_change``. The connection reconnects with
exponential backoff and resubscribes to every tracked token; a fresh ``book``
snapshot is delivered on each (re)subscription, so no deltas are applied to a
stale book.
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
from typing import Callable

import websockets

from ...db import now_ms
from ...services.connections import registry
from ...services.orderbook import TokenBook

log = logging.getLogger("reversal.clob_ws")


class MarketChannel:
    def __init__(self, url: str, on_update: Callable[[str], None] | None = None) -> None:
        self.url = url
        self.books: dict[str, TokenBook] = {}
        self._wanted: set[str] = set()
        self._ws = None
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self.on_update = on_update
        self.connected = False
        self.last_message_ts: int | None = None
        self.attempt = 0

    # ---------------------------------------------------------------- control
    def start(self) -> None:
        if not self._task:
            self._task = asyncio.create_task(self._run(), name="clob-market-ws")

    async def stop(self) -> None:
        self._stop.set()
        if self._ws is not None:
            await self._ws.close()
        if self._task:
            self._task.cancel()

    async def track(self, token_ids: list[str]) -> None:
        new = [t for t in token_ids if t and t not in self._wanted]
        if not new:
            return
        for t in new:
            self._wanted.add(t)
            self.books.setdefault(t, TokenBook(token_id=t))
        if self._ws is not None and self.connected:
            try:
                await self._ws.send(json.dumps({"assets_ids": new, "operation": "subscribe"}))
            except Exception as e:  # will resubscribe on reconnect
                log.warning("dynamic subscribe failed: %s", e)

    async def untrack(self, token_ids: list[str]) -> None:
        gone = [t for t in token_ids if t in self._wanted]
        for t in gone:
            self._wanted.discard(t)
            self.books.pop(t, None)
        if gone and self._ws is not None and self.connected:
            try:
                await self._ws.send(json.dumps({"assets_ids": gone, "operation": "unsubscribe"}))
            except Exception:
                pass

    # ---------------------------------------------------------------- loop
    async def _run(self) -> None:
        while not self._stop.is_set():
            if not self._wanted:
                await asyncio.sleep(0.5)
                continue
            try:
                async with websockets.connect(self.url, ping_interval=None, open_timeout=15,
                                              max_size=8 * 1024 * 1024) as ws:
                    self._ws = ws
                    self.connected = True
                    self.attempt = 0
                    # mark books stale until the fresh snapshot arrives
                    for b in self.books.values():
                        b.has_snapshot = False
                    await ws.send(json.dumps({"assets_ids": sorted(self._wanted), "type": "market"}))
                    hb = asyncio.create_task(self._heartbeat(ws))
                    try:
                        async for raw in ws:
                            self._handle(raw)
                    finally:
                        hb.cancel()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                registry.fail("clob_ws", repr(e))
                log.warning("market ws error: %r", e)
            finally:
                self.connected = False
                self._ws = None
            if self._stop.is_set():
                break
            self.attempt += 1
            registry.reconnect("clob_ws")
            delay = min(30.0, 0.5 * 2 ** min(self.attempt, 6)) + random.random() * 0.5
            await asyncio.sleep(delay)

    async def _heartbeat(self, ws) -> None:
        while True:
            await asyncio.sleep(10)
            try:
                await ws.send("PING")
            except Exception:
                return
            if self.last_message_ts and now_ms() - self.last_message_ts > 45_000:
                log.warning("market ws silent for 45s — forcing reconnect")
                await ws.close()
                return

    def _handle(self, raw) -> None:
        if raw in ("PONG", b"PONG"):
            self.last_message_ts = now_ms()
            return
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            return
        self.last_message_ts = now_ms()
        msgs = data if isinstance(data, list) else [data]
        registry.ok("clob_ws", len(msgs))
        touched: set[str] = set()
        for m in msgs:
            et = m.get("event_type")
            srv = now_ms()
            if et == "book":
                tok = m.get("asset_id")
                if tok in self.books:
                    self.books[tok].apply_snapshot(m.get("bids", []), m.get("asks", []),
                                                   _int(m.get("timestamp")), srv, m.get("hash"), m.get("tick_size"))
                    touched.add(tok)
            elif et == "price_change":
                ts = _int(m.get("timestamp"))
                for ch in m.get("price_changes", []):
                    tok = ch.get("asset_id")
                    b = self.books.get(tok)
                    if b is None or not b.has_snapshot:
                        continue
                    b.apply_change(ch.get("side", ""), float(ch["price"]), float(ch["size"]), ts, srv)
                    touched.add(tok)
            elif et == "last_trade_price":
                tok = m.get("asset_id")
                b = self.books.get(tok)
                if b is not None:
                    try:
                        b.last_trade_price = float(m.get("price"))
                        b.last_trade_ts = _int(m.get("timestamp"))
                        b.traded_shares += float(m.get("size") or 0)
                    except (TypeError, ValueError):
                        pass
                    touched.add(tok)
            elif et == "tick_size_change":
                tok = m.get("asset_id")
                b = self.books.get(tok)
                if b is not None and m.get("new_tick_size"):
                    b.tick_size = float(m["new_tick_size"])
        if self.on_update:
            for t in touched:
                self.on_update(t)


def _int(v) -> int | None:
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None
