"""Research recorder for 15-minute and 1-hour crypto Up/Down markets (record only — never traded).

Slower markets may have fewer fast bots and longer-lasting mispricings. This records every
second of every 15-minute market (order book top levels, Chainlink price, fast exchange price)
into separate tables so strategies can be tested on them later, without touching the 5-minute
collector or any running bot.
"""
from __future__ import annotations

import asyncio
import json
import logging

from sqlalchemy import select

from ..constants import ASSETS
from ..db import now_ms, session_scope
from ..models import ResearchMarket15, ResearchObs15
from ..providers.polymarket.market_ws import MarketChannel

log = logging.getLogger("reversal.research15")
WINDOWS = (("15m", 900), ("1h", 3600))   # recorded for research (never traded)


def _json_list(v):
    if isinstance(v, list):
        return v
    try:
        return json.loads(v or "[]")
    except ValueError:
        return []


class Research15:
    def __init__(self, collector) -> None:
        self.c = collector
        self.counts = {lab: 0 for lab, _ in WINDOWS}
        self.channel = MarketChannel(collector.settings.clob_market_ws_url)
        self.markets: dict[str, dict] = {}       # slug -> info
        self.running = False
        self.rows_written = 0
        self.errors = 0

    async def start(self) -> None:
        self.running = True
        self.channel.start()
        with session_scope() as s:
            for m in s.scalars(select(ResearchMarket15).where(ResearchMarket15.close_ts > now_ms())).all():
                self.markets[m.slug] = {"id": m.id, "asset": m.asset, "open_ts": m.open_ts, "close_ts": m.close_ts,
                                        "up": m.up_token, "down": m.down_token}
        if self.markets:
            await self.channel.track([t for m in self.markets.values() for t in (m["up"], m["down"])])
        for coro in (self._discover, self._sample, self._resolve):
            asyncio.create_task(self._guard(coro), name=f"research15-{coro.__name__}")

    async def _guard(self, coro) -> None:
        while self.running:
            try:
                await coro()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.errors += 1
                log.warning("research15 %s error: %r", coro.__name__, e)
                await asyncio.sleep(10)

    async def _discover(self) -> None:
        while self.running:
            now = now_ms() // 1000
            todo = [(lab, w, st) for lab, w in WINDOWS for st in (now // w * w, now // w * w + w)]
            for lab, WINDOW, st in todo:
                for a, meta in ASSETS.items():
                    slug = f"{meta['slug']}-updown-{lab}-{st}"
                    if slug in self.markets:
                        continue
                    r = await self.c.http.get(f"{self.c.settings.gamma_base_url}/events", params={"slug": slug}, timeout=10)
                    if r.status_code != 200 or not r.json():
                        continue
                    ev = r.json()[0]
                    mk = (ev.get("markets") or [{}])[0]
                    outs = [str(o).lower() for o in _json_list(mk.get("outcomes"))]
                    toks = _json_list(mk.get("clobTokenIds"))
                    if set(outs) != {"up", "down"} or len(toks) != 2:
                        continue
                    up, dn = toks[outs.index("up")], toks[outs.index("down")]
                    cfg = mk.get("cryptoMarketConfig") or {}
                    with session_scope() as s:
                        row = s.scalar(select(ResearchMarket15).where(ResearchMarket15.slug == slug))
                        if row is None:
                            row = ResearchMarket15(slug=slug, asset=a, open_ts=st * 1000, close_ts=(st + WINDOW) * 1000,
                                                   up_token=up, down_token=dn, condition_id=mk.get("conditionId"),
                                                   twap_s=cfg.get("twapLookbackSeconds") if cfg.get("twapEnabled") else None,
                                                   rule=(mk.get("description") or "")[:500])
                            s.add(row)
                            s.flush()
                        info = {"id": row.id, "asset": a, "open_ts": row.open_ts, "close_ts": row.close_ts, "up": up, "down": dn}
                    self.markets[slug] = info
                    await self.channel.track([up, dn])
            # forget markets that closed > 2 minutes ago
            for slug, m in list(self.markets.items()):
                if m["close_ts"] < now_ms() - 120_000:
                    await self.channel.untrack([m["up"], m["down"]])
                    self.markets.pop(slug, None)
            await asyncio.sleep(30)

    async def _sample(self) -> None:
        while self.running:
            t0 = now_ms()
            rows = []
            for m in list(self.markets.values()):
                if not (m["open_ts"] <= t0 < m["close_ts"]):
                    continue
                ub, db = self.channel.books.get(m["up"]), self.channel.books.get(m["down"])
                if not ub or not db or not ub.has_snapshot or not db.has_snapshot:
                    continue
                cl = self.c.prices.get(m["asset"], "chainlink")
                spot = cl.last.price if cl and cl.last else None
                fast = self.c._fast_spot(m["asset"], t0, spot).get("fast_spot")
                rows.append(ResearchObs15(
                    market_id=m["id"], ts=t0, secs_remaining=(m["close_ts"] - t0) / 1000.0,
                    up_bid=ub.best_bid, up_ask=ub.best_ask, down_bid=db.best_bid, down_ask=db.best_ask,
                    up_asks_json=json.dumps(ub.sorted_asks(5)), down_asks_json=json.dumps(db.sorted_asks(5)),
                    up_bids_json=json.dumps(ub.sorted_bids(5)), down_bids_json=json.dumps(db.sorted_bids(5)),
                    spot=spot, fast_spot=fast))
            if rows:
                def _w():
                    with session_scope() as s:
                        s.add_all(rows)
                await asyncio.to_thread(_w)
                self.rows_written += len(rows)
            await asyncio.sleep(max(0.05, 1.0 - (now_ms() - t0) / 1000))

    async def _resolve(self) -> None:
        while self.running:
            with session_scope() as s:
                todo = [(m.id, m.slug) for m in s.scalars(select(ResearchMarket15).where(
                    ResearchMarket15.winner.is_(None), ResearchMarket15.close_ts < now_ms() - 90_000,
                    ResearchMarket15.close_ts > now_ms() - 2 * 86400_000)).all()][:20]
            for mid, slug in todo:
                r = await self.c.http.get(f"{self.c.settings.gamma_base_url}/events", params={"slug": slug}, timeout=10)
                if r.status_code != 200 or not r.json():
                    continue
                mk = (r.json()[0].get("markets") or [{}])[0]
                outs = [str(o).lower() for o in _json_list(mk.get("outcomes"))]
                px = [float(x) for x in _json_list(mk.get("outcomePrices"))]
                if set(outs) != {"up", "down"} or len(px) != 2:
                    continue
                up_p = px[outs.index("up")]
                win = "UP" if up_p >= 0.99 else "DOWN" if up_p <= 0.01 else None
                if win:
                    with session_scope() as s:
                        row = s.get(ResearchMarket15, mid)
                        if row:
                            row.winner = win
            await asyncio.sleep(60)

    def health(self) -> dict:
        by = {}
        for slug in self.markets:
            lab = slug.split("-updown-")[1].split("-")[0]
            by[lab] = by.get(lab, 0) + 1
        return {"tracking": len(self.markets), "by_window": by, "rows_written": self.rows_written, "errors": self.errors}
