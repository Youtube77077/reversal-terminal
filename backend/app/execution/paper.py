"""Paper execution adapter: real-time order books, simulated fills, virtual funds."""
from __future__ import annotations

import asyncio
from typing import Callable

from ..config import get_settings
from ..db import now_ms
from ..providers.polymarket.fees import FeeSchedule
from ..services.orderbook import TokenBook
from .base import ExecutionAdapter, ExecutionReport, OrderIntent
from .simulator import simulate_marketable_buy, validate_order


class PaperExecutionAdapter(ExecutionAdapter):
    mode = "paper"

    def __init__(self, book_lookup: Callable[[str], TokenBook | None]) -> None:
        self.book_lookup = book_lookup
        self.settings = get_settings()

    def available(self) -> tuple[bool, str]:
        return True, "Paper trading: virtual funds, real market data."

    async def submit(self, intent: OrderIntent, fee: FeeSchedule | None = None, min_shares: float | None = None,
                     tick_size: float = 0.01) -> ExecutionReport:
        fee = fee or FeeSchedule()
        min_sh = min_shares if min_shares is not None else self.settings.paper_min_order_shares
        if intent.order_type == "passive_limit":
            err = validate_order(intent.limit_price, intent.shares, min_sh, 0.0, tick_size, marketable=False)
            if err:
                return ExecutionReport("failed", [], intent.shares, reason=err, executed_ts=now_ms())
            book = self.book_lookup(intent.token_id)
            if book is not None and book.best_ask is not None and book.best_ask <= intent.limit_price:
                # a "passive" price that already crosses the book would execute as a taker
                return await self._marketable(intent, fee, min_sh, tick_size)
            return ExecutionReport("pending", [], intent.shares, reason="resting on book", executed_ts=now_ms(),
                                   best_ask_at_execution=book.best_ask if book else None)
        return await self._marketable(intent, fee, min_sh, tick_size)

    async def _marketable(self, intent: OrderIntent, fee: FeeSchedule, min_sh: float, tick: float) -> ExecutionReport:
        # simulate network + matching-engine latency, then read the book AS IT IS THEN
        await asyncio.sleep(self.settings.paper_latency_ms / 1000.0)
        book = self.book_lookup(intent.token_id)
        if book is None or not book.has_snapshot:
            return ExecutionReport("failed", [], intent.shares, reason="order book not available", executed_ts=now_ms())
        rep = simulate_marketable_buy(book.sorted_asks(), intent.limit_price, intent.shares, fee, intent.tif,
                                      min_sh, self.settings.paper_min_marketable_notional, book.tick_size or tick)
        rep.executed_ts = now_ms()
        return rep

    async def cancel(self, order_ref: str) -> bool:
        return True
