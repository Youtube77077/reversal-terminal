"""Live-trading eligibility.

Source: Polymarket geoblock policy (docs.polymarket.com/api-reference/geoblock, read 2026-11-17):
  * OFAC jurisdictions: blocked on frontend AND API.
  * Main regulatory list (e.g. US, GB, FR, DE, SG ...): close-only on frontend AND API.
  * Frontend-only list (NL, IE, JP, KR, MT-sports): close-only on the frontend;
    "the API itself is not restricted".

The Terms of Use (polymarket.com/tos, eff. 2026-08-11) separately list the Netherlands
as a place where trading is not permitted and prohibit VPNs to circumvent restrictions.
The two Polymarket sources conflict; the user has chosen to rely on the API policy.
This module surfaces that conflict on the Live panel and never uses VPN/proxy logic.
The server's own location is checked with the provider's geoblock endpoint, so
orders are only attempted from a location where the API accepts them.
"""
from __future__ import annotations

import httpx

from ..config import get_settings
from ..db import now_ms

FRONTEND_ONLY = {"NL", "IE", "JP", "KR", "MT"}
_cache: dict = {}


async def executor_health() -> dict:
    s = get_settings()
    try:
        async with httpx.AsyncClient(timeout=6) as c:
            r = await c.get(f"{s.executor_url}/health", headers={"Authorization": f"Bearer {s.executor_token}"})
            return r.json() if r.status_code == 200 else {"ok": False, "error": f"HTTP {r.status_code}"}
    except Exception as e:
        return {"ok": False, "error": f"executor unreachable: {e!r}"}


async def check_eligibility(force: bool = False) -> dict:
    s = get_settings()
    if _cache and not force and now_ms() - _cache.get("checked_ts", 0) < 60 * 1000:
        return _cache
    geo = {"reachable": False, "blocked": None, "country": None, "region": None, "error": None}
    try:
        async with httpx.AsyncClient(timeout=8) as c:
            d = (await c.get(s.geoblock_url)).json()
            geo.update(reachable=True, blocked=d.get("blocked"), country=d.get("country"), region=d.get("region"))
    except Exception as e:
        geo["error"] = repr(e)
    ex = await executor_health()
    blockers: list[str] = []
    if not s.live_trading_enabled:
        blockers.append("LIVE_TRADING_ENABLED is false in the server environment.")
    if not ex.get("ok"):
        blockers.append(f"Live executor not ready: {ex.get('error') or 'no credentials'}")
    if not geo["reachable"]:
        blockers.append("Could not verify the server location with Polymarket's geoblock endpoint.")
    elif geo["blocked"] and (geo["country"] or "").upper() not in FRONTEND_ONLY:
        blockers.append(f"Server location {geo['country']} is API-restricted by Polymarket — orders would be rejected.")
    warnings = []
    if (geo["country"] or s.user_country or "").upper() in FRONTEND_ONLY:
        warnings.append("Polymarket's geoblock docs say the API is not restricted for this country (frontend close-only), "
                        "but the Terms of Use list the Netherlands as not permitted for trading. Polymarket may place "
                        "wallets in close-only mode for ToS violations. You chose to proceed; trade at your own risk.")
    result = {
        "provider": "polymarket", "eligible": not blockers,
        "live_order_placement": "available" if not blockers else "unavailable",
        "market_data": "enabled", "paper_trading": "enabled", "user_country": s.user_country,
        "geoblock": geo, "executor": ex, "reasons": blockers, "warnings": warnings,
        "limits": {"max_order_usd": s.live_max_order_usd, "max_session_budget_usd": s.live_max_session_budget_usd},
        "checked_ts": now_ms(),
    }
    _cache.clear()
    _cache.update(result)
    return result
