"""Rolling in-memory store of underlying prices with momentum/volatility features."""
from __future__ import annotations

import bisect
import math
import threading
from collections import deque
from dataclasses import dataclass

from ..db import now_ms

KEEP_MS = 6 * 60 * 1000


@dataclass
class Tick:
    server_ts: int
    exchange_ts: int | None
    price: float


BUCKET_MS = 100  # keep at most one tick per 100 ms (last value wins)


class PriceSeries:
    """Append-only parallel arrays (ts, price) with amortised trimming."""

    def __init__(self) -> None:
        self.ts: list[int] = []
        self.px: list[float] = []
        self.ex: list[int | None] = []

    def add(self, t: Tick) -> None:
        if self.ts and t.server_ts < self.ts[-1]:
            return  # out-of-order tick; ignore to keep arrays sorted
        if self.ts and t.server_ts // BUCKET_MS == self.ts[-1] // BUCKET_MS:
            self.ts[-1], self.px[-1], self.ex[-1] = t.server_ts, t.price, t.exchange_ts
        else:
            self.ts.append(t.server_ts)
            self.px.append(t.price)
            self.ex.append(t.exchange_ts)
        cutoff = t.server_ts - KEEP_MS
        if self.ts[0] < cutoff and len(self.ts) > 64:
            i = bisect.bisect_left(self.ts, cutoff)
            if i > len(self.ts) // 4:
                del self.ts[:i], self.px[:i], self.ex[:i]

    @property
    def ticks(self) -> list[Tick]:
        return [Tick(a, c, b) for a, b, c in zip(self.ts, self.px, self.ex)]

    @property
    def last(self) -> Tick | None:
        return Tick(self.ts[-1], self.ex[-1], self.px[-1]) if self.ts else None

    def price_at(self, ts: int) -> float | None:
        """Last known price at or before ``ts`` (no look-ahead)."""
        i = bisect.bisect_right(self.ts, ts) - 1
        return self.px[i] if i >= 0 else None

    def twap(self, start: int, end: int) -> float | None:
        """Time-weighted average over [start, end] using last-value-carried-forward."""
        if end <= start or not self.ts:
            return None
        p0 = self.price_at(start)
        lo = bisect.bisect_right(self.ts, start)
        hi = bisect.bisect_right(self.ts, end)
        seg = [(start, p0)] if p0 is not None else []
        seg += list(zip(self.ts[lo:hi], self.px[lo:hi]))
        if not seg:
            return None
        total = 0.0
        dur = 0
        for i, (ts, p) in enumerate(seg):
            nxt = seg[i + 1][0] if i + 1 < len(seg) else end
            d = max(0, nxt - ts)
            total += p * d
            dur += d
        return total / dur if dur else seg[-1][1]


class PriceStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.series: dict[tuple[str, str], PriceSeries] = {}

    def add(self, asset: str, source: str, price: float, exchange_ts: int | None, server_ts: int | None = None) -> None:
        if price is None or price <= 0 or math.isnan(price):
            return
        with self._lock:
            self.series.setdefault((asset, source), PriceSeries()).add(
                Tick(server_ts or now_ms(), exchange_ts, float(price)))

    def get(self, asset: str, source: str) -> PriceSeries | None:
        return self.series.get((asset, source))

    def features(self, asset: str, source: str, at: int | None = None, open_price: float | None = None) -> dict:
        """Momentum, volatility and threshold-distance features using data <= ``at``."""
        at = at or now_ms()
        s = self.get(asset, source)
        out: dict = {"spot": None, "spot_exchange_ts": None, "spot_age_ms": None, "spot_source": source}
        if s is None or s.last is None:
            return out
        with self._lock:
            spot = s.price_at(at)
            if spot is None:
                return out
            last = s.last
            out["spot"] = spot
            out["spot_exchange_ts"] = last.exchange_ts
            out["spot_age_ms"] = at - last.server_ts
            for n in (1, 3, 5, 10, 30, 60):
                prev = s.price_at(at - n * 1000)
                out[f"mom_{n}s"] = (spot - prev) if prev is not None else None
            # 1-second log returns over 30s for realised volatility
            rets = []
            prev = s.price_at(at - 30_000)
            for k in range(29, -1, -1):
                cur = s.price_at(at - k * 1000)
                if prev and cur:
                    rets.append(math.log(cur / prev))
                prev = cur
            if len(rets) >= 5:
                m = sum(rets) / len(rets)
                out["vol_30s"] = math.sqrt(sum((r - m) ** 2 for r in rets) / (len(rets) - 1)) * 1e4  # bps/sec
            else:
                out["vol_30s"] = None
            m5_now = out.get("mom_5s")
            p5 = s.price_at(at - 5000)
            p10 = s.price_at(at - 10000)
            out["accel"] = (m5_now - (p5 - p10)) if (m5_now is not None and p5 and p10) else None
            out["twap60_est"] = s.twap(at - 60_000, at)
        if open_price:
            ref = out["spot"]
            out["dist_abs"] = ref - open_price
            out["dist_bps"] = (ref - open_price) / open_price * 1e4
        else:
            out["dist_abs"] = out["dist_bps"] = None
        return out
