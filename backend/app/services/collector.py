"""Persistent background data collector.

Runs inside the FastAPI process but is completely independent of any browser
tab. Responsibilities:

* discover the current and next 5-minute market for each enabled asset;
* keep live order books (CLOB websocket) and underlying prices (RTDS Chainlink
  + Binance) for every active market;
* sample one observation per market per second (UTC-aligned) and capture the
  exact T-minus checkpoints;
* fetch opening / settlement reference prices and official resolutions;
* classify reversals once a market is officially resolved;
* hand every tick to the paper-trading engine;
* detect and record data gaps; recover after restarts or sleep.

One failing asset never blocks the others: every per-asset step is isolated.
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import time

import httpx
from sqlalchemy import select, text
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from ..config import get_settings
from ..constants import ASSETS, CHECKPOINTS, MARKET_DURATION_SECONDS
from ..db import now_ms, session_scope
from ..models import (
    Asset,
    Checkpoint,
    CollectorGap,
    Market,
    MarketObservation,
    MarketResolution,
    OrderBookSnapshot,
    UnderlyingPrice,
)
from ..providers.polymarket.discovery import DiscoveredMarket, fetch_market, window_start
from ..providers.polymarket.fees import FeeSchedule
from ..providers.polymarket.market_ws import MarketChannel
from ..providers.polymarket.resolution import fetch_reference_prices, winner_from_prices
from ..providers.polymarket.rtds import ChainlinkFeed
from ..providers.spot.binance import BinanceFeed
from ..providers.spot.exchanges import FAST_SOURCES, CoinbaseFeed, HyperliquidFeed, OkxFeed
from .connections import registry
from .events import record_event
from .market_state import MarketState, build_state, implied_up_prob
from .orderbook import vwap_for_usd
from .price_store import PriceStore
from .reversal import classify, leader

log = logging.getLogger("reversal.collector")

db_write_lock = threading.Lock()


def _levels_json(levels: list[tuple[float, float]], depth: int = 5) -> str:
    return json.dumps([[round(p, 4), round(s, 2)] for p, s in levels[:depth]])


class Collector:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.assets = [a for a in self.settings.assets if a in ASSETS]
        self.prices = PriceStore()
        self.channel = MarketChannel(self.settings.clob_market_ws_url, on_update=self._on_book_update)
        self.chainlink = ChainlinkFeed(self.settings.rtds_ws_url, self.prices, self.assets)
        self.binance = BinanceFeed(self.settings.binance_ws_url, self.prices, self.assets)
        self.fast_feeds = [CoinbaseFeed(self.prices, self.assets), OkxFeed(self.prices, self.assets),
                           HyperliquidFeed(self.prices, self.assets)]
        self.http: httpx.AsyncClient | None = None
        self.markets: dict[int, Market] = {}          # active + upcoming market rows (detached copies)
        self.fees: dict[int, FeeSchedule] = {}
        self.checkpoints_done: dict[int, set[int]] = {}
        self.last_obs_ts: dict[int, int] = {}
        self.last_traded: dict[str, float] = {}
        self.live_states: dict[str, dict] = {}          # asset -> UI state
        self.asset_status: dict[str, dict] = {a: {"status": "starting", "detail": None} for a in self.assets}
        self.tasks: list[asyncio.Task] = []
        self.started_ts: int | None = None
        self.last_tick_ts: int | None = None
        self.tick_count = 0
        self.observations_written = 0
        self.missing_observations = 0
        self.write_errors = 0
        self.running = False
        self.engine = None  # set by main (TradingEngine)
        self.on_tick_listeners: list = []

    # ================================================================ lifecycle
    async def start(self) -> None:
        self.http = httpx.AsyncClient(headers={"User-Agent": "reversal-terminal/1.0 (research)"},
                                      timeout=15, follow_redirects=True)
        self.started_ts = now_ms()
        self.running = True
        self._ensure_assets()
        self._load_open_markets()
        self._record_restart_gaps()
        try:
            await asyncio.to_thread(self.repair_checkpoints)
        except Exception:
            log.exception("checkpoint repair failed")
        self.channel.start()
        self.chainlink.start()
        self.binance.start()
        for f in self.fast_feeds:
            f.start()
        for name, coro in (("discovery", self._discovery_loop), ("sampler", self._sample_loop),
                           ("refprice", self._refprice_loop), ("resolver", self._resolution_loop),
                           ("health", self._health_loop)):
            self.tasks.append(asyncio.create_task(self._supervise(name, coro), name=f"collector-{name}"))
        record_event("collector", "Collector started", data={"assets": self.assets})

    async def stop(self) -> None:
        self.running = False
        for t in self.tasks:
            t.cancel()
        await self.channel.stop()
        await self.chainlink.stop()
        await self.binance.stop()
        for f in self.fast_feeds:
            await f.stop()
        if self.http:
            await self.http.aclose()
        record_event("collector_stopped", "Collector stopped", level="WARNING")

    async def _supervise(self, name: str, factory) -> None:
        """Restart a crashed loop with backoff — background task supervision."""
        delay = 1.0
        while self.running:
            try:
                await factory()
                return
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.exception("loop %s crashed", name)
                record_event("collector", f"Loop '{name}' crashed: {e!r}; restarting in {delay:.0f}s", level="ERROR")
                await asyncio.sleep(delay)
                delay = min(delay * 2, 60)

    # ================================================================ bootstrap
    def _ensure_assets(self) -> None:
        with session_scope() as s:
            for sym, meta in ASSETS.items():
                row = s.get(Asset, sym)
                if row is None:
                    s.add(Asset(symbol=sym, name=meta["name"], slug_prefix=meta["slug"],
                                chainlink_symbol=meta["chainlink"], enabled=sym in self.assets, updated_ts=now_ms()))
                else:
                    row.enabled = sym in self.assets

    def _load_open_markets(self) -> None:
        cutoff = now_ms() - 60_000
        with session_scope() as s:
            rows = s.scalars(select(Market).where(Market.close_ts > cutoff, Market.status.in_(("upcoming", "active")))).all()
            for m in rows:
                s.expunge(m)
                self._register_market(m)
                done = s.scalars(select(Checkpoint.t_minus).where(Checkpoint.market_id == m.id)).all()
                self.checkpoints_done[m.id] = set(done)
                last = s.scalar(select(MarketObservation.server_ts).where(MarketObservation.market_id == m.id)
                                .order_by(MarketObservation.server_ts.desc()).limit(1))
                if last:
                    self.last_obs_ts[m.id] = last

    def _record_restart_gaps(self) -> None:
        """If the app was down (shutdown/sleep) while markets were open, record the gap honestly."""
        now = now_ms()
        with session_scope() as s:
            last = s.execute(text("SELECT asset, MAX(server_ts) FROM market_observations GROUP BY asset")).all()
            for asset, ts in last:
                if ts and now - ts > 5_000:
                    secs = int((now - ts) / 1000)
                    s.add(CollectorGap(asset=asset, start_ts=ts, end_ts=now, missing_seconds=secs, reason="app_offline"))
                    self.missing_observations += secs
        if last:
            record_event("collector", "Recovered after restart; offline gaps recorded", level="WARNING")

    def _register_market(self, m: Market) -> None:
        self.markets[m.id] = m
        raw = json.loads(m.raw_json) if m.raw_json else None
        if m.fee_verified and m.fee_rate is not None:
            self.fees[m.id] = FeeSchedule(rate=m.fee_rate, exponent=m.fee_exponent or 1.0,
                                          taker_only=bool(m.fee_taker_only), rebate_rate=m.fee_rebate_rate or 0.0,
                                          fee_type=m.fee_type, verified=True)
        else:
            from ..providers.polymarket.fees import schedule_from_market
            self.fees[m.id] = schedule_from_market(raw)
        self.checkpoints_done.setdefault(m.id, set())

    # ================================================================ discovery
    async def _discovery_loop(self) -> None:
        while self.running:
            now_s = time.time()
            ws = window_start(now_s)
            targets = [ws, ws + MARKET_DURATION_SECONDS]
            await asyncio.gather(*(self._discover_asset(a, targets) for a in self.assets), return_exceptions=True)
            await self._prune_subscriptions()
            # idempotent: guarantees books for markets restored from the DB after a restart
            await self.channel.track([t for m in self.markets.values() if m.close_ts > now_ms()
                                      for t in (m.up_token_id, m.down_token_id) if t])
            # poll faster around window boundaries so the next market is ready early
            secs_into = now_s - ws
            await asyncio.sleep(5 if secs_into > 240 or secs_into < 15 else self.settings.discovery_poll_seconds)

    async def _discover_asset(self, asset: str, starts: list[int]) -> None:
        for st in starts:
            if any(m.asset == asset and m.open_ts == st * 1000 for m in self.markets.values()):
                continue
            try:
                dm = await fetch_market(self.http, self.settings.gamma_base_url, asset, st)
                registry.ok("gamma")
            except Exception as e:
                registry.fail("gamma", repr(e))
                self._set_asset_status(asset, "offline", f"Gamma request failed: {e!r}")
                record_event("connection_failed", f"{asset}: market discovery failed ({e!r})", level="WARNING")
                continue
            if dm is None:
                if st == starts[0]:
                    self._set_asset_status(asset, "unavailable",
                                           f"No 5-minute market found for window starting {st} — not substituted")
                continue
            if not (dm.up_token_id and dm.down_token_id):
                self._set_asset_status(asset, "unavailable", f"Market {dm.slug} has unusable outcomes")
                continue
            m = self._upsert_market(dm)
            self._register_market(m)
            await self.channel.track([m.up_token_id, m.down_token_id])
            record_event("market_discovered", f"{asset}: discovered {dm.slug}",
                         data={"slug": dm.slug, "condition_id": dm.condition_id,
                               "substitution_note": dm.substitution_note})

    def _upsert_market(self, dm: DiscoveredMarket) -> Market:
        with db_write_lock, session_scope() as s:
            m = s.scalar(select(Market).where(Market.slug == dm.slug))
            if m is None:
                m = Market(asset=dm.asset, slug=dm.slug, discovered_ts=now_ms())
                s.add(m)
            m.window = "5m"
            m.gamma_event_id, m.gamma_market_id = dm.gamma_event_id, dm.gamma_market_id
            m.condition_id, m.question_id, m.question = dm.condition_id, dm.question_id, dm.question
            m.up_token_id, m.down_token_id = dm.up_token_id, dm.down_token_id
            m.open_ts, m.close_ts = dm.open_ts, dm.close_ts
            m.status = dm.status if dm.status != "upcoming" or now_ms() < dm.open_ts else "active"
            if now_ms() >= dm.open_ts and m.status == "upcoming":
                m.status = "active"
            m.resolution_source, m.settlement_method = dm.resolution_source, dm.settlement_method
            m.twap_lookback_s = dm.twap_lookback_s
            m.fee_type, m.fee_rate, m.fee_exponent = dm.fee.fee_type, dm.fee.rate, dm.fee.exponent
            m.fee_taker_only, m.fee_rebate_rate, m.fee_verified = dm.fee.taker_only, dm.fee.rebate_rate, dm.fee.verified
            m.tick_size, m.min_order_size, m.neg_risk = dm.tick_size, dm.min_order_size, dm.neg_risk
            m.restricted, m.substitution_note = dm.restricted, dm.substitution_note
            m.raw_json = json.dumps(dm.raw, default=str)
            s.flush()
            s.expunge(m)
            return m

    def _on_book_update(self, token: str) -> None:
        if self.engine is not None:
            try:
                self.engine.notify_book(token)
            except Exception:
                pass

    async def _prune_subscriptions(self) -> None:
        now = now_ms()
        stale = [m for m in self.markets.values() if m.close_ts < now - 20_000]
        for m in stale:
            await self.channel.untrack([m.up_token_id, m.down_token_id])
            self.markets.pop(m.id, None)
            self.fees.pop(m.id, None)
            self.checkpoints_done.pop(m.id, None)
            self.last_obs_ts.pop(m.id, None)
            ser = self.prices.get(m.asset, "chainlink")
            fin = ser.twap(m.close_ts - 60_000, m.close_ts) if ser and ser.ts and ser.ts[0] <= m.close_ts - 55_000 else None
            with db_write_lock, session_scope() as s:
                row = s.get(Market, m.id)
                if row and fin:
                    row.final_twap = fin
                if row and row.status in ("upcoming", "active"):
                    row.status = "closed"

    def _set_asset_status(self, asset: str, status: str, detail: str | None = None) -> None:
        prev = self.asset_status.get(asset, {}).get("status")
        self.asset_status[asset] = {"status": status, "detail": detail, "ts": now_ms()}
        if prev != status:
            try:
                with db_write_lock, session_scope() as s:
                    row = s.get(Asset, asset)
                    if row:
                        row.status, row.status_detail, row.updated_ts = status, detail, now_ms()
            except Exception:
                pass
            warmed_up = self.started_ts is not None and now_ms() - self.started_ts > 30_000
            if status in ("offline", "unavailable") and prev not in (None, "starting") and warmed_up:
                record_event("connection_failed", f"{asset} is {status}: {detail}", level="WARNING")

    # ================================================================ reference prices
    async def _refprice_loop(self) -> None:
        while self.running:
            now = now_ms()
            need = [m for m in self.markets.values() if m.open_ts <= now and m.open_price is None]
            for m in need:
                try:
                    rp = await fetch_reference_prices(self.http, self.settings.crypto_price_url, m.asset,
                                                      m.open_ts, m.close_ts)
                except Exception as e:
                    registry.fail("crypto_price", repr(e))
                    continue
                if rp and rp.get("open_price"):
                    registry.ok("crypto_price")
                    m.open_price = float(rp["open_price"])
                    m.open_price_source = "polymarket crypto-price (Chainlink TWAP stream)"
                    with db_write_lock, session_scope() as s:
                        row = s.get(Market, m.id)
                        if row:
                            row.open_price, row.open_price_source = m.open_price, m.open_price_source
            await asyncio.sleep(2)

    # ================================================================ sampler
    async def _sample_loop(self) -> None:
        interval = self.settings.observation_interval_ms / 1000.0
        while self.running:
            # align to whole seconds (+5 ms) so T-minus checkpoints land on exact seconds
            now = time.time()
            await asyncio.sleep(interval - (now % interval) + 0.005)
            try:
                await self._tick()
            except Exception:
                log.exception("tick failed")

    async def _tick(self) -> None:
        ts = now_ms()
        self.last_tick_ts = ts
        self.tick_count += 1
        states: list[MarketState] = []
        obs_rows: list[dict] = []
        ckpt_rows: list[dict] = []
        snap_rows: list[dict] = []
        px_rows: list[dict] = []
        gap_rows: list[dict] = []
        ts_sec = ts // 1000

        for asset in self.assets:
            for src in ("chainlink", "binance", "coinbase", "okx", "hyperliquid"):
                ser = self.prices.get(asset, src)
                if ser and ser.last and ts - ser.last.server_ts < 10_000:
                    px_rows.append({"asset": asset, "source": src, "ts_sec": ts_sec,
                                    "exchange_ts": ser.last.exchange_ts, "price": ser.last.price})

        active_assets: set[str] = set()
        for m in list(self.markets.values()):
            if not (m.open_ts <= ts < m.close_ts):
                continue
            active_assets.add(m.asset)
            try:
                st = self._state_for(m, ts)
            except Exception as e:
                log.warning("state build failed for %s: %r", m.slug, e)
                continue
            states.append(st)
            prev = self.last_obs_ts.get(m.id)
            if prev and ts - prev > 2500:
                missing = int((ts - prev) / 1000) - 1
                gap_rows.append({"asset": m.asset, "start_ts": prev, "end_ts": ts, "missing_seconds": missing,
                                 "reason": "sampling_gap"})
                self.missing_observations += missing
            self.last_obs_ts[m.id] = ts
            obs_rows.append(self._obs_row(m, st, ts_sec))
            # exact checkpoints
            k = round(st.secs_remaining)
            if k in CHECKPOINTS and abs(st.secs_remaining - k) < 0.5 and k not in self.checkpoints_done[m.id]:
                self.checkpoints_done[m.id].add(k)
                ckpt_rows.append(self._ckpt_row(m, st, k))
                snap_rows.append(self._snap_row(m, st, "checkpoint", k))
            self._update_live_state(m, st)

        for asset in self.assets:
            if asset not in active_assets and self.asset_status[asset]["status"] not in ("unavailable", "offline"):
                self._set_asset_status(asset, "waiting", "No active market this second")

        if obs_rows or px_rows or ckpt_rows:
            await asyncio.to_thread(self._write_batch, obs_rows, ckpt_rows, snap_rows, px_rows, gap_rows)

        if self.engine is not None and states:
            try:
                await self.engine.on_tick(states, ts)
            except Exception:
                log.exception("trading engine tick failed")
        for cb in self.on_tick_listeners:
            try:
                cb(states)
            except Exception:
                pass

    def _price_to_beat(self, m: Market, ts: int) -> float | None:
        """Settlement threshold = Chainlink 60s-TWAP at window start (official rule).

        Verified on 665 resolved markets: TWAP(end) >= TWAP(start) reproduces the official
        winner 98.7% of the time, vs 87% for the instantaneous open price.
        """
        ptb = getattr(m, "price_to_beat", None)
        if ptb:
            return ptb
        if ts < m.open_ts + 500:
            return None
        ser = self.prices.get(m.asset, "chainlink")
        if not ser or not ser.ts or ser.ts[0] > m.open_ts - 50_000:
            return None          # not enough history before the window started (e.g. just restarted)
        v = ser.twap(m.open_ts - 60_000, m.open_ts)
        if v:
            m.price_to_beat = v
            try:
                with db_write_lock, session_scope() as s:
                    row = s.get(Market, m.id)
                    if row:
                        row.price_to_beat = v
            except Exception:
                pass
        return v

    def _fast_spot(self, asset: str, ts: int, chainlink_spot: float | None) -> dict:
        """Blend of fast exchange feeds, each shifted onto Chainlink's level.

        Each exchange trades at a slightly different level (USDT vs USD, perp basis), so we
        measure each feed's typical gap to Chainlink over the last minute and remove it. The
        median of the adjusted feeds is where Chainlink is heading."""
        cl = self.prices.get(asset, "chainlink")
        ests, used = [], []
        for src in FAST_SOURCES:
            ser = self.prices.get(asset, src)
            if not ser or not ser.last or ts - ser.last.server_ts > 2000 or not cl or not cl.ts:
                continue
            diffs = []
            for k in range(5, 60, 5):
                a, b = cl.price_at(ts - k * 1000 - 1000), ser.price_at(ts - k * 1000 - 1000)
                if a and b:
                    diffs.append(a - b)
            if len(diffs) < 4:
                continue
            diffs.sort()
            ests.append(ser.last.price + diffs[len(diffs) // 2])
            used.append(src)
        if not ests:
            return {"fast_spot": None, "fast_sources": [], "lead": None}
        ests.sort()
        n = len(ests)
        fast = ests[n // 2] if n % 2 else (ests[n // 2 - 1] + ests[n // 2]) / 2
        return {"fast_spot": fast, "fast_sources": used,
                "lead": (fast - chainlink_spot) if chainlink_spot else None}

    def _state_for(self, m: Market, ts: int) -> MarketState:
        src = self.settings.price_provider_for(m.asset)
        ptb = self._price_to_beat(m, ts) or m.open_price
        feats = self.prices.features(m.asset, src, ts, ptb)
        if feats.get("spot") is None and src != "binance":  # fallback, recorded in spot_source
            feats = self.prices.features(m.asset, "binance", ts, ptb)
        # average of the settlement window so far (the part of the final 60s TWAP already known)
        ser = self.prices.get(m.asset, src)
        win_start = m.close_ts - 60_000
        feats["twap_window"] = ser.twap(win_start, ts) if (ser and ts > win_start + 500) else None
        feats["price_to_beat"] = ptb
        feats["ptb_exact"] = bool(getattr(m, "price_to_beat", None))
        feats.update(self._fast_spot(m.asset, ts, feats.get("spot")))
        st = build_state(m, self.channel.books.get(m.up_token_id), self.channel.books.get(m.down_token_id),
                         feats, ts, self.fees.get(m.id) or FeeSchedule())
        st.open_price = ptb
        status = "live" if (st.book_ok and st.spot_ok) else ("degraded" if (st.book_ok or st.spot_ok) else "offline")
        detail = None if status == "live" else (
            ("order book not synced; " if not st.book_ok else "") + ("spot feed stale" if not st.spot_ok else ""))
        self._set_asset_status(m.asset, status, detail)
        return st

    def _obs_row(self, m: Market, st: MarketState, ts_sec: int) -> dict:
        f = st.features
        upb, dnb = self.channel.books.get(m.up_token_id), self.channel.books.get(m.down_token_id)
        vol = 0.0
        for b in (upb, dnb):
            if b is not None:
                prev = self.last_traded.get(b.token_id, b.traded_shares)
                vol += max(0.0, b.traded_shares - prev)
                self.last_traded[b.token_id] = b.traded_shares
        return {
            "market_id": m.id, "asset": m.asset, "ts_sec": ts_sec, "server_ts": st.server_ts,
            "book_exchange_ts": st.book_exchange_ts, "secs_remaining": st.secs_remaining,
            "up_bid": st.up_bid, "up_ask": st.up_ask, "down_bid": st.down_bid, "down_ask": st.down_ask,
            "up_mid": st.up_mid, "down_mid": st.down_mid,
            "up_bid_size": st.up_bid_size, "up_ask_size": st.up_ask_size,
            "down_bid_size": st.down_bid_size, "down_ask_size": st.down_ask_size,
            "up_ask_liq": st.ask_liquidity_usd("UP", depth=5), "down_ask_liq": st.ask_liquidity_usd("DOWN", depth=5),
            "up_bid_liq": sum(p * s for p, s in st.up_bids[:5]), "down_bid_liq": sum(p * s for p, s in st.down_bids[:5]),
            "last_trade_up": upb.last_trade_price if upb else None,
            "last_trade_down": dnb.last_trade_price if dnb else None,
            "trade_volume": vol,
            "spot": f.get("spot"), "spot_exchange_ts": f.get("spot_exchange_ts"), "spot_source": f.get("spot_source"),
            "twap60_est": f.get("twap60_est"), "open_price": st.open_price, "fast_spot": f.get("fast_spot"), "twap_window": f.get("twap_window"),
            "dist_abs": f.get("dist_abs"), "dist_bps": f.get("dist_bps"),
            "mom_1s": f.get("mom_1s"), "mom_3s": f.get("mom_3s"), "mom_5s": f.get("mom_5s"),
            "mom_10s": f.get("mom_10s"), "mom_30s": f.get("mom_30s"), "mom_60s": f.get("mom_60s"),
            "vol_30s": f.get("vol_30s"), "accel": f.get("accel"),
            "up_asks_json": _levels_json(st.up_asks), "down_asks_json": _levels_json(st.down_asks),
            "book_ok": st.book_ok, "spot_ok": st.spot_ok,
        }

    def _ckpt_row(self, m: Market, st: MarketState, k: int) -> dict:
        fav, dog = st.favourite, st.underdog
        valid = st.book_ok and fav is not None
        reason = None if valid else ("book_not_synced" if not st.book_ok else "no_favourite")
        dog_asks = st.asks(dog) if dog else []
        return {
            "market_id": m.id, "asset": m.asset, "t_minus": k, "server_ts": st.server_ts,
            "actual_secs_remaining": st.secs_remaining, "favourite": fav, "fav_prob": st.fav_prob,
            "fav_bid": st.bid(fav) if fav else None, "fav_ask": st.ask(fav) if fav else None,
            "dog_bid": st.bid(dog) if dog else None, "dog_ask": st.ask(dog) if dog else None,
            "dog_ask_size": st.ask_size(dog) if dog else None,
            "dog_ask_liq": st.ask_liquidity_usd(dog, depth=10) if dog else None,
            "dog_spread": st.spread(dog) if dog else None,
            "dog_vwap_10usd": vwap_for_usd(dog_asks, 10.0) if dog_asks else None,
            "spot": st.features.get("spot"), "open_price": st.open_price, "dist_bps": st.features.get("dist_bps"),
            "mom_10s": st.features.get("mom_10s"), "mom_30s": st.features.get("mom_30s"),
            "momentum_toward_dog": st.momentum_toward(dog) if dog else None,
            "valid": valid, "invalid_reason": reason, "source": "live",
        }

    def _snap_row(self, m: Market, st: MarketState, reason: str, k: int | None) -> dict:
        return {"market_id": m.id, "server_ts": st.server_ts, "exchange_ts": st.book_exchange_ts, "reason": reason,
                "t_minus": k, "up_bids_json": json.dumps(st.up_bids), "up_asks_json": json.dumps(st.up_asks),
                "down_bids_json": json.dumps(st.down_bids), "down_asks_json": json.dumps(st.down_asks)}

    def _write_batch(self, obs, ckpts, snaps, pxs, gaps) -> None:
        try:
            with db_write_lock, session_scope() as s:
                if obs:
                    s.execute(sqlite_insert(MarketObservation).values(obs).on_conflict_do_nothing())
                    for o in obs:
                        s.execute(text("UPDATE markets SET observation_count = observation_count + 1, "
                                       "status = CASE WHEN status='upcoming' THEN 'active' ELSE status END "
                                       "WHERE id = :id"), {"id": o["market_id"]})
                if ckpts:
                    s.execute(sqlite_insert(Checkpoint).values(ckpts).on_conflict_do_nothing())
                if snaps:
                    s.execute(sqlite_insert(OrderBookSnapshot).values(snaps))
                if pxs:
                    s.execute(sqlite_insert(UnderlyingPrice).values(pxs).on_conflict_do_nothing())
                if gaps:
                    s.execute(sqlite_insert(CollectorGap).values(gaps))
            self.observations_written += len(obs)
        except Exception as e:
            self.write_errors += 1
            log.exception("batch write failed")
            record_event("database", f"Batch write failed: {e!r}", level="ERROR", persist=False)

    def _update_live_state(self, m: Market, st: MarketState) -> None:
        f = st.features
        dog = st.underdog
        self.live_states[m.asset] = {
            "asset": m.asset, "market_id": m.id, "slug": m.slug, "question": m.question,
            "open_ts": m.open_ts, "close_ts": m.close_ts, "secs_remaining": st.secs_remaining,
            "up_bid": st.up_bid, "up_ask": st.up_ask, "down_bid": st.down_bid, "down_ask": st.down_ask,
            "up_mid": st.up_mid, "down_mid": st.down_mid, "up_prob": st.up_prob,
            "up_spread": st.spread("UP"), "down_spread": st.spread("DOWN"),
            "up_ask_liq": st.ask_liquidity_usd("UP", depth=5), "down_ask_liq": st.ask_liquidity_usd("DOWN", depth=5),
            "spot": f.get("spot"), "spot_source": f.get("spot_source"), "twap60_est": f.get("twap60_est"),
            "open_price": st.open_price, "dist_abs": f.get("dist_abs"), "dist_bps": f.get("dist_bps"),
            "mom_10s": f.get("mom_10s"), "mom_30s": f.get("mom_30s"), "vol_30s": f.get("vol_30s"),
            "favourite": st.favourite, "fav_prob": st.fav_prob, "underdog": dog,
            "underdog_ask": st.ask(dog) if dog else None, "book_ok": st.book_ok, "spot_ok": st.spot_ok,
            "status": self.asset_status[m.asset]["status"], "status_detail": self.asset_status[m.asset].get("detail"),
            "server_ts": st.server_ts, "book_exchange_ts": st.book_exchange_ts,
            "fee_rate": st.fee.rate, "fee_verified": st.fee.verified,
            "binance_spot": (self.prices.get(m.asset, "binance").last.price
                             if self.prices.get(m.asset, "binance") and self.prices.get(m.asset, "binance").last else None),
        }

    # ================================================================ resolution
    async def _resolution_loop(self) -> None:
        while self.running:
            try:
                await self.resolve_pending()
            except Exception:
                log.exception("resolution pass failed")
            await asyncio.sleep(self.settings.resolution_poll_seconds)

    async def resolve_pending(self, limit: int = 60) -> int:
        now = now_ms()
        with session_scope() as s:
            rows = s.execute(
                select(Market.id, Market.asset, Market.slug, Market.open_ts, Market.close_ts, Market.open_price)
                .where(Market.close_ts < now - 3000, Market.status.notin_(("resolved", "cancelled")))
                .order_by(Market.close_ts.desc()).limit(limit)
            ).all()
        resolved = 0
        for mid, asset, slug, ots, cts, op in rows:
            try:
                if await self._resolve_one(mid, asset, slug, ots, cts, op):
                    resolved += 1
            except Exception as e:
                log.warning("resolve %s failed: %r", slug, e)
        return resolved

    async def _resolve_one(self, mid: int, asset: str, slug: str, ots: int, cts: int, op: float | None) -> bool:
        rp = None
        try:
            rp = await fetch_reference_prices(self.http, self.settings.crypto_price_url, asset, ots, cts)
            if rp:
                registry.ok("crypto_price")
        except Exception as e:
            registry.fail("crypto_price", repr(e))
        dm = None
        try:
            dm = await fetch_market(self.http, self.settings.gamma_base_url, asset, ots // 1000)
            registry.ok("gamma")
        except Exception as e:
            registry.fail("gamma", repr(e))
        open_p = (rp or {}).get("open_price") or op
        close_p = (rp or {}).get("close_price")
        price_winner = winner_from_prices(open_p, close_p) if (rp and rp.get("completed")) else None
        official = dm.official_winner if dm else None
        with db_write_lock, session_scope() as s:
            res = s.get(MarketResolution, mid) or MarketResolution(market_id=mid)
            s.add(res)
            res.attempts = (res.attempts or 0) + 1
            res.checked_ts = now_ms()
            res.open_price, res.close_price = open_p, close_p
            res.price_api_winner = price_winner
            if dm:
                res.gamma_outcome_prices = json.dumps(dm.outcome_prices)
                res.uma_status = dm.uma_status
            m = s.get(Market, mid)
            if m and open_p and not m.open_price:
                m.open_price = open_p
            if m and close_p:
                m.close_price = close_p
            if official in ("UP", "DOWN"):
                res.winner, res.official, res.status, res.resolved_ts = official, True, "resolved", now_ms()
                res.sources_agree = (price_winner == official) if price_winner else None
                if m:
                    m.winner, m.status, m.resolved_ts = official, "resolved", res.resolved_ts
            elif official == "SPLIT":
                res.status, res.official = "cancelled", True
                if m:
                    m.status = "cancelled"
            elif price_winner:
                res.status = "provisional"
                if m and m.status not in ("resolved",):
                    m.status = "closed"
            if res.attempts > 400 and not res.official:
                # ~100 min of polling without an official result: mark, keep trades unresolved
                res.status = "stale"
        if official in ("UP", "DOWN"):
            await asyncio.to_thread(self._classify_market, mid, official)
            if self.engine is not None:
                await self.engine.settle_market(mid, official)
            return True
        if official == "SPLIT" and self.engine is not None:
            await self.engine.cancel_market(mid, "market resolved 50/50 (cancelled)")
        return False

    def _classify_market(self, mid: int, winner: str) -> None:
        with db_write_lock, session_scope() as s:
            obs = s.execute(select(MarketObservation.secs_remaining, MarketObservation.up_bid,
                                   MarketObservation.up_ask, MarketObservation.down_bid, MarketObservation.down_ask,
                                   MarketObservation.spot)
                            .where(MarketObservation.market_id == mid, MarketObservation.book_ok.is_(True))
                            .order_by(MarketObservation.server_ts)).all()
            ups = [(sr, implied_up_prob(ub, ua, db_, da), sp) for sr, ub, ua, db_, da, sp in obs]
            final_spot = next((sp for sr, p, sp in reversed(ups) if sp is not None), None)
            late = next((leader(p) for sr, p, sp in reversed(ups) if p is not None and sr <= 3.0), None)
            for c in s.scalars(select(Checkpoint).where(Checkpoint.market_id == mid, Checkpoint.source == "live")).all():
                later = [p for sr, p, sp in ups if sr < c.actual_secs_remaining]
                cl = classify(c.favourite, winner, later, c.spot, c.mom_10s, final_spot, late)
                c.winner = winner
                c.favourite_lost = cl.favourite_lost
                c.price_crossover_after = cl.price_crossover_after
                c.underlying_reversal = cl.underlying_reversal
                c.settlement_reversal = cl.settlement_reversal

    # ================================================================ repair
    def repair_checkpoints(self) -> int:
        """Rebuild checkpoints marked invalid 'no_favourite' from the recorded observation at the same second.

        Earlier builds derived probability from midpoints only and so lost one-sided books near expiry.
        The raw observation (bids/asks/depth) was always stored, so the checkpoint can be reconstructed
        exactly. Resolved markets are re-classified afterwards.
        """
        fixed, markets = 0, set()
        with db_write_lock, session_scope() as s:
            bad = s.scalars(select(Checkpoint).where(Checkpoint.valid.is_(False),
                                                     Checkpoint.invalid_reason == "no_favourite")).all()
            for c in bad:
                o = s.scalar(select(MarketObservation).where(MarketObservation.market_id == c.market_id,
                                                             MarketObservation.server_ts == c.server_ts))
                if o is None or not o.book_ok:
                    continue
                p = implied_up_prob(o.up_bid, o.up_ask, o.down_bid, o.down_ask)
                if p is None or p == 0.5:
                    continue
                fav = "UP" if p > 0.5 else "DOWN"
                dog = "DOWN" if fav == "UP" else "UP"
                asks = json.loads((o.down_asks_json if dog == "DOWN" else o.up_asks_json) or "[]")
                pick = lambda side, a, b: (a if side == "UP" else b)
                c.favourite, c.fav_prob = fav, max(p, 1 - p)
                c.fav_bid, c.fav_ask = pick(fav, o.up_bid, o.down_bid), pick(fav, o.up_ask, o.down_ask)
                c.dog_bid, c.dog_ask = pick(dog, o.up_bid, o.down_bid), pick(dog, o.up_ask, o.down_ask)
                c.dog_ask_size = pick(dog, o.up_ask_size, o.down_ask_size)
                c.dog_ask_liq = sum(px * sz for px, sz in asks)
                c.dog_spread = (c.dog_ask - c.dog_bid) if (c.dog_ask is not None and c.dog_bid is not None) else None
                c.dog_vwap_10usd = vwap_for_usd([(px, sz) for px, sz in asks], 10.0) if asks else None
                m10 = o.mom_10s
                c.momentum_toward_dog = None if not m10 else ((m10 > 0) if dog == "UP" else (m10 < 0))
                c.valid, c.invalid_reason = True, None
                fixed += 1
                markets.add(c.market_id)
            winners = dict(s.execute(select(Market.id, Market.winner).where(Market.id.in_(markets),
                                                                          Market.winner.in_(("UP", "DOWN")))).all())
        for mid, w in winners.items():
            self._classify_market(mid, w)
        if fixed:
            record_event("collector", f"Repaired {fixed} checkpoints from recorded observations "
                                      f"({len(winners)} resolved markets re-classified)")
        return fixed

    # ================================================================ health
    async def _health_loop(self) -> None:
        while self.running:
            await asyncio.sleep(10)
            try:
                await asyncio.to_thread(registry.flush)
            except Exception:
                pass
            if self.last_tick_ts and now_ms() - self.last_tick_ts > 15_000:
                record_event("collector_stopped", "Sampler has not ticked for 15 s", level="ERROR")

    def health(self) -> dict:
        return {
            "running": self.running,
            "started_ts": self.started_ts,
            "last_tick_ts": self.last_tick_ts,
            "tick_count": self.tick_count,
            "fast_strategy_checks": getattr(self.engine, "fast_checks", 0) if self.engine else 0,
            "observations_written": self.observations_written,
            "missing_observations": self.missing_observations,
            "write_errors": self.write_errors,
            "clob_ws": {"connected": self.channel.connected, "reconnect_attempts": self.channel.attempt,
                        "last_message_ts": self.channel.last_message_ts, "tokens": len(self.channel.books)},
            "rtds": {"connected": self.chainlink.connected, "reconnect_attempts": self.chainlink.attempt,
                     "last_message_ts": self.chainlink.last_message_ts},
            "binance": {"connected": self.binance.connected, "reconnect_attempts": self.binance.attempt},
            "active_markets": len([m for m in self.markets.values() if m.open_ts <= now_ms() < m.close_ts]),
            "tracked_markets": len(self.markets),
            "asset_status": self.asset_status,
        }


collector = Collector()
