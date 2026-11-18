"""Polymarket LIVE broker adapter (real money).

Talks to the local `executor` service (Node.js, `executor/index.mjs`), which uses the exact
official SDK path the user's working reference bot used (`@polymarket/client`
createSecureClient → deposit wallet → placeLimitOrder / fetchOrder / cancelOrder,
gasless redemption). Credentials live ONLY in the executor's environment; this Python
process and the browser never see the private key.

Order semantics: a marketable LIMIT buy at the strategy's limit price (price-protected),
then any unfilled remainder is cancelled — i.e. fill-and-kill with a hard price cap.
"""
from __future__ import annotations

import httpx

from ..config import get_settings
from ..db import now_ms
from ..providers.polymarket.fees import FeeSchedule, taker_fee
from .base import ExecutionAdapter, ExecutionReport, FillReport, LiveTradingUnavailable, OrderIntent


class PolymarketLiveAdapter(ExecutionAdapter):
    mode = "live"

    def __init__(self) -> None:
        self.settings = get_settings()

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.settings.executor_token}"}

    def available(self) -> tuple[bool, str]:
        from .switch import live_enabled
        if not live_enabled():
            return False, "live trading switch is off"
        return True, "live adapter configured (executor health checked per order)"

    async def balance(self, wallet: str = "main") -> float | None:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(f"{self.settings.executor_url}/balance", params={"wallet": wallet}, headers=self._headers())
            if r.status_code != 200:
                return None
            return float(r.json().get("usdc", 0.0))

    async def submit(self, intent: OrderIntent, fee: FeeSchedule | None = None, min_shares: float | None = None,
                     tick_size: float = 0.01) -> ExecutionReport:
        ok, why = self.available()
        if not ok:
            raise LiveTradingUnavailable(why)
        notional = intent.limit_price * intent.shares
        if notional > self.settings.live_max_order_usd + 1e-9:
            return ExecutionReport("failed", [], intent.shares, executed_ts=now_ms(),
                                   reason=f"order ${notional:.2f} exceeds LIVE_MAX_ORDER_USD ${self.settings.live_max_order_usd:.2f}")
        body = {"wallet": intent.meta.get("wallet", "main"), "tokenId": intent.token_id, "side": "BUY", "price": intent.limit_price, "size": intent.shares,
                "mode": "limit_fak", "waitMs": 2500}
        try:
            async with httpx.AsyncClient(timeout=30) as c:
                r = await c.post(f"{self.settings.executor_url}/order", json=body, headers=self._headers())
            d = r.json()
        except Exception as e:
            return ExecutionReport("failed", [], intent.shares, reason=f"executor error: {e!r}", executed_ts=now_ms())
        if not d.get("ok"):
            return ExecutionReport("failed", [], intent.shares, reason=str(d.get("error") or "rejected"),
                                   executed_ts=now_ms())
        matched = float(d.get("sizeMatched") or 0.0)
        px = float(d.get("avgPrice") or intent.limit_price)
        fee = fee or FeeSchedule()
        fills = [FillReport(price=px, shares=matched, fee=taker_fee(matched, px, fee), role="taker")] if matched > 0 else []
        status = "filled" if matched >= intent.shares - 1e-6 else ("partially_filled" if matched > 0 else "unfilled")
        rep = ExecutionReport(status, fills, intent.shares, executed_ts=now_ms(),
                              reason=None if status == "filled" else d.get("note") or "remainder cancelled")
        rep.reason = (rep.reason or "") + f" [order {d.get('orderId')}]"
        return rep

    async def cancel(self, order_ref: str) -> bool:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(f"{self.settings.executor_url}/cancel", json={"orderId": order_ref}, headers=self._headers())
            return r.status_code == 200 and r.json().get("ok", False)

    async def redeem(self, condition_id: str, wallet: str = "main") -> dict:
        async with httpx.AsyncClient(timeout=120) as c:
            r = await c.post(f"{self.settings.executor_url}/redeem", json={"conditionId": condition_id, "wallet": wallet},
                             headers=self._headers())
            return r.json()
