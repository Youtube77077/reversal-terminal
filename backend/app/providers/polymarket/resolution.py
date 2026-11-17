"""Opening/settlement reference prices and official resolution.

Two independent sources are recorded and compared:

1. ``polymarket.com/api/crypto/crypto-price`` — returns ``openPrice`` (as soon
   as the window opens) and ``closePrice`` (a few seconds after it ends) for the
   Chainlink TWAP stream used to settle the market. Verified: a window's
   ``openPrice`` equals the previous window's ``closePrice``.
2. Gamma ``outcomePrices`` once ``closed`` and ``umaResolutionStatus ==
   "resolved"`` — this is the OFFICIAL outcome. Trades are only settled from
   the official outcome; the price API is used for a provisional result and a
   cross-check (``sources_agree``).
"""
from __future__ import annotations

from datetime import datetime, timezone

VARIANT = "fiveminute"


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


async def fetch_reference_prices(client, url: str, asset: str, open_ts: int, close_ts: int) -> dict | None:
    r = await client.get(url, params={"symbol": asset, "variant": VARIANT, "eventStartTime": _iso(open_ts),
                                      "endDate": _iso(close_ts)},
                         headers={"Accept": "application/json"}, timeout=10)
    if r.status_code != 200:
        return None
    d = r.json()
    if not isinstance(d, dict):
        return None
    return {
        "open_price": d.get("openPrice"),
        "close_price": d.get("closePrice"),
        "completed": bool(d.get("completed")),
        "timestamp": d.get("timestamp"),
    }


def winner_from_prices(open_price: float | None, close_price: float | None) -> str | None:
    """UP if close >= open (ties resolve UP per the market rules), else DOWN."""
    if open_price is None or close_price is None:
        return None
    return "UP" if close_price >= open_price else "DOWN"
