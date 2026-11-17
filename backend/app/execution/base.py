"""Unified execution interface.

The trading engine and strategies talk to an ``ExecutionAdapter`` and never
know whether orders are simulated (``PaperExecutionAdapter``) or routed to an
authorised live provider. Switching adapters requires an explicit,
eligibility-checked mode change — never a silent fallback.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class OrderIntent:
    account_id: int
    market_id: int
    token_id: str
    side: str                 # UP | DOWN
    order_type: str           # marketable_limit | passive_limit
    tif: str                  # FAK | FOK | GTD
    limit_price: float
    shares: float
    expire_ts: int | None = None
    decision_ts: int = 0
    meta: dict = field(default_factory=dict)


@dataclass
class FillReport:
    price: float
    shares: float
    fee: float
    role: str  # taker | maker

    @property
    def notional(self) -> float:
        return self.price * self.shares


@dataclass
class ExecutionReport:
    status: str               # filled | partially_filled | unfilled | failed | pending
    fills: list[FillReport]
    requested_shares: float
    reason: str | None = None
    executed_ts: int | None = None
    best_ask_at_execution: float | None = None

    @property
    def filled_shares(self) -> float:
        return sum(f.shares for f in self.fills)

    @property
    def notional(self) -> float:
        return sum(f.notional for f in self.fills)

    @property
    def fees(self) -> float:
        return round(sum(f.fee for f in self.fills), 5)

    @property
    def vwap(self) -> float | None:
        s = self.filled_shares
        return self.notional / s if s > 0 else None


class ExecutionAdapter(ABC):
    mode: str = "abstract"

    @abstractmethod
    def available(self) -> tuple[bool, str]:
        """(is_available, reason)."""

    @abstractmethod
    async def submit(self, intent: OrderIntent) -> ExecutionReport: ...

    @abstractmethod
    async def cancel(self, order_ref: str) -> bool: ...


class LiveTradingUnavailable(RuntimeError):
    pass
