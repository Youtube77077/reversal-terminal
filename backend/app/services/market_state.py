"""Point-in-time market state handed to the scanner, strategies and paper engine."""
from __future__ import annotations

from dataclasses import dataclass, field

from ..providers.polymarket.fees import FeeSchedule
from .orderbook import TokenBook


@dataclass
class MarketState:
    market_id: int
    asset: str
    slug: str
    condition_id: str | None
    up_token: str
    down_token: str
    open_ts: int
    close_ts: int
    server_ts: int
    secs_remaining: float
    open_price: float | None
    fee: FeeSchedule
    min_order_size: float
    tick_size: float
    up_bid: float | None = None
    up_ask: float | None = None
    down_bid: float | None = None
    down_ask: float | None = None
    up_bid_size: float | None = None
    up_ask_size: float | None = None
    down_bid_size: float | None = None
    down_ask_size: float | None = None
    up_asks: list[tuple[float, float]] = field(default_factory=list)
    down_asks: list[tuple[float, float]] = field(default_factory=list)
    up_bids: list[tuple[float, float]] = field(default_factory=list)
    down_bids: list[tuple[float, float]] = field(default_factory=list)
    book_exchange_ts: int | None = None
    book_ok: bool = False
    features: dict = field(default_factory=dict)
    spot_ok: bool = False
    window: str = "5m"          # 5m | 15m

    # ------------------------------------------------------------ derived
    @property
    def up_mid(self) -> float | None:
        return _mid(self.up_bid, self.up_ask)

    @property
    def down_mid(self) -> float | None:
        return _mid(self.down_bid, self.down_ask)

    @property
    def up_prob(self) -> float | None:
        """Implied UP probability from the effective (synthetic) UP book.

        Buying DOWN at a is economically selling UP at 1-a, so the effective UP bid is
        max(UP bid, 1 - DOWN ask) and the effective UP ask is min(UP ask, 1 - DOWN bid).
        Near expiry books are often one-sided (e.g. UP ask 0.01 only, DOWN bid 0.99 only);
        plain midpoints are undefined there, but the effective book still prices the market.
        """
        return implied_up_prob(self.up_bid, self.up_ask, self.down_bid, self.down_ask)

    @property
    def favourite(self) -> str | None:
        p = self.up_prob
        if p is None:
            return None
        if abs(p - 0.5) < 1e-9:
            return None
        return "UP" if p > 0.5 else "DOWN"

    @property
    def underdog(self) -> str | None:
        f = self.favourite
        return None if f is None else ("DOWN" if f == "UP" else "UP")

    @property
    def fav_prob(self) -> float | None:
        p = self.up_prob
        if p is None:
            return None
        return max(p, 1 - p)

    def ask(self, side: str) -> float | None:
        return self.up_ask if side == "UP" else self.down_ask

    def bid(self, side: str) -> float | None:
        return self.up_bid if side == "UP" else self.down_bid

    def ask_size(self, side: str) -> float | None:
        return self.up_ask_size if side == "UP" else self.down_ask_size

    def asks(self, side: str) -> list[tuple[float, float]]:
        return self.up_asks if side == "UP" else self.down_asks

    def bids(self, side: str) -> list[tuple[float, float]]:
        return self.up_bids if side == "UP" else self.down_bids

    def token(self, side: str) -> str:
        return self.up_token if side == "UP" else self.down_token

    def spread(self, side: str) -> float | None:
        a, b = self.ask(side), self.bid(side)
        return None if a is None or b is None else a - b

    def ask_liquidity_usd(self, side: str, max_price: float | None = None, depth: int = 10) -> float:
        tot = 0.0
        for p, s in self.asks(side)[:depth]:
            if max_price is not None and p > max_price + 1e-12:
                break
            tot += p * s
        return tot

    @property
    def dist_bps(self) -> float | None:
        return self.features.get("dist_bps")

    def momentum_toward(self, side: str, horizon: str = "mom_10s") -> bool | None:
        """True if the underlying is moving in the direction that helps ``side`` win."""
        m = self.features.get(horizon)
        if m is None or m == 0:
            return None
        return (m > 0) if side == "UP" else (m < 0)

    def to_snapshot(self, depth: int = 10) -> dict:
        f = self.features
        return {
            "market_id": self.market_id, "asset": self.asset, "slug": self.slug, "server_ts": self.server_ts,
            "secs_remaining": round(self.secs_remaining, 3), "open_ts": self.open_ts, "close_ts": self.close_ts,
            "up": {"bid": self.up_bid, "ask": self.up_ask, "mid": self.up_mid, "bids": self.up_bids[:depth],
                   "asks": self.up_asks[:depth]},
            "down": {"bid": self.down_bid, "ask": self.down_ask, "mid": self.down_mid,
                     "bids": self.down_bids[:depth], "asks": self.down_asks[:depth]},
            "up_prob": self.up_prob, "favourite": self.favourite, "fav_prob": self.fav_prob,
            "open_price": self.open_price, "spot": f.get("spot"), "spot_source": f.get("spot_source"),
            "dist_bps": f.get("dist_bps"), "dist_abs": f.get("dist_abs"), "twap60_est": f.get("twap60_est"),
            "momentum": {k: f.get(k) for k in ("mom_1s", "mom_3s", "mom_5s", "mom_10s", "mom_30s", "mom_60s")},
            "vol_30s": f.get("vol_30s"), "accel": f.get("accel"),
            "fee": {"rate": self.fee.rate, "exponent": self.fee.exponent, "verified": self.fee.verified},
            "book_exchange_ts": self.book_exchange_ts,
        }


def implied_up_prob(up_bid, up_ask, down_bid, down_ask) -> float | None:
    bids = [x for x in (up_bid, (1 - down_ask) if down_ask is not None else None) if x is not None]
    asks = [x for x in (up_ask, (1 - down_bid) if down_bid is not None else None) if x is not None]
    eb = max(bids) if bids else None
    ea = min(asks) if asks else None
    if eb is not None and ea is not None:
        p = (eb + ea) / 2
    elif eb is not None:
        p = eb
    elif ea is not None:
        p = ea
    else:
        return None
    return max(0.0, min(1.0, p))


def _mid(b: float | None, a: float | None) -> float | None:
    if b is None or a is None:
        return None
    return (a + b) / 2


def build_state(market, up_book: TokenBook | None, down_book: TokenBook | None, features: dict, server_ts: int,
                fee: FeeSchedule) -> MarketState:
    st = MarketState(
        market_id=market.id, asset=market.asset, slug=market.slug, condition_id=market.condition_id,
        up_token=market.up_token_id, down_token=market.down_token_id, open_ts=market.open_ts,
        close_ts=market.close_ts, server_ts=server_ts, secs_remaining=(market.close_ts - server_ts) / 1000.0,
        open_price=market.open_price, fee=fee, min_order_size=market.min_order_size or 5.0,
        tick_size=market.tick_size or 0.01, features=features,
        window=getattr(market, "window", None) or "5m",
    )
    if up_book is not None and up_book.has_snapshot:
        st.up_bid, st.up_ask = up_book.best_bid, up_book.best_ask
        st.up_bid_size, st.up_ask_size = up_book.best_bid_size, up_book.best_ask_size
        st.up_asks, st.up_bids = up_book.sorted_asks(10), up_book.sorted_bids(10)
        st.tick_size = up_book.tick_size or st.tick_size
    if down_book is not None and down_book.has_snapshot:
        st.down_bid, st.down_ask = down_book.best_bid, down_book.best_ask
        st.down_bid_size, st.down_ask_size = down_book.best_bid_size, down_book.best_ask_size
        st.down_asks, st.down_bids = down_book.sorted_asks(10), down_book.sorted_bids(10)
    st.book_ok = bool(up_book and down_book and up_book.has_snapshot and down_book.has_snapshot)
    ex = [b.exchange_ts for b in (up_book, down_book) if b is not None and b.exchange_ts]
    st.book_exchange_ts = max(ex) if ex else None
    st.spot_ok = features.get("spot") is not None and (features.get("spot_age_ms") or 1e9) < 15_000
    return st
