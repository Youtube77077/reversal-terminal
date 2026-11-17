"""Market discovery via the public Gamma API.

5-minute crypto Up/Down markets follow a deterministic slug pattern
(verified against live Gamma data on 2026-11-17 and in the reference bot):

    {asset}-updown-5m-{window_start_unix_seconds}

e.g. ``btc-updown-5m-1794933300``. Windows are aligned to 300-second
boundaries. Each event contains exactly one binary market whose
``outcomes`` is ``["Up", "Down"]`` and whose ``clobTokenIds`` lists the
UP token first and DOWN token second. We never assume ordering — we map
token ids by the outcome labels and record a substitution note if the
payload ever deviates from the expected shape.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime

from ...constants import ASSETS, MARKET_DURATION_SECONDS, MARKET_WINDOW_LABEL
from .fees import FeeSchedule, schedule_from_market

log = logging.getLogger("reversal.discovery")


def window_start(ts_sec: float) -> int:
    return int(ts_sec // MARKET_DURATION_SECONDS * MARKET_DURATION_SECONDS)


def slug_for(asset: str, start_sec: int) -> str:
    return f"{ASSETS[asset]['slug']}-updown-{MARKET_WINDOW_LABEL}-{start_sec}"


def _parse_iso_ms(s: str | None) -> int | None:
    if not s:
        return None
    try:
        return int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp() * 1000)
    except ValueError:
        return None


def _json_list(v) -> list:
    if v is None:
        return []
    if isinstance(v, list):
        return v
    try:
        return json.loads(v)
    except (TypeError, ValueError):
        return []


@dataclass
class DiscoveredMarket:
    asset: str
    slug: str
    gamma_event_id: str | None
    gamma_market_id: str | None
    condition_id: str | None
    question_id: str | None
    question: str | None
    up_token_id: str | None
    down_token_id: str | None
    open_ts: int
    close_ts: int
    active: bool
    closed: bool
    accepting_orders: bool
    resolution_source: str | None
    settlement_method: str | None
    twap_lookback_s: int | None
    fee: FeeSchedule
    tick_size: float | None
    min_order_size: float | None
    neg_risk: bool
    restricted: bool | None
    outcome_prices: list[str]
    uma_status: str | None
    substitution_note: str | None
    raw: dict

    @property
    def status(self) -> str:
        if self.uma_status == "resolved" and self.closed:
            return "resolved"
        if self.closed:
            return "closed"
        return "active" if self.active else "upcoming"

    @property
    def official_winner(self) -> str | None:
        """Winner from Gamma ``outcomePrices`` once officially resolved."""
        if not (self.closed and self.outcome_prices and len(self.outcome_prices) == 2):
            return None
        try:
            up, down = float(self.outcome_prices[0]), float(self.outcome_prices[1])
        except (TypeError, ValueError):
            return None
        if up == 1.0 and down == 0.0:
            return "UP"
        if down == 1.0 and up == 0.0:
            return "DOWN"
        if up == 0.5 and down == 0.5:
            return "SPLIT"  # 50/50 / cancelled style resolution
        return None


def parse_event(asset: str, slug: str, event: dict) -> DiscoveredMarket | None:
    markets = event.get("markets") or []
    notes: list[str] = []
    if not markets:
        return None
    if len(markets) != 1:
        notes.append(f"event contained {len(markets)} markets; using the one matching slug")
    m = next((x for x in markets if x.get("slug") == slug), markets[0])
    if m.get("slug") != slug:
        notes.append(f"SUBSTITUTION: market slug {m.get('slug')} differs from requested {slug}")

    outcomes = [str(o).strip().lower() for o in _json_list(m.get("outcomes"))]
    tokens = _json_list(m.get("clobTokenIds"))
    up_tok = down_tok = None
    if len(outcomes) == 2 and len(tokens) == 2 and set(outcomes) == {"up", "down"}:
        up_tok = tokens[outcomes.index("up")]
        down_tok = tokens[outcomes.index("down")]
        if outcomes[0] != "up":
            notes.append("outcome order was Down/Up; tokens mapped by label")
    else:
        notes.append(f"unexpected outcomes {outcomes} / {len(tokens)} tokens — market unusable")

    start_sec = int(slug.rsplit("-", 1)[-1])
    open_ts = _parse_iso_ms(m.get("eventStartTime") or event.get("startTime")) or start_sec * 1000
    close_ts = _parse_iso_ms(m.get("endDate") or event.get("endDate")) or (start_sec + MARKET_DURATION_SECONDS) * 1000
    if open_ts != start_sec * 1000:
        notes.append(f"eventStartTime {open_ts} != slug window start {start_sec * 1000}")
    if close_ts - open_ts != MARKET_DURATION_SECONDS * 1000:
        notes.append(f"duration {(close_ts - open_ts) / 1000:.0f}s is not 300s")

    cfg = m.get("cryptoMarketConfig") or {}
    twap = cfg.get("twapLookbackSeconds") if cfg.get("twapEnabled") else None
    if cfg and cfg.get("duration") and cfg.get("duration") != MARKET_WINDOW_LABEL:
        notes.append(f"cryptoMarketConfig duration {cfg.get('duration')} is not 5m")
    method = (
        f"Resolves UP if the Chainlink {asset}/USD "
        + (f"{twap}s-TWAP " if twap else "")
        + "value at window end is >= the value at window start; otherwise DOWN. "
        + f"Mechanism: {m.get('resolutionMechanism') or 'oracle'}; "
        + f"config: {cfg.get('id') or 'n/a'}."
    )
    tick = m.get("orderPriceMinTickSize")
    mos = m.get("orderMinSize")
    return DiscoveredMarket(
        asset=asset,
        slug=slug,
        gamma_event_id=str(event.get("id")) if event.get("id") is not None else None,
        gamma_market_id=str(m.get("id")) if m.get("id") is not None else None,
        condition_id=m.get("conditionId"),
        question_id=m.get("questionID"),
        question=m.get("question") or event.get("title"),
        up_token_id=up_tok,
        down_token_id=down_tok,
        open_ts=open_ts,
        close_ts=close_ts,
        active=bool(m.get("active")),
        closed=bool(m.get("closed")),
        accepting_orders=bool(m.get("acceptingOrders")),
        resolution_source=m.get("resolutionSource") or event.get("resolutionSource"),
        settlement_method=method,
        twap_lookback_s=int(twap) if twap else None,
        fee=schedule_from_market(m),
        tick_size=float(tick) if tick else None,
        min_order_size=float(mos) if mos else None,
        neg_risk=bool(m.get("negRisk")),
        restricted=m.get("restricted", event.get("restricted")),
        outcome_prices=_prices_up_down(outcomes, _json_list(m.get("outcomePrices"))),
        uma_status=m.get("umaResolutionStatus"),
        substitution_note="; ".join(notes) or None,
        raw={k: v for k, v in m.items() if k not in ("description",)},
    )


def _prices_up_down(outcomes: list[str], prices: list) -> list[str]:
    """Return outcomePrices ordered [UP, DOWN] by outcome label (never by position)."""
    prices = [str(x) for x in prices]
    if len(outcomes) == 2 and len(prices) == 2 and set(outcomes) == {"up", "down"}:
        return [prices[outcomes.index("up")], prices[outcomes.index("down")]]
    return prices


async def fetch_market(client, gamma_base: str, asset: str, start_sec: int) -> DiscoveredMarket | None:
    """Fetch one 5m window for ``asset`` from Gamma. Returns None if it does not exist."""
    slug = slug_for(asset, start_sec)
    r = await client.get(f"{gamma_base}/events", params={"slug": slug}, timeout=10)
    r.raise_for_status()
    data = r.json()
    if not data:
        return None
    return parse_event(asset, slug, data[0])
