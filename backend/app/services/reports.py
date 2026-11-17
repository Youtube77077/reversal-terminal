"""Experiment report generator (HTML + CSV)."""
from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from pathlib import Path

from ..config import get_settings
from ..constants import ASSETS, KEY_CHECKPOINTS, MIN_SAMPLE_SOLID
from ..db import now_ms, session_scope
from ..models import Experiment, ExperimentReport
from . import analytics
from .collector import db_write_lock


def _fmt(v, kind: str = "num") -> str:
    if v is None:
        return "—"
    if kind == "pct":
        return f"{v * 100:.2f}%"
    if kind == "usd":
        return f"${v:,.4f}"
    if isinstance(v, float):
        return f"{v:,.4f}"
    return html.escape(str(v))


def _table(rows: list[dict], cols: list[tuple[str, str, str]]) -> str:
    if not rows:
        return "<p class='muted'>No resolved data in this window.</p>"
    h = "".join(f"<th>{html.escape(lbl)}</th>" for _, lbl, _ in cols)
    body = ""
    for r in rows:
        body += "<tr>" + "".join(f"<td>{_fmt(r.get(k), kind)}</td>" for k, _, kind in cols) + "</tr>"
    return f"<table><thead><tr>{h}</tr></thead><tbody>{body}</tbody></table>"


RATE_COLS = [("resolved", "n", "num"), ("reversals", "reversals", "num"), ("reversal_rate", "rate", "pct"),
             ("reversal_ci_low", "95% CI low", "pct"), ("reversal_ci_high", "95% CI high", "pct"),
             ("avg_entry_price", "avg ask", "num"), ("realistic_ev_per_share", "real EV/share", "num"),
             ("sample", "sample", "str")]


def build_summary(e: Experiment) -> dict:
    end = e.completed_ts or now_ms()
    perf = analytics.strategy_comparison(e.id)
    traded = [p for p in perf if p.get("trades")]
    tx = analytics.transactions_df(e.id)
    settled = tx[tx["status"].isin(["won", "lost"])] if not tx.empty else tx
    wins = int((settled["status"] == "won").sum()) if not tx.empty else 0
    n = int(len(settled)) if not tx.empty else 0
    gross = float(settled["net_profit"].sum()) if n else 0.0
    fees = float(tx["trading_fee"].sum()) if not tx.empty else 0.0
    slip = float(tx["slippage"].sum()) if not tx.empty else 0.0
    invested = float(settled["total_cost"].sum()) if n else 0.0
    intervals = analytics.interval_table(None, "live", e.started_ts, end)
    scanner = analytics.scanner(None, "live", e.started_ts, end)
    br = analytics.breakdowns(None, "live", e.started_ts, end)
    per_asset = []
    for a in ASSETS:
        for t in KEY_CHECKPOINTS:
            rows = [r for r in analytics.interval_table(a, "live", e.started_ts, end) if r["t_minus"] == t]
            if rows:
                r = rows[0]
                r["asset"] = a
                per_asset.append(r)
    best = max(traded, key=lambda p: p.get("net_pnl") or 0) if traded else None
    worst = min(traded, key=lambda p: p.get("net_pnl") or 0) if traded else None

    # ---------------- conclusions (conservative, rule-based)
    key_rows = [r for r in intervals if r["t_minus"] in KEY_CHECKPOINTS and r.get("resolved")]
    pos_ev = [r for r in key_rows if (r.get("realistic_ev_ci_low") or -1) > 0]
    sig = [r for r in key_rows if (r.get("p_value_vs_breakeven") or 1) < 0.05]
    sample_ok = all((r.get("resolved") or 0) >= MIN_SAMPLE_SOLID for r in key_rows) and bool(key_rows)
    asset_pos = {r["asset"] for r in per_asset if (r.get("realistic_ev_per_share") or -1) > 0 and r.get("resolved")}
    conclusion = {
        "positive_ev_evidence": bool(pos_ev),
        "positive_ev_detail": ("Lower 95% CI of realistic EV > 0 at: " + ", ".join(f"T-{r['t_minus']}" for r in pos_ev))
        if pos_ev else "No key checkpoint has a realistic-EV confidence interval entirely above zero.",
        "sample_sufficient": sample_ok,
        "sample_detail": f"Key checkpoints need >= {MIN_SAMPLE_SOLID} resolved observations each; have " +
                         ", ".join(f"T-{r['t_minus']}: {r.get('resolved', 0)}" for r in key_rows),
        "statistically_significant": bool(sig),
        "significance_detail": ("One-sided binomial test p<0.05 vs fee-adjusted break-even at: " +
                                ", ".join(f"T-{r['t_minus']}" for r in sig)) if sig else
                               "No key checkpoint beats the fee-adjusted break-even at p<0.05.",
        "survives_fees": bool(pos_ev),
        "survives_conservative_slippage": bool([r for r in pos_ev if (r.get("realistic_ev_ci_low") or 0) > 0.01]),
        "consistent_across_assets": len(asset_pos) >= 5,
        "consistency_detail": f"{len(asset_pos)}/7 assets show positive point-estimate realistic EV at a key checkpoint",
        "more_testing_needed": not (sample_ok and pos_ev and sig),
        "notes": [
            "Settlement uses a 60-second Chainlink TWAP, which dampens last-second price moves; late reversals "
            "require the TWAP (not just spot) to cross the opening reference.",
            "Point estimates without adequate samples are not evidence; see confidence intervals.",
        ],
    }
    return {
        "experiment": {"id": e.id, "name": e.name, "status": e.status, "started_ts": e.started_ts,
                       "ended_ts": end, "duration_hours": (end - e.started_ts) / 3_600_000,
                       "assets": json.loads(e.assets_json), "config": json.loads(e.config_json)},
        "executive": {
            "markets_resolved": scanner["totals"]["resolved"], "observations": e.observation_count,
            "signals": e.signal_count, "simulated_trades": int((tx["filled_shares"] > 0).sum()) if not tx.empty else 0,
            "wins": wins, "losses": n - wins, "win_rate": (wins / n) if n else None,
            "starting_balance": e.starting_balance, "ending_balance": e.ending_balance,
            "gross_pnl": gross + fees, "fees": fees, "slippage": slip, "net_pnl": gross,
            "roi": (gross / invested) if invested else None,
        },
        "intervals": intervals, "per_asset_key": per_asset,
        "by_prob_bucket": scanner["by_prob_bucket"], "by_price_bucket": scanner["by_price_bucket"],
        "by_distance": br.get("distance", []), "by_momentum": br.get("momentum", []),
        "strategies": perf, "best_strategy": best, "worst_strategy": worst, "conclusion": conclusion,
    }


def render_html(sm: dict) -> str:
    ex, exe, c = sm["experiment"], sm["executive"], sm["conclusion"]
    ts = lambda ms: datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    strat_cols = [("account", "account", "str"), ("trades", "trades", "num"), ("wins", "W", "num"),
                  ("losses", "L", "num"), ("win_rate", "win rate", "pct"), ("win_ci_low", "CI low", "pct"),
                  ("win_ci_high", "CI high", "pct"), ("net_pnl", "net P&L", "usd"), ("fees", "fees", "usd"),
                  ("max_drawdown", "max DD", "usd"), ("ev_per_trade", "EV/trade", "usd"), ("sample", "sample", "str")]
    yes = lambda b: "<b class='g'>YES</b>" if b else "<b class='r'>NO</b>"
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>Report {html.escape(ex['id'])}</title>
<style>body{{background:#0b0c0e;color:#d7dbe0;font:13px/1.5 'JetBrains Mono',Consolas,monospace;margin:32px;max-width:1200px}}
h1,h2{{font-family:Inter,system-ui,sans-serif;color:#fff}}h2{{border-bottom:1px solid #26292e;padding-bottom:6px;margin-top:36px}}
table{{border-collapse:collapse;width:100%;margin:8px 0}}td,th{{border:1px solid #23262b;padding:4px 8px;text-align:right}}
th{{background:#15171a;color:#9aa3ad;font-weight:500}}td:first-child,th:first-child{{text-align:left}}
.muted{{color:#7a828c}}.g{{color:#22c55e}}.r{{color:#ef4444}}.a{{color:#f59e0b}}.kv td{{text-align:left}}</style></head><body>
<h1>REVERSAL TERMINAL — Experiment Report</h1>
<p class="muted">{html.escape(ex['id'])} · {html.escape(ex['name'])} · {ts(ex['started_ts'])} → {ts(ex['ended_ts'])}
 ({ex['duration_hours']:.2f} h) · status {html.escape(ex['status'])} · PAPER / SIMULATED results</p>
<h2>Executive summary</h2><table class="kv">
<tr><td>Assets</td><td>{', '.join(ex['assets'])}</td></tr>
<tr><td>Markets resolved (checkpoints)</td><td>{exe['markets_resolved']}</td></tr>
<tr><td>Observations</td><td>{exe['observations']}</td></tr><tr><td>Signals</td><td>{exe['signals']}</td></tr>
<tr><td>Simulated trades (filled)</td><td>{exe['simulated_trades']}</td></tr>
<tr><td>Wins / Losses</td><td>{exe['wins']} / {exe['losses']} ({_fmt(exe['win_rate'], 'pct')})</td></tr>
<tr><td>Starting → ending balance</td><td>{_fmt(exe['starting_balance'], 'usd')} → {_fmt(exe['ending_balance'], 'usd')}</td></tr>
<tr><td>Gross P&L (before fees)</td><td>{_fmt(exe['gross_pnl'], 'usd')}</td></tr>
<tr><td>Trading fees</td><td>{_fmt(exe['fees'], 'usd')}</td></tr>
<tr><td>Slippage (embedded in cost)</td><td>{_fmt(exe['slippage'], 'usd')}</td></tr>
<tr><td>Net P&L (realised)</td><td>{_fmt(exe['net_pnl'], 'usd')}</td></tr><tr><td>ROI</td><td>{_fmt(exe['roi'], 'pct')}</td></tr></table>
<h2>Conclusion</h2><table class="kv">
<tr><td>Evidence of positive expected value?</td><td>{yes(c['positive_ev_evidence'])} — {html.escape(c['positive_ev_detail'])}</td></tr>
<tr><td>Sample size sufficient?</td><td>{yes(c['sample_sufficient'])} — {html.escape(c['sample_detail'])}</td></tr>
<tr><td>Statistically significant?</td><td>{yes(c['statistically_significant'])} — {html.escape(c['significance_detail'])}</td></tr>
<tr><td>Survives realistic fees?</td><td>{yes(c['survives_fees'])}</td></tr>
<tr><td>Survives conservative slippage (+1c)?</td><td>{yes(c['survives_conservative_slippage'])}</td></tr>
<tr><td>Consistent across assets?</td><td>{yes(c['consistent_across_assets'])} — {html.escape(c['consistency_detail'])}</td></tr>
<tr><td>Additional testing necessary?</td><td>{yes(c['more_testing_needed'])}</td></tr></table>
<ul>{''.join(f'<li class="muted">{html.escape(n)}</li>' for n in c['notes'])}</ul>
<h2>Reversal frequency by time interval</h2>{_table(sm['intervals'], [('t_minus','T-',"num")] + RATE_COLS)}
<h2>Reversal frequency per asset (key checkpoints)</h2>{_table(sm['per_asset_key'], [('asset','asset','str'),('t_minus','T-','num')] + RATE_COLS)}
<h2>By favourite probability bucket</h2>{_table(sm['by_prob_bucket'], [('t_minus','T-','num'),('prob_bucket','bucket','str')] + RATE_COLS)}
<h2>By entry price</h2>{_table(sm['by_price_bucket'], [('t_minus','T-','num'),('price_bucket','bucket','str')] + RATE_COLS)}
<h2>By settlement distance</h2>{_table(sm['by_distance'], [('t_minus','T-','num'),('dist_bucket','distance','str')] + RATE_COLS)}
<h2>By momentum direction</h2>{_table(sm['by_momentum'], [('t_minus','T-','num'),('momentum_dir','momentum','str')] + RATE_COLS)}
<h2>Strategy performance</h2>
<p>Best: <b>{html.escape(str((sm['best_strategy'] or {}).get('account', '—')))}</b> · Worst: <b>{html.escape(str((sm['worst_strategy'] or {}).get('account', '—')))}</b></p>
{_table(sm['strategies'], strat_cols)}
<p class="muted">Generated {ts(now_ms())}. All figures are simulated paper results from real market data; nothing here is investment advice.</p>
</body></html>"""


def generate_report(exp_id: str) -> int:
    import csv

    st = get_settings()
    with session_scope() as s:
        e = s.get(Experiment, exp_id)
        sm = build_summary(e)
    out = Path(st.data_dir) / "reports"
    html_path = out / f"{exp_id}.html"
    csv_path = out / f"{exp_id}_transactions.csv"
    html_path.write_text(render_html(sm), encoding="utf-8")
    tx = analytics.transactions_df(exp_id)
    if tx.empty:
        csv_path.write_text("no transactions\n", encoding="utf-8")
    else:
        tx.drop(columns=["entry_snapshot_json"], errors="ignore").to_csv(csv_path, index=False, quoting=csv.QUOTE_MINIMAL)
    with db_write_lock, session_scope() as s:
        r = ExperimentReport(experiment_id=exp_id, created_ts=now_ms(),
                             summary_json=json.dumps(sm, default=str), html_path=str(html_path), csv_path=str(csv_path))
        s.add(r)
        s.flush()
        return r.id
