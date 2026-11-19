"""Automated paper-trading engine.

Pipeline per tick (1 Hz, driven by the collector):
  live market state -> strategy evaluation -> account risk checks -> signal
  -> funds reservation -> simulated latency -> execution against the real
  order book (partial fills allowed) -> position tracking -> official
  settlement -> ledger + statistics update.

Trading only happens while an experiment is running and the engine is not
paused. Data collection continues regardless.
"""
from __future__ import annotations

import asyncio
import json
import logging
import secrets
import time
from datetime import datetime, timezone

from sqlalchemy import select

from ..constants import price_bucket
from ..db import now_ms, session_scope
from ..models import (
    Account,
    Asset,
    Checkpoint,
    Experiment,
    FeeRecord,
    Market,
    OrderBookSnapshot,
    Signal,
    SimFill,
    SimOrder,
    Transaction,
)
from ..providers.polymarket.fees import FeeSchedule, taker_fee
from ..services.collector import db_write_lock
from ..services.events import record_event
from ..services.market_state import MarketState
from ..strategies.library import Decision, StrategyContext, evaluate
from . import accounting, risk
from .base import ExecutionReport, OrderIntent
from .live_polymarket import PolymarketLiveAdapter
from .paper import PaperExecutionAdapter
from .simulator import max_cost, simulate_passive_check

log = logging.getLogger("reversal.engine")


FAST_KEYS = {"O", "X"}     # strategies evaluated by the sub-second loop
FAST_MS = 50               # fallback: 20 checks per second (plus instantly on every order-book change)
EXIT_EVERY_MS = 200        # take-profit checks (DB query) at most 5x per second
FAST_WINDOW_MS = 125_000   # only the last ~2 minutes of each market


def new_tx_id() -> str:
    return "TX-" + datetime.now(timezone.utc).strftime("%y%m%d") + "-" + secrets.token_hex(3).upper()


class TradingEngine:
    def __init__(self, collector) -> None:
        self.collector = collector
        self.paper = PaperExecutionAdapter(lambda tok: collector.channel.books.get(tok))
        self.live = PolymarketLiveAdapter()
        self.live_eligible = False          # refreshed every 60 s from eligibility.check_eligibility()
        self.live_armed = False             # user must arm live mode in the UI (password confirmed)
        self.loop: asyncio.AbstractEventLoop | None = None
        self.paused = False
        self.inflight: set[tuple[int, int]] = set()     # (account_id, market_id) being processed
        self.resting: dict[int, dict] = {}              # order_id -> info for passive orders
        self.hist_cache: dict[tuple[str, int, str], tuple[int, int]] = {}
        self.hist_cache_ts = 0
        self.opportunities: dict[int, dict] = {}        # market_id -> latest live opportunity
        self._notified_opps: set[int] = set()
        self._halt_notified: set[int] = set()
        self.last_tick_ts: int | None = None
        self.tasks: set[asyncio.Task] = set()
        self._done: set[tuple[int, int]] = set()             # (account, market) at its trade limit
        self._why: dict[int, dict] = {}                       # account -> minute -> reason -> [seconds, example, ts]
        self._why_last: dict[tuple[int, str], float] = {}     # throttle: count each reason at most once a second
        self._rejected: set[tuple[int, int, str]] = set()   # dedupe identical rejections per market
        self._fast_accounts: list[dict] = []                 # accounts running a FAST strategy (e.g. O)
        self._fast_task: asyncio.Task | None = None
        self.fast_checks = 0
        self._wake: asyncio.Event | None = None
        self._last_exit_check = 0.0
        self._cand: dict[tuple[int, int], dict] = {}        # (account, market) -> best candidate so far

    # ================================================================ context
    def _refresh_hist(self) -> None:
        if time.time() - self.hist_cache_ts < 60:
            return
        cache: dict[tuple[str, int, str], list[int]] = {}
        with session_scope() as s:
            rows = s.execute(select(Checkpoint.asset, Checkpoint.t_minus, Checkpoint.dog_ask, Checkpoint.favourite_lost)
                             .join(Market, Market.id == Checkpoint.market_id)
                             .where(Checkpoint.valid.is_(True), Checkpoint.favourite_lost.is_not(None),
                                    Checkpoint.source == "live", Market.window == "5m")).all()
        for asset, t, ask, lost in rows:
            b = price_bucket(ask)
            if b is None:
                continue
            for key in ((asset, t, b), ("ALL", t, b)):
                c = cache.setdefault(key, [0, 0])
                c[0] += 1 if lost else 0
                c[1] += 1
        self.hist_cache = {k: (v[0], v[1]) for k, v in cache.items()}
        self.hist_cache_ts = time.time()

    def hist_lookup(self, asset: str, t_minus: int, price: float) -> tuple[int, int]:
        b = price_bucket(price)
        if b is None:
            return (0, 0)
        return self.hist_cache.get((asset, t_minus, b), (0, 0))

    # ================================================================ tick
    async def on_tick(self, states: list[MarketState], ts: int) -> None:
        self.last_tick_ts = ts
        self._scan(states)
        if self.resting:
            await asyncio.to_thread(self._check_resting, {st.market_id: st for st in states}, ts)
        if self.paused:
            return
        exp = await asyncio.to_thread(self._running_experiment)
        accounts, paused_assets = await asyncio.to_thread(self._load_accounts, exp)
        self._fast_accounts = [a for a in accounts if a["strategy_key"] in FAST_KEYS
                               and not a["paused"] and not a["halted_reason"]]
        win = FAST_WINDOW_MS
        for a in self._fast_accounts:
            try:
                win = max(win, int(float(json.loads(a["params_json"] or "{}").get("entry_max_secs") or 0) * 1000) + 5000)
            except (ValueError, TypeError):
                pass
        self._fast_window_ms = win
        self._paused_assets = paused_assets
        if self._fast_accounts and (self._fast_task is None or self._fast_task.done()):
            self._fast_task = asyncio.create_task(self._fast_loop(), name="fast-strategy-loop")
        if not accounts:
            return
        await asyncio.to_thread(self._refresh_hist)
        await self._check_exits(accounts, {st.market_id: st for st in states})
        ctx = StrategyContext(hist_lookup=self.hist_lookup)
        for acct in accounts:
            if acct["paused"] or acct["halted_reason"]:
                continue
            params = json.loads(acct["params_json"] or "{}")
            allowed = acct["assets"]
            wins = params.get("windows") or ["5m"]
            for st in states:
                if st.asset not in allowed or st.asset in paused_assets or st.window not in wins:
                    continue
                key = (acct["id"], st.market_id)
                if key in self.inflight or key in self._done:
                    continue
                if acct["strategy_key"] in FAST_KEYS:
                    continue                      # evaluated 5x per second by _fast_loop
                decision, _why = evaluate(acct["strategy_key"], st, params, ctx)
                if decision is None:
                    continue
                self.inflight.add(key)
                t = asyncio.create_task(self._enter(acct["id"], st, decision, acct["exp_id"]))
                self.tasks.add(t)
                t.add_done_callback(self.tasks.discard)

    def _scan(self, states: list[MarketState]) -> None:
        now = now_ms()
        for st in states:
            dog = st.underdog
            if dog is None or st.fav_prob is None:
                self.opportunities.pop(st.market_id, None)
                continue
            ask = st.ask(dog)
            if ask is not None and ask <= 0.20 and st.fav_prob >= 0.80:
                self.opportunities[st.market_id] = {
                    "market_id": st.market_id, "asset": st.asset, "slug": st.slug, "ts": now,
                    "secs_remaining": st.secs_remaining, "favourite": st.favourite, "fav_prob": st.fav_prob,
                    "underdog": dog, "dog_ask": ask, "dog_ask_size": st.ask_size(dog),
                    "liquidity_usd": st.ask_liquidity_usd(dog, max_price=ask), "spread": st.spread(dog),
                    "dist_bps": st.dist_bps, "mom_toward_dog": st.momentum_toward(dog),
                    "executable": st.ask_liquidity_usd(dog, max_price=ask) >= 1.0,
                }
                if (st.fav_prob >= 0.95 and ask <= 0.05 and st.secs_remaining <= 30
                        and st.market_id not in self._notified_opps):
                    self._notified_opps.add(st.market_id)
                    record_event("opportunity", f"{st.asset}: {dog} at {ask:.2f} with favourite {st.fav_prob:.1%} "
                                                f"T-{st.secs_remaining:.0f}s", persist=False,
                                 data=self.opportunities[st.market_id])
            else:
                self.opportunities.pop(st.market_id, None)
        for mid in [m for m, o in self.opportunities.items() if now - o["ts"] > 3000]:
            self.opportunities.pop(mid, None)
        if len(self._notified_opps) > 5000:
            self._notified_opps.clear()

    def _running_experiment(self) -> dict | None:
        with session_scope() as s:
            e = s.scalar(select(Experiment).where(Experiment.status == "running").limit(1))
            if not e:
                return None
            return {"id": e.id, "assets_json": e.assets_json, "account_ids_json": e.account_ids_json}

    def _load_accounts(self, exp: dict | None) -> tuple[list[dict], set[str]]:
        """Accounts that may trade now: members of the running experiment, plus any account
        with a running bot session ("Start bot"). Live accounts additionally need live mode
        armed and eligibility confirmed."""
        from ..constants import ASSETS
        exp_ids = set(json.loads(exp["account_ids_json"])) if exp else set()
        exp_assets = set(json.loads(exp["assets_json"])) if exp else set()
        with session_scope() as s:
            rows = s.scalars(select(Account).where(Account.active.is_(True), Account.archived.is_(False))).all()
            paused_assets = set(s.scalars(select(Asset.symbol).where(Asset.paused.is_(True))).all())
            out = []
            for a in rows:
                in_exp = a.id in exp_ids
                in_session = a.risk_budget_mode in ("percent", "amount") and a.session_start_ts is not None
                if not (in_exp or in_session):
                    continue
                if a.mode == "live" and not (self.live_armed and self.live_eligible and in_session):
                    continue  # live accounts never trade unless armed, eligible AND in a risk-bounded session
                try:
                    p = json.loads(a.params_json or "{}")
                except ValueError:
                    p = {}
                assets = set(p.get("assets") or []) or (exp_assets if in_exp else set(ASSETS))
                out.append({"id": a.id, "strategy_key": a.strategy_key, "params_json": a.params_json,
                            "paused": a.paused, "halted_reason": a.halted_reason, "mode": a.mode,
                            "assets": assets, "exp_id": exp["id"] if (exp and in_exp) else None})
            return out, paused_assets

    # ================================================================ entry
    def _custom_prepare(self, account_id: int, d: Decision, st: MarketState) -> str | None:
        """Strategy Builder bots: stake from balance (capped by max loss per trade) + daily guards.
        Returns a reason to skip, or None to go ahead (d.shares is resized in place)."""
        import math
        from datetime import datetime
        from ..strategies.custom import AMS, merged, stake_usd
        with session_scope() as s:
            acct = s.get(Account, account_id)
            if acct is None or acct.strategy_key != "X":
                return None
            p = merged(json.loads(acct.params_json or "{}"))
            equity = self._equity_estimate(s, acct)
            day0 = int(datetime.now(AMS).replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)
            today = s.scalars(select(Transaction).where(Transaction.account_id == account_id, Transaction.source == "live",
                                                        Transaction.created_ts >= day0)).all()
            open_n = sum(1 for t in today if t.status in ("pending", "filled", "partially_filled"))
            here = s.scalars(select(Transaction).where(Transaction.account_id == account_id, Transaction.source == "live",
                                                       Transaction.market_id == st.market_id,
                                                       Transaction.status.notin_(("cancelled", "expired")))).all()
            settled = [t for t in today if t.status in ("won", "lost")]
            losses = sum(1 for t in settled if (t.net_profit or 0) < 0)
            day_pnl = sum((t.net_profit or 0) for t in settled)
            start_bal = max(equity - day_pnl, 1e-9)
        per_mkt = int(p.get("max_trades_per_market", 1) or 0)
        if per_mkt > 0 and len(here) >= per_mkt:
            return "max trades in this market reached"
        if any(t.status in ("pending", "filled", "partially_filled") for t in here):
            return "holding a position in this market: waiting to sell"
        last_out = max((t.settled_ts or 0 for t in here), default=0)
        cool = float(p.get("reentry_cooldown_secs") or 0)
        if last_out and now_ms() - last_out < cool * 1000:
            return f"waiting {cool:g}s before buying again in this market"
        if int(p.get("max_open_positions") or 0) and open_n >= int(p["max_open_positions"]):
            return "max open trades reached"
        if int(p.get("max_trades_per_day") or 0) and len(today) >= int(p["max_trades_per_day"]):
            return "max trades per day reached"
        if int(p.get("max_losses_per_day") or 0) and losses >= int(p["max_losses_per_day"]):
            return "stopped for today: too many losses"
        if float(p.get("daily_loss_limit_pct") or 0) and -day_pnl >= start_bal * float(p["daily_loss_limit_pct"]) / 100:
            return "stopped for today: daily loss limit"
        if float(p.get("daily_profit_cap_pct") or 0) and day_pnl >= start_bal * float(p["daily_profit_cap_pct"]) / 100:
            return "stopped for today: profit target reached"
        stake = stake_usd(p, equity)
        shares = math.floor(stake / d.limit_price * 100) / 100 if d.limit_price else 0
        if shares < (st.min_order_size or 5) or shares * d.limit_price < max(1.0, float(p.get("min_order_usd") or 1)):
            min_cost = max((st.min_order_size or 5) * d.limit_price, 1.0)
            pct = min(float(p["stake_value"]), float(p.get("max_loss_pct") or 100)) if p.get("stake_mode") != "fixed" else 0
            need = f"; the wallet needs about ${min_cost / (pct / 100):.0f} at {pct:g}% per trade" if pct else ""
            return (f"stake ${stake:.2f} too small: Polymarket needs at least 5 shares = ${min_cost:.2f} "
                    f"(balance ${equity:.2f}){need}")
        d.shares = shares
        return None

    async def _enter(self, account_id: int, st: MarketState, d: Decision, exp_id: str | None) -> None:
        try:
            why = await asyncio.to_thread(self._custom_prepare, account_id, d, st)
            if why:
                self._note_why(account_id, why)
                if "per day" in why or "today" in why or "too small" in why or "in this market reached" in why:
                    self._done.add((account_id, st.market_id))
                return
            opened = await asyncio.to_thread(self._open_order, account_id, st, d, exp_id)
            if not opened:
                return
            order_id, txid, intent, mode = opened
            if mode == "live":
                if not (self.live_armed and self.live_eligible):
                    rep = ExecutionReport("failed", [], intent.shares, reason="live mode disarmed before submission",
                                          executed_ts=now_ms())
                else:
                    rep = await self.live.submit(intent, fee=st.fee, min_shares=st.min_order_size,
                                                 tick_size=st.tick_size)
            else:
                rep = await self.paper.submit(intent, fee=st.fee, min_shares=st.min_order_size,
                                              tick_size=st.tick_size)
            await asyncio.to_thread(self._apply_execution, order_id, txid, rep, st)
        except Exception:
            log.exception("entry failed")
        finally:
            # keep the (account, market) pair blocked; risk max_trades_per_market decides re-entry
            await asyncio.sleep(1.0)
            self.inflight.discard((account_id, st.market_id))

    def _equity_estimate(self, s, acct: Account) -> float:
        mark = self.mark_prices(s, acct.id)
        return accounting.account_summary(s, acct, mark)["equity"]

    def _open_order(self, account_id: int, st: MarketState, d: Decision, exp_id: str | None):
        cost = max_cost(d.limit_price, d.shares, st.fee)
        liq = st.ask_liquidity_usd(d.side, max_price=d.limit_price)
        with db_write_lock, session_scope() as s:
            acct = s.get(Account, account_id)
            if acct is None:
                return None
            equity = self._equity_estimate(s, acct)
            hist_n = d.reasons.get("hist_n")
            edge = None
            if "hist_win_prob" in d.expected:
                edge = d.expected["hist_win_prob"] - d.expected["breakeven_prob"]
            per_mkt = None
            if acct.strategy_key == "X":
                from ..strategies.custom import merged as _cm
                n_ = int(_cm(json.loads(acct.params_json or "{}")).get("max_trades_per_market", 1) or 0)
                per_mkt = 10 ** 9 if n_ <= 0 else n_
            rd = risk.check(s, acct, st.market_id, cost, liq, st.spread(d.side), edge, hist_n, equity, per_mkt)
            if not rd.ok and rd.reason:
                if rd.reason.startswith("already"):
                    self._done.add((acct.id, st.market_id))   # trade limit reached: stop re-evaluating
                    return None
                rkey = (acct.id, st.market_id, " ".join(rd.reason.split()[:2]))
                if rkey in self._rejected:
                    return None                                # same rejection already recorded for this market
                self._rejected.add(rkey)
                if len(self._rejected) > 50_000:
                    self._rejected.clear()
            if len(self._done) > 50_000:
                self._done.clear()
            sig = Signal(ts=st.server_ts, account_id=acct.id, strategy_key=acct.strategy_key, experiment_id=exp_id,
                         market_id=st.market_id, asset=st.asset, side=d.side, secs_remaining=st.secs_remaining,
                         fav_prob=st.fav_prob, entry_ask=d.decision_ask, ask_liq=liq, spread=st.spread(d.side),
                         dist_bps=st.dist_bps, decision="accepted" if rd.ok else "rejected",
                         reject_reason=rd.reason, detail_json=json.dumps({"reasons": d.reasons,
                                                                          "expected": d.expected}, default=str))
            s.add(sig)
            s.flush()
            e = s.get(Experiment, exp_id) if exp_id else None
            if e:
                e.signal_count += 1
            if not rd.ok:
                if rd.reason and rd.reason.startswith("insufficient funds") and acct.cash <= 0.0:
                    acct.halted_reason = "virtual balance is zero — stopped placing new trades"
                    if acct.id not in self._halt_notified:
                        self._halt_notified.add(acct.id)
                        record_event("loss_limit", f"Account '{acct.name}': insufficient funds, trading stopped",
                                     level="WARNING", data={"account_id": acct.id})
                elif rd.reason and ("daily loss" in rd.reason or "drawdown" in rd.reason):
                    if acct.id not in self._halt_notified:
                        self._halt_notified.add(acct.id)
                        record_event("loss_limit", f"Account '{acct.name}': {rd.reason}", level="WARNING",
                                     data={"account_id": acct.id})
                return None
            snap = OrderBookSnapshot(market_id=st.market_id, server_ts=st.server_ts, exchange_ts=st.book_exchange_ts,
                                     reason="order_decision", up_bids_json=json.dumps(st.up_bids),
                                     up_asks_json=json.dumps(st.up_asks), down_bids_json=json.dumps(st.down_bids),
                                     down_asks_json=json.dumps(st.down_asks))
            s.add(snap)
            s.flush()
            txid = new_tx_id()
            expire = st.close_ts - 1000 if d.order_type == "passive_limit" else None
            order = SimOrder(account_id=acct.id, signal_id=sig.id, transaction_id=txid, market_id=st.market_id,
                             token_id=st.token(d.side), side=d.side, order_type=d.order_type, tif=d.tif,
                             limit_price=d.limit_price, requested_shares=d.shares, reserved_amount=cost,
                             status="pending", decision_ts=st.server_ts, expire_ts=expire, decision_book_id=snap.id)
            s.add(order)
            s.flush()
            snapshot = st.to_snapshot()
            snapshot["decision"] = {"reasons": d.reasons, "expected": d.expected}
            s.add(Transaction(
                id=txid, account_id=acct.id, experiment_id=exp_id, strategy_key=acct.strategy_key, mode=acct.mode,
                market_duration=st.window,
                source="live", signal_id=sig.id, order_id=order.id, market_id=st.market_id, asset=st.asset,
                outcome=d.side, order_type=d.order_type, limit_price=d.limit_price, decision_ask=d.decision_ask,
                requested_shares=d.shares, unfilled_shares=d.shares, status="pending", created_ts=st.server_ts,
                entry_secs_remaining=st.secs_remaining, fee_estimated=st.fee.estimated,
                predicted_prob=d.expected.get("model_win_prob") or d.expected.get("hist_win_prob"),
                entry_snapshot_json=json.dumps(snapshot, default=str)))
            accounting.reserve(s, acct, cost, txid)
            intent = OrderIntent(account_id=acct.id, market_id=st.market_id, token_id=st.token(d.side), side=d.side,
                                 order_type=d.order_type, tif=d.tif, limit_price=d.limit_price, shares=d.shares,
                                 expire_ts=expire, decision_ts=st.server_ts)
            from ..services.wallets import wallet_key_for_account
            intent.meta["wallet"] = wallet_key_for_account(s, acct)
            return order.id, txid, intent, acct.mode

    # ================================================================ execution results
    def _apply_execution(self, order_id: int, txid: str, rep: ExecutionReport, st: MarketState) -> None:
        with db_write_lock, session_scope() as s:
            order = s.get(SimOrder, order_id)
            tx = s.get(Transaction, txid)
            acct = s.get(Account, order.account_id)
            book_up = self.collector.channel.books.get(st.up_token)
            book_dn = self.collector.channel.books.get(st.down_token)
            snap = OrderBookSnapshot(
                market_id=st.market_id, server_ts=rep.executed_ts or now_ms(), reason="order_execution",
                exchange_ts=max([b.exchange_ts or 0 for b in (book_up, book_dn) if b] or [0]) or None,
                up_bids_json=json.dumps(book_up.sorted_bids(10) if book_up else []),
                up_asks_json=json.dumps(book_up.sorted_asks(10) if book_up else []),
                down_bids_json=json.dumps(book_dn.sorted_bids(10) if book_dn else []),
                down_asks_json=json.dumps(book_dn.sorted_asks(10) if book_dn else []))
            s.add(snap)
            s.flush()
            order.execution_book_id = snap.id
            order.executed_ts = rep.executed_ts
            if rep.status == "pending":
                self.resting[order.id] = {"txid": txid, "market_id": st.market_id, "token": order.token_id,
                                          "fee": st.fee, "rule": "trade_through"}
                order.status = "pending"
                record_event("order_simulated", f"{st.asset}: resting BUY {order.side} {order.requested_shares:g} @ "
                                                f"{order.limit_price}", persist=False, data={"tx": txid})
                return
            self._book_fills(s, order, tx, acct, rep.fills, rep.executed_ts or now_ms(), st)
            if rep.status in ("failed", "unfilled"):
                order.status = rep.status
                order.failure_reason = rep.reason
                tx.status = "cancelled"
                tx.notes = f"{'Rejected' if rep.status == 'failed' else 'Not filled'}: {rep.reason}"
            else:
                order.status = rep.status
                if rep.reason:
                    order.failure_reason = rep.reason
            # release whatever is left of the reservation
            accounting.release(s, acct, order.reserved_amount, txid)
            order.reserved_amount = 0.0
            accounting.snapshot_balance(s, acct, self.mark_prices(s, acct.id))
            if order.filled_shares > 0:
                e = s.get(Experiment, tx.experiment_id) if tx.experiment_id else None
                if e:
                    e.trade_count += 1
            record_event("order_simulated",
                         f"{st.asset}: BUY {order.side} {order.filled_shares:g}/{order.requested_shares:g} @ "
                         f"{tx.entry_price or order.limit_price:.3f} -> {order.status}", persist=False,
                         data={"tx": txid, "account_id": acct.id, "status": order.status})

    def _book_fills(self, s, order: SimOrder, tx: Transaction, acct: Account, fills, ts: int, st: MarketState) -> None:
        if not fills:
            return
        decision_mid = st.bids(order.side)[0][0] if st.bids(order.side) else None
        if decision_mid is not None and tx.decision_ask is not None:
            decision_mid = (decision_mid + tx.decision_ask) / 2
        for f in fills:
            sf = SimFill(order_id=order.id, ts=ts, price=f.price, shares=f.shares, notional=f.notional, fee=f.fee,
                         role=f.role)
            s.add(sf)
            s.flush()
            if f.fee > 0:
                s.add(FeeRecord(transaction_id=tx.id, fill_id=sf.id, kind="trading", amount=f.fee,
                                estimated=st.fee.estimated, formula=st.fee.describe()))
            cost = f.notional + f.fee
            accounting.debit_fill(s, acct, cost, tx.id, f"fill {f.shares:g} @ {f.price} ({f.role}) + fee {f.fee:.5f}")
            order.reserved_amount = max(0.0, order.reserved_amount - cost)
            order.filled_shares = round(order.filled_shares + f.shares, 6)
            slip = (f.price - (tx.decision_ask or f.price)) * f.shares
            spread_c = (f.price - decision_mid) * f.shares if decision_mid is not None else 0.0
            tx.gross_cost = round(tx.gross_cost + f.notional, 6)
            tx.trading_fee = round(tx.trading_fee + f.fee, 6)
            tx.slippage = round(tx.slippage + slip, 6)
            tx.spread_cost = round(tx.spread_cost + spread_c, 6)
        tx.filled_shares = order.filled_shares
        tx.unfilled_shares = round(max(0.0, order.requested_shares - order.filled_shares), 6)
        tx.entry_price = tx.gross_cost / tx.filled_shares if tx.filled_shares else None
        tx.total_cost = round(tx.gross_cost + tx.trading_fee + tx.gas_fee + tx.network_fee, 6)
        tx.potential_payout = tx.filled_shares
        tx.entry_ts = tx.entry_ts or ts
        tx.status = "filled" if tx.unfilled_shares <= 1e-6 else "partially_filled"
        if tx.slippage:
            s.add(FeeRecord(transaction_id=tx.id, kind="slippage", amount=round(tx.slippage, 6), estimated=False,
                            formula="sum((fill_price - decision_ask) * shares) — embedded in gross cost"))
        s.add(FeeRecord(transaction_id=tx.id, kind="gas", amount=0.0, estimated=True,
                        formula="CLOB matching and settlement are gasless for traders (relayer-paid)"))

    def _check_resting(self, states: dict[int, MarketState], ts: int) -> None:
        for oid, info in list(self.resting.items()):
            st = states.get(info["market_id"])
            with db_write_lock, session_scope() as s:
                order = s.get(SimOrder, oid)
                if order is None or order.status not in ("pending", "partially_filled"):
                    self.resting.pop(oid, None)
                    continue
                tx = s.get(Transaction, info["txid"])
                acct = s.get(Account, order.account_id)
                if order.expire_ts and ts >= order.expire_ts:
                    order.status = "expired"
                    tx.status = "partially_filled" if order.filled_shares > 0 else "expired"
                    tx.notes = "Passive limit order expired before market close"
                    accounting.release(s, acct, order.reserved_amount, tx.id, "expired order reservation released")
                    order.reserved_amount = 0.0
                    self.resting.pop(oid, None)
                    continue
                if st is None:
                    continue
                remaining = order.requested_shares - order.filled_shares
                fills = simulate_passive_check(st.asks(order.side), order.limit_price, remaining, info["fee"],
                                               info["rule"])
                if fills:
                    self._book_fills(s, order, tx, acct, fills, ts, st)
                    order.status = "filled" if order.filled_shares >= order.requested_shares - 1e-6 else "partially_filled"
                    if order.status == "filled":
                        accounting.release(s, acct, order.reserved_amount, tx.id)
                        order.reserved_amount = 0.0
                        self.resting.pop(oid, None)

    # ================================================================ fast loop (strategy O)
    def notify_book(self, token: str) -> None:
        """Order book changed -> wake the fast loop immediately (called on the event loop)."""
        if self._wake is not None:
            self._wake.set()

    async def _fast_loop(self) -> None:
        """Re-evaluate fast strategies every FAST_MS using the newest order book AND the newest
        exchange prices at the same instant (the 1-second sampler is too slow for a ~2 s edge)."""
        ctx = StrategyContext(hist_lookup=self.hist_lookup)
        log.info("fast strategy loop started (%d account(s))", len(self._fast_accounts))
        self._wake = asyncio.Event()
        while self._fast_accounts:
            t0 = time.perf_counter()
            self.fast_checks += 1
            try:
                if not self.paused:
                    now = now_ms()
                    markets = [m for m in list(self.collector.markets.values())
                               if m.open_ts <= now < m.close_ts and (m.close_ts - now) <= getattr(self, "_fast_window_ms", FAST_WINDOW_MS)]
                    if markets:
                        states = []
                        for m in markets:
                            try:
                                states.append(self.collector._state_for(m, now))
                            except Exception:
                                continue
                        smap = {st.market_id: st for st in states}
                        if time.perf_counter() - self._last_exit_check >= EXIT_EVERY_MS / 1000:
                            self._last_exit_check = time.perf_counter()
                            await self._check_exits(self._fast_accounts, smap)
                        for acct in self._fast_accounts:
                            params = json.loads(acct["params_json"] or "{}")
                            wins = params.get("windows") or ["5m"]
                            checked = False
                            for st in states:
                                if (st.asset not in acct["assets"] or st.asset in getattr(self, "_paused_assets", set())
                                        or st.window not in wins):
                                    continue
                                key = (acct["id"], st.market_id)
                                if key in self.inflight or key in self._done:
                                    continue
                                diag: dict = {}
                                decision, why = evaluate(acct["strategy_key"], st, params, ctx, diag)
                                checked = checked or why != "outside entry window"
                                if diag:
                                    self._note_candidate(acct, st, diag, why, decision is not None)
                                if decision is None:
                                    self._note_why(acct["id"], why)
                                    continue
                                self._note_why(acct["id"], f"signal found: {st.asset} {decision.side} at {decision.decision_ask:.2f}")
                                self.inflight.add(key)
                                t = asyncio.create_task(self._enter(acct["id"], st, decision, acct["exp_id"]))
                                self.tasks.add(t)
                                t.add_done_callback(self.tasks.discard)
                            if not checked:
                                self._note_why(acct["id"], "waiting")
                    else:
                        for acct in self._fast_accounts:
                            self._note_why(acct["id"], "waiting")
            except Exception:
                log.exception("fast loop error")
            # wait for the next order-book change, or FAST_MS at most; never spin faster than 20 ms
            spent = time.perf_counter() - t0
            if spent < 0.02:
                await asyncio.sleep(0.02 - spent)
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=max(0.0, FAST_MS / 1000 - max(spent, 0.02)))
            except asyncio.TimeoutError:
                pass
            self._wake.clear()

    def _note_why(self, account_id: int, why: str | None) -> None:
        """Remember why a bot did not trade (counted at most once per second per reason)."""
        cat = why_category(why)
        t = time.time()
        if t - self._why_last.get((account_id, cat), 0) < 1.0:
            return
        self._why_last[(account_id, cat)] = t
        w = self._why.setdefault(account_id, {})
        b = w.setdefault(int(t // 60), {})
        e = b.get(cat)
        if e is None:
            b[cat] = [1, why or "", now_ms()]
        else:
            e[0] += 1; e[1] = why or ""; e[2] = now_ms()
        if len(w) > 70:
            for k in sorted(w)[:-61]:
                w.pop(k, None)

    def why_summary(self, account_id: int, minutes: int = 30) -> dict:
        now_min = int(time.time() // 60)
        agg: dict[str, list] = {}
        for m, b in list(self._why.get(account_id, {}).items()):
            if m <= now_min - minutes:
                continue
            for cat, (n, ex, ts) in b.items():
                a = agg.setdefault(cat, [0, ex, ts])
                a[0] += n
                if ts >= a[2]:
                    a[1], a[2] = ex, ts
        rows = [{"reason": c, "seconds": v[0], "example": v[1], "last_ts": v[2]} for c, v in agg.items()]
        rows.sort(key=lambda r: -r["seconds"])
        return {"minutes": minutes, "reasons": rows[:12]}

    def _note_candidate(self, acct: dict, st: MarketState, diag: dict, why: str | None, traded: bool) -> None:
        key = (acct["id"], st.market_id)
        cur = self._cand.get(key)
        n = (cur or {}).get("checks", 0) + 1
        if traded or cur is None or (not cur.get("traded") and diag.get("edge", -9) > cur.get("edge", -9)):
            self._cand[key] = {**diag, "account_id": acct["id"], "strategy_key": acct["strategy_key"],
                               "market_id": st.market_id, "asset": st.asset, "ts": st.server_ts,
                               "reason": None if traded else (why or "")[:160], "traded": traded or bool((cur or {}).get("traded")),
                               "checks": n}
        else:
            cur["checks"] = n

    def _drift_guard(self, s, acct) -> None:
        """Real money only: pause if results fall far below what the model predicted.

        Over the last 40 settled trades with a predicted chance, if actual wins are more than
        2.5 standard deviations below the expected number of wins, something is wrong (market
        changed, feed issue, bug) — stop and tell the user rather than keep losing."""
        if acct is None or acct.mode != "live" or acct.halted_reason:
            return
        rows = s.execute(select(Transaction.predicted_prob, Transaction.net_profit).where(
            Transaction.account_id == acct.id, Transaction.status.in_(("won", "lost")),
            Transaction.predicted_prob.is_not(None)).order_by(Transaction.settled_ts.desc()).limit(40)).all()
        if len(rows) < 40:
            return
        exp = sum(p for p, _ in rows)
        var = sum(p * (1 - p) for p, _ in rows)
        wins = sum(1 for _, pnl in rows if (pnl or 0) > 0)
        if var > 0 and wins < exp - 2.5 * var ** 0.5:
            acct.halted_reason = (f"Paused for safety: {wins} wins in the last 40 trades vs about {exp:.0f} "
                                  f"expected — results are far below the model's predictions")
            record_event("loss_limit", f"{acct.name}: {acct.halted_reason}", level="WARNING",
                         data={"account_id": acct.id}, persist=True)

    def _flush_candidates(self, s, market_id: int, winner: str) -> None:
        from ..models import StrategyCandidate
        for key in [k for k in list(self._cand) if k[1] == market_id]:
            c = self._cand.pop(key, None)
            if not c:
                continue
            ask = c.get("ask")
            wp = None
            if ask and 0 < ask < 1 and winner in ("UP", "DOWN"):
                fee_pd = 0.07 * (1 - ask)       # fee per $1 spent
                wp = (1 / ask - 1 - fee_pd) if c.get("side") == winner else -(1 + fee_pd)
            s.add(StrategyCandidate(account_id=c["account_id"], strategy_key=c["strategy_key"], market_id=market_id,
                                    asset=c["asset"], ts=c["ts"], secs_remaining=c.get("secs"), side=c.get("side"),
                                    ask=ask, model_prob=c.get("model_prob"), breakeven=c.get("breakeven"),
                                    edge=c.get("edge"), reason=c.get("reason"), traded=bool(c.get("traded")),
                                    checks=c.get("checks", 0), winner=winner, would_pnl_per_dollar=wp))

    # ================================================================ early exits (take profit)
    async def _check_exits(self, accounts: list[dict], states: dict[int, MarketState]) -> None:
        """Sell an open position early when its best bid reaches the strategy's take_profit_price."""
        from ..strategies.library import default_params
        wanted = {}
        for a in accounts:
            p = {**default_params(a["strategy_key"]), **json.loads(a["params_json"] or "{}")}
            tp = float(p.get("take_profit_price") or 0)
            is_x = a["strategy_key"] == "X"
            sp = float(p.get("stop_price") or 0) if is_x else 0.0
            tpc = float(p.get("take_profit_cents") or 0) if is_x else 0.0
            slc = float(p.get("stop_loss_cents") or 0) if is_x else 0.0
            if 0 < tp < 1 or 0 < sp < 1 or tpc > 0 or slc > 0:
                wanted[a["id"]] = {"tp": tp if 0 < tp < 1 else None, "stop": sp if 0 < sp < 1 else None,
                                   "z_stop": float(p.get("z_stop") or 0), "use_fast": bool(p.get("use_fast", True)),
                                   "rel": {"take_profit_cents": tpc, "stop_loss_cents": slc} if (tpc > 0 or slc > 0) else None}
        if not wanted:
            return
        todo = await asyncio.to_thread(self._exit_candidates, wanted, states)
        for txid, mode, st, side, shares, price, token, wallet in todo:
            key = ("exit", txid)
            if key in self.inflight:
                continue
            self.inflight.add(key)
            try:
                if mode == "live":
                    if not self.live_armed:
                        continue
                    res = await self.live.sell(token, price, shares, wallet)
                    if not res.get("ok"):
                        record_event("order_simulated", f"{st.asset}: early SELL failed - {res.get('error')}",
                                     level="WARNING", persist=False, data={"tx": txid})
                        continue
                    matched = float(res.get("sizeMatched") or 0)
                    if matched <= 0:
                        continue
                    fills = [(price, matched)]
                else:
                    fills = _bids_fills(st.bids(side), shares, price)
                    if not fills:
                        continue
                await asyncio.to_thread(self._book_exit, txid, fills, st)
            finally:
                self.inflight.discard(key)

    def _exit_candidates(self, wanted: dict, states: dict) -> list:
        from ..services.wallets import wallet_key_for_account
        out = []
        with session_scope() as s:
            txs = s.scalars(select(Transaction).where(
                Transaction.account_id.in_(list(wanted)), Transaction.source == "live",
                Transaction.status.in_(("filled", "partially_filled")), Transaction.filled_shares > 0,
                Transaction.market_id.in_(list(states)))).all()
            for tx in txs:
                st = states.get(tx.market_id)
                if st is None or st.secs_remaining <= 1.0:
                    continue
                bids = st.bids(tx.outcome)
                w = wanted[tx.account_id]
                if not bids:
                    continue
                price = None
                rel = None
                if w.get("rel") and tx.entry_price:
                    from ..strategies.custom import scalp_exit
                    rel = scalp_exit(w["rel"], tx.entry_price, bids[0][0], st.fee)
                if w["tp"] and bids[0][0] >= w["tp"] - 1e-9:
                    price = w["tp"]                                   # take profit
                elif rel == "take profit":
                    price = bids[0][0]                                # +X cents after fees: sell at the best bid
                elif rel == "stop":
                    price = max(0.01, round(bids[0][0] - 0.03, 2))    # -X cents: accept up to 3c below best bid
                elif w["stop"] and bids[0][0] <= w["stop"] + 1e-9:
                    from ..strategies.custom import safety_z
                    z = safety_z(st, tx.outcome, w["use_fast"])
                    if z is None or z < w["z_stop"]:                    # only sell when really at risk
                        price = max(0.01, round(bids[0][0] - 0.05, 2))  # stop: accept up to 5c below best bid
                if price is None:
                    continue
                acct = s.get(Account, tx.account_id)
                out.append((tx.id, tx.mode, st, tx.outcome, tx.filled_shares, price, st.token(tx.outcome),
                            wallet_key_for_account(s, acct)))
        return out

    def _book_exit(self, txid: str, fills: list, st: MarketState) -> None:
        with db_write_lock, session_scope() as s:
            tx = s.get(Transaction, txid)
            if tx is None or tx.status not in ("filled", "partially_filled"):
                return
            acct = s.get(Account, tx.account_id)
            sold = min(sum(q for _, q in fills), tx.filled_shares)
            gross = sum(p * q for p, q in fills)
            fee = sum(taker_fee(q, p, st.fee) for p, q in fills)
            proceeds = round(gross - fee, 6)
            avg = gross / sold if sold else 0.0
            accounting.credit_settlement(s, acct, proceeds, tx.id,
                                         f"sold {sold:g} {tx.outcome} early @ {avg:.3f} (fee {fee:.4f})")
            if fee > 0:
                s.add(FeeRecord(transaction_id=tx.id, kind="trading", amount=round(fee, 6),
                                estimated=st.fee.estimated, formula="early-exit sell: " + st.fee.describe()))
            tx.trading_fee = round(tx.trading_fee + fee, 6)
            tx.exit_proceeds = round((tx.exit_proceeds or 0.0) + proceeds, 6)
            tx.exit_price = avg
            tx.filled_shares = round(tx.filled_shares - sold, 6)
            tx.potential_payout = tx.filled_shares
            if tx.filled_shares <= 1e-6:
                tx.filled_shares = 0.0
                tx.gross_payout = tx.exit_proceeds
                tx.net_profit = round(tx.exit_proceeds - tx.total_cost, 6)
                tx.roi = tx.net_profit / tx.total_cost if tx.total_cost else None
                tx.status = "won" if tx.net_profit > 0 else "lost"
                tx.settlement_outcome = "SOLD"
                tx.settled_ts = now_ms()
                tx.holding_seconds = (tx.settled_ts - (tx.entry_ts or tx.created_ts)) / 1000.0
            tx.notes = ((tx.notes or "") + f" Sold {sold:g} early at {avg:.2f} for ${proceeds:.2f}.").strip()
            accounting.snapshot_balance(s, acct, self.mark_prices(s, acct.id))
        record_event("trade_settled", f"{st.asset} {txid} SOLD EARLY @ {avg:.2f} -> ${proceeds:.2f}",
                     data={"tx": txid, "status": "sold", "proceeds": proceeds})

    # ================================================================ settlement
    async def settle_market(self, market_id: int, winner: str) -> None:
        self.loop = asyncio.get_running_loop()
        await asyncio.to_thread(self._settle, market_id, winner)

    def _settle(self, market_id: int, winner: str) -> None:
        settled = []
        live_wins = None
        with db_write_lock, session_scope() as s:
            # expire anything still resting on this market
            for o in s.scalars(select(SimOrder).where(SimOrder.market_id == market_id,
                                                      SimOrder.status.in_(("pending",)))).all():
                acct = s.get(Account, o.account_id)
                tx = s.get(Transaction, o.transaction_id)
                o.status = "expired"
                accounting.release(s, acct, o.reserved_amount, o.transaction_id, "order expired at resolution")
                o.reserved_amount = 0.0
                self.resting.pop(o.id, None)
                if tx and tx.filled_shares <= 0:
                    tx.status = "expired"
            txs = s.scalars(select(Transaction).where(Transaction.market_id == market_id, Transaction.source == "live",
                                                      Transaction.status.in_(("filled", "partially_filled", "unresolved")))
                            ).all()
            m = s.get(Market, market_id)
            try:
                self._flush_candidates(s, market_id, winner)
            except Exception:
                log.exception("candidate flush failed")
            for tx in txs:
                if tx.filled_shares <= 0:
                    tx.status = "expired"
                    continue
                acct = s.get(Account, tx.account_id)
                payout = tx.filled_shares if tx.outcome == winner else 0.0
                tx.settlement_outcome = winner
                gross = payout + (tx.exit_proceeds or 0.0)      # shares sold early were credited already
                tx.gross_payout = round(gross, 6)
                tx.net_profit = round(gross - tx.total_cost, 6)
                tx.roi = tx.net_profit / tx.total_cost if tx.total_cost else None
                tx.status = "won" if tx.net_profit > 0 else "lost"
                tx.settled_ts = now_ms()
                tx.holding_seconds = (tx.settled_ts - (tx.entry_ts or tx.created_ts)) / 1000.0
                if payout > 0 and tx.mode == "live" and m is not None:
                    from ..services.wallets import wallet_key_for_account
                    live_wins = (m.condition_id, wallet_key_for_account(s, acct))
                if payout > 0:
                    accounting.credit_settlement(s, acct, payout, tx.id,
                                                 f"{tx.filled_shares:g} {tx.outcome} shares x $1 ({m.slug if m else ''})")
                else:
                    accounting.credit_settlement(s, acct, 0.0, tx.id, f"{tx.outcome} lost — shares expire worthless")
                e = s.get(Experiment, tx.experiment_id) if tx.experiment_id else None
                if e:
                    if payout > 0:
                        e.win_count += 1
                    else:
                        e.loss_count += 1
                accounting.snapshot_balance(s, acct, self.mark_prices(s, acct.id))
                settled.append((tx.id, tx.asset, tx.status, tx.net_profit, acct.name))
            from .session import session_status
            for aid in {t.account_id for t in txs}:
                self._drift_guard(s, s.get(Account, aid))
                acct = s.get(Account, aid)
                ss = session_status(s, acct)
                if ss["active"] and ss["state"] in ("stop_loss_hit", "take_profit_hit") and not acct.halted_reason:
                    label = "Stop loss hit" if ss["state"] == "stop_loss_hit" else "Take profit hit"
                    acct.halted_reason = f"{label}: session P&L {ss['realized_pnl']:+.2f}"
                    acct.session_end_reason = label.lower()
                    record_event("loss_limit" if ss["state"] == "stop_loss_hit" else "trade_settled",
                                 f"{acct.name}: {acct.halted_reason} — bot stopped", level="WARNING",
                                 data={"account_id": acct.id, "session": ss}, persist=False)
        if live_wins and self.live_armed:
            cond, wkey = live_wins
            t = asyncio.run_coroutine_threadsafe(self.live.redeem(cond, wkey), self.loop) if self.loop else None
        for txid, asset, status, pnl, name in settled:
            record_event("trade_settled", f"{asset} {txid} {status.upper()} {pnl:+.4f} USD ({name})",
                         data={"tx": txid, "status": status, "net_profit": pnl})

    async def cancel_market(self, market_id: int, reason: str) -> None:
        def _do():
            with db_write_lock, session_scope() as s:
                for tx in s.scalars(select(Transaction).where(Transaction.market_id == market_id,
                                                              Transaction.status.in_(("filled", "partially_filled")))):
                    acct = s.get(Account, tx.account_id)
                    payout = round(tx.filled_shares * 0.5, 6)  # 50/50 resolution pays $0.50 per share
                    tx.gross_payout = payout
                    tx.net_profit = round(payout - tx.total_cost, 6)
                    tx.roi = tx.net_profit / tx.total_cost if tx.total_cost else None
                    tx.status = "cancelled"
                    tx.settlement_outcome = "SPLIT"
                    tx.settled_ts = now_ms()
                    tx.notes = reason
                    accounting.credit_settlement(s, acct, payout, tx.id, reason)
        await asyncio.to_thread(_do)

    def mark_unresolved(self, older_than_ms: int = 2 * 3600 * 1000) -> None:
        cutoff = now_ms() - older_than_ms
        with db_write_lock, session_scope() as s:
            for tx in s.scalars(select(Transaction).join(Market, Market.id == Transaction.market_id)
                                .where(Transaction.status.in_(("filled", "partially_filled")),
                                       Market.close_ts < cutoff, Market.status != "resolved")).all():
                tx.status = "unresolved"

    # ================================================================ marks
    def mark_prices(self, s, account_id: int) -> dict[str, float]:
        """Best bid for each open position (what it could be sold for now) — an estimate."""
        out = {}
        for tx in accounting.open_positions(s, account_id):
            m = s.get(Market, tx.market_id)
            if not m:
                continue
            tok = m.up_token_id if tx.outcome == "UP" else m.down_token_id
            b = self.collector.channel.books.get(tok)
            out[tx.id] = (b.best_bid or 0.0) if b is not None else 0.0
        return out


def fee_for_market(m: Market) -> FeeSchedule:
    if m.fee_rate is None:
        return FeeSchedule(verified=False)
    return FeeSchedule(rate=m.fee_rate, exponent=m.fee_exponent or 1.0, taker_only=bool(m.fee_taker_only),
                       rebate_rate=m.fee_rebate_rate or 0.0, fee_type=m.fee_type, verified=bool(m.fee_verified))


def _bids_fills(bids, shares: float, min_price: float):
    """Walk the bid side for ``shares`` using only levels >= min_price. None unless fully sellable."""
    left, out = shares, []
    for p, q in bids:
        if p < min_price - 1e-9 or left <= 1e-9:
            break
        take = min(q, left)
        out.append((p, take))
        left -= take
    return out if left <= 1e-6 else None


WHY_LABELS = [
    ("waiting", "Waiting: no market is in your time window right now"),
    ("outside entry window", "Waiting: no market is in your time window right now"),
    ("signal found", "Signal found: order sent"),
    ("holding a position", "Holding a trade in this market: waiting to sell"),
    ("before buying again", "Just sold: short wait before buying again"),
    ("in this market reached", "Max trades in this market reached"),
    ("no prediction yet", "No prediction yet (price data warming up)"),
    ("too small", "Stake too small for Polymarket's 5-share minimum"),
    ("safety margin z none", "Safety margin unknown (price feed not ready)"),
    ("news blackout", "News blackout (weekdays 14:25-14:45)"),
    ("moving fast against", "Price moving fast against our side"),
    ("model edge", "Model edge too small"),
    ("above cap", "Model chance above your cap"),
    ("not enough sellers", "Not enough sellers at your price"),
    ("no sellers", "Not enough sellers at your price"),
    ("order book not ready", "No prices yet"),
    ("no prices", "No prices yet"),
]


def why_category(why: str | None) -> str:
    w = (why or "").lower()
    if "safety margin" in w and "none" not in w:
        return "Safety margin too low: coin too close to the price to beat" if "<" in w else "Safety margin above your maximum"
    if " ask " in w and "outside" in w:
        return "Price outside your range"
    if "model chance" in w and "price+fee" in w:
        return "Model chance too low for the price (no edge after fees)"
    for key, label in WHY_LABELS:
        if label and key in w:
            return label
    import re
    g = re.sub(r"[-+]?\$?\d+(\.\d+)?%?", "…", why or "unknown").strip()   # group same reason with different numbers
    return (g[:1].upper() + g[1:])[:90]
