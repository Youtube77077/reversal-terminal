"""In-memory L2 order book for one outcome token."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class BookLevelFill:
    price: float
    shares: float

    @property
    def notional(self) -> float:
        return self.price * self.shares


@dataclass
class TokenBook:
    token_id: str
    bids: dict[float, float] = field(default_factory=dict)
    asks: dict[float, float] = field(default_factory=dict)
    exchange_ts: int | None = None
    server_ts: int | None = None
    hash: str | None = None
    tick_size: float = 0.01
    last_trade_price: float | None = None
    last_trade_ts: int | None = None
    traded_shares: float = 0.0  # cumulative, from last_trade_price events
    has_snapshot: bool = False

    # ---------------------------------------------------------------- mutate
    def apply_snapshot(self, bids: list[dict], asks: list[dict], exchange_ts: int | None, server_ts: int,
                       hash_: str | None = None, tick_size: str | float | None = None) -> None:
        self.bids = {float(l["price"]): float(l["size"]) for l in bids if float(l["size"]) > 0}
        self.asks = {float(l["price"]): float(l["size"]) for l in asks if float(l["size"]) > 0}
        self.exchange_ts = exchange_ts
        self.server_ts = server_ts
        self.hash = hash_
        if tick_size:
            self.tick_size = float(tick_size)
        self.has_snapshot = True

    def apply_change(self, side: str, price: float, size: float, exchange_ts: int | None, server_ts: int) -> None:
        book = self.bids if side.upper() in ("BUY", "BID") else self.asks
        if size <= 0:
            book.pop(price, None)
        else:
            book[price] = size
        self.exchange_ts = exchange_ts or self.exchange_ts
        self.server_ts = server_ts

    # ---------------------------------------------------------------- read
    @property
    def best_bid(self) -> float | None:
        return max(self.bids) if self.bids else None

    @property
    def best_ask(self) -> float | None:
        return min(self.asks) if self.asks else None

    @property
    def best_bid_size(self) -> float | None:
        b = self.best_bid
        return None if b is None else self.bids[b]

    @property
    def best_ask_size(self) -> float | None:
        a = self.best_ask
        return None if a is None else self.asks[a]

    @property
    def mid(self) -> float | None:
        b, a = self.best_bid, self.best_ask
        if b is None or a is None:
            return None
        return (a + b) / 2.0

    @property
    def spread(self) -> float | None:
        b, a = self.best_bid, self.best_ask
        if b is None or a is None:
            return None
        return a - b

    def sorted_asks(self, depth: int | None = None) -> list[tuple[float, float]]:
        out = sorted(self.asks.items(), key=lambda kv: kv[0])
        return out[:depth] if depth else out

    def sorted_bids(self, depth: int | None = None) -> list[tuple[float, float]]:
        out = sorted(self.bids.items(), key=lambda kv: -kv[0])
        return out[:depth] if depth else out

    def ask_liquidity_usd(self, depth: int = 5, max_price: float | None = None) -> float:
        tot = 0.0
        for p, s in self.sorted_asks(depth):
            if max_price is not None and p > max_price:
                break
            tot += p * s
        return tot

    def bid_liquidity_usd(self, depth: int = 5) -> float:
        return sum(p * s for p, s in self.sorted_bids(depth))

    def copy_levels(self) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
        return self.sorted_bids(), self.sorted_asks()


def walk_asks(asks: list[tuple[float, float]], limit_price: float, max_shares: float) -> list[BookLevelFill]:
    """Consume ascending ask levels up to ``limit_price`` until ``max_shares`` are bought."""
    fills: list[BookLevelFill] = []
    remaining = max_shares
    for price, size in sorted(asks, key=lambda kv: kv[0]):
        if remaining <= 1e-12:
            break
        if price > limit_price + 1e-12:
            break
        take = min(size, remaining)
        if take > 0:
            fills.append(BookLevelFill(price=price, shares=take))
            remaining -= take
    return fills


def vwap_for_usd(asks: list[tuple[float, float]], usd: float) -> float | None:
    """Average price paid to spend ``usd`` walking the ask side (None if book too thin)."""
    remaining = usd
    shares = 0.0
    spent = 0.0
    for price, size in sorted(asks, key=lambda kv: kv[0]):
        if remaining <= 1e-12:
            break
        level_cost = price * size
        if level_cost <= remaining:
            shares += size
            spent += level_cost
            remaining -= level_cost
        else:
            s = remaining / price
            shares += s
            spent += remaining
            remaining = 0
    if remaining > 1e-9 or shares <= 0:
        return None
    return spent / shares
