"""Everything you need to judge a bot before giving it real money.

For one account (= one wallet's practice or real bot):
  * every settled trade: predicted chance, decision price vs actual fill price, fees, slippage,
    exit type, price to beat vs our final Chainlink 60s average, official winner
  * summary, worst drawdown, longest losing streak, current streak
  * calibration: predicted win chance vs how often it actually won
  * profit by coin, by entry price, by time left, by exit type
  * skipped signals (near-misses): what the trades it did NOT take would have done
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
from sqlalchemy import text

from ..db import engine


def _f(v):
    if v is None:
        return None
    try:
        v = float(v)
    except (TypeError, ValueError):
        return v
    return None if np.isnan(v) or np.isinf(v) else v


def _group(df: pd.DataFrame, col: str, order: list | None = None) -> list[dict]:
    out = []
    for k, g in df.groupby(col, observed=True):
        out.append({"key": str(k), "trades": int(len(g)), "wins": int((g.net_profit > 0).sum()),
                    "win_rate": _f((g.net_profit > 0).mean()), "pnl": _f(g.net_profit.sum()),
                    "avg_pnl": _f(g.net_profit.mean()), "cost": _f(g.total_cost.sum())})
    if order:
        out.sort(key=lambda r: order.index(r["key"]) if r["key"] in order else 99)
    return out


def report(account_id: int) -> dict:
    tx = pd.read_sql(text("""
        SELECT t.id, t.asset, t.outcome, t.status, t.created_ts, t.entry_ts, t.settled_ts, t.decision_ask, t.limit_price,
               t.entry_price, t.exit_price, t.filled_shares, t.total_cost, t.trading_fee, t.slippage, t.spread_cost,
               t.gross_payout, t.net_profit, t.exit_proceeds, t.settlement_outcome, t.entry_secs_remaining,
               t.predicted_prob, t.entry_snapshot_json, m.price_to_beat, m.final_twap, m.winner, m.slug
        FROM transactions t JOIN markets m ON m.id = t.market_id
        WHERE t.account_id = :a AND t.source = 'live' AND t.status IN ('won','lost')
        ORDER BY t.settled_ts"""), engine, params={"a": account_id})
    open_n = pd.read_sql(text("SELECT COUNT(*) n FROM transactions WHERE account_id=:a AND source='live' "
                              "AND status IN ('filled','partially_filled','pending')"), engine, params={"a": account_id}).n.iloc[0]
    out: dict = {"account_id": account_id, "open_trades": int(open_n), "trades": int(len(tx))}
    if not tx.empty:
        # predicted chance for older trades lives inside the entry snapshot
        def _pp(r):
            if r.predicted_prob == r.predicted_prob and r.predicted_prob is not None:
                return r.predicted_prob
            try:
                e = json.loads(r.entry_snapshot_json or "{}").get("decision", {}).get("expected", {})
                return e.get("model_win_prob") or e.get("hist_win_prob")
            except ValueError:
                return None
        tx["pred"] = tx.apply(_pp, axis=1).astype(float)
        tx["win"] = tx.net_profit > 0
        tx["exit"] = np.where(tx.settlement_outcome == "SOLD", "sold early",
                              np.where(tx.win, "held to end — won", "held to end — lost"))
        bal = tx.net_profit.cumsum()
        dd = float((bal - bal.cummax()).min()) if len(bal) else 0.0
        streak = best_loss = best_win = cur = 0
        for w in tx.win:
            cur = cur + 1 if (w and cur >= 0) else (1 if w else (cur - 1 if cur <= 0 else -1))
            best_loss = min(best_loss, cur)
            best_win = max(best_win, cur)
        streak = cur
        fees = float(tx.trading_fee.sum())
        slip = float(tx.slippage.sum())
        fill_vs_dec = (tx.entry_price - tx.decision_ask).dropna()
        out["summary"] = {
            "wins": int(tx.win.sum()), "losses": int((~tx.win).sum()), "win_rate": _f(tx.win.mean()),
            "pnl": _f(tx.net_profit.sum()), "spent": _f(tx.total_cost.sum()),
            "roi": _f(tx.net_profit.sum() / tx.total_cost.sum()) if tx.total_cost.sum() else None,
            "avg_win": _f(tx[tx.win].net_profit.mean()), "avg_loss": _f(tx[~tx.win].net_profit.mean()),
            "biggest_win": _f(tx.net_profit.max()), "biggest_loss": _f(tx.net_profit.min()),
            "fees": fees, "slippage": slip,
            "avg_fill_minus_decision_price": _f(fill_vs_dec.mean()) if len(fill_vs_dec) else None,
            "fills_worse_than_decision_pct": _f((fill_vs_dec > 1e-9).mean()) if len(fill_vs_dec) else None,
            "max_drawdown": dd, "longest_losing_streak": int(-best_loss), "longest_winning_streak": int(best_win),
            "current_streak": int(streak), "avg_predicted": _f(tx.pred.mean()),
            "first_ts": int(tx.created_ts.min()), "last_ts": int(tx.settled_ts.max() or tx.created_ts.max()),
        }
        out["equity"] = [{"ts": int(t), "pnl": _f(v)} for t, v in zip(tx.settled_ts.fillna(tx.created_ts), bal)]
        # calibration
        c = tx.dropna(subset=["pred"]).copy()
        if len(c):
            c["bin"] = pd.cut(c.pred, [0, .05, .1, .2, .3, .45, .6, .8, .95, 1.0001],
                              labels=["0-5%", "5-10%", "10-20%", "20-30%", "30-45%", "45-60%", "60-80%", "80-95%", "95-100%"])
            out["calibration"] = [{"bin": str(b), "trades": int(len(g)), "predicted": _f(g.pred.mean()),
                                   "actual": _f(g.win.mean())} for b, g in c.groupby("bin", observed=True)]
        tx["price_b"] = pd.cut(tx.decision_ask, [0, .03, .06, .1, .15, .3, .7, .9, .95, 1.0],
                               labels=["<3¢", "3-6¢", "6-10¢", "10-15¢", "15-30¢", "30-70¢", "70-90¢", "90-95¢", "95¢+"])
        tx["secs_b"] = pd.cut(tx.entry_secs_remaining, [-1, 10, 30, 60, 90, 120, 400],
                              labels=["0-10s", "10-30s", "30-60s", "60-90s", "90-120s", "120s+"])
        out["by_coin"] = _group(tx, "asset")
        out["by_price"] = _group(tx, "price_b")
        out["by_time_left"] = _group(tx, "secs_b")
        out["by_exit"] = _group(tx, "exit")
        out["recent"] = [{
            "id": r.id, "asset": r.asset, "side": r.outcome, "ts": int(r.created_ts), "secs_left": _f(r.entry_secs_remaining),
            "predicted": _f(r.pred), "decision_price": _f(r.decision_ask), "fill_price": _f(r.entry_price),
            "exit_price": _f(r.exit_price), "cost": _f(r.total_cost), "fees": _f(r.trading_fee), "pnl": _f(r.net_profit),
            "exit": r.exit, "price_to_beat": _f(r.price_to_beat), "final_twap": _f(r.final_twap), "winner": r.winner,
        } for r in tx.tail(40).iloc[::-1].itertuples()]
    # skipped signals (near-misses)
    cd = pd.read_sql(text("SELECT * FROM strategy_candidates WHERE account_id=:a ORDER BY ts"), engine, params={"a": account_id})
    if not cd.empty:
        sk = cd[~cd.traded.astype(bool)]
        why = sk.reason.fillna("").str.replace(r"[\d.]+%?", "#", regex=True).str.slice(0, 60).value_counts().head(8)
        priced = sk.dropna(subset=["would_pnl_per_dollar"])
        out["skipped"] = {
            "markets_considered": int(len(cd)), "traded": int(cd.traded.astype(bool).sum()), "skipped": int(len(sk)),
            "would_have_won": int((priced.would_pnl_per_dollar > 0).sum()),
            "would_have_pnl_per_dollar_each": _f(priced.would_pnl_per_dollar.sum()),
            "top_reasons": [{"reason": k, "count": int(v)} for k, v in why.items()],
            "near_misses": [{"asset": r.asset, "ts": int(r.ts), "side": r.side, "ask": _f(r.ask), "model": _f(r.model_prob),
                             "edge": _f(r.edge), "reason": r.reason, "winner": r.winner, "would_pnl": _f(r.would_pnl_per_dollar)}
                            for r in sk.sort_values("ts", ascending=False).head(30).itertuples()],
        }
        cc = cd.dropna(subset=["model_prob", "winner"]).copy()
        if len(cc):
            cc["won"] = cc.side == cc.winner
            cc["bin"] = pd.cut(cc.model_prob, [0, .05, .1, .2, .3, .45, .6, .8, 1.0001],
                               labels=["0-5%", "5-10%", "10-20%", "20-30%", "30-45%", "45-60%", "60-80%", "80-100%"])
            out["model_check_all_candidates"] = [{"bin": str(b), "n": int(len(g)), "predicted": _f(g.model_prob.mean()),
                                                  "actual": _f(g.won.mean()), "price": _f(g.ask.mean())}
                                                 for b, g in cc.groupby("bin", observed=True)]
    return out
