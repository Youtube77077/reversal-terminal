"use client";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { DataTable, ErrorNote, KV, Panel, Pill, Stat } from "@/components/ui";
import { usePoll } from "@/lib/api";
import { dur, num, pct, pnlClass, price, signedUsd, spot, statusColor, ts, usd } from "@/lib/format";

function Book({ title, b }: { title: string; b: any }) {
  if (!b) return <Panel title={title}><div className="text-2xs text-faint">not recorded</div></Panel>;
  const side = (label: string, bids: any[], asks: any[], color: string) => (
    <div className="min-w-0">
      <div className={`mb-1 text-2xs font-semibold ${color}`}>{label}</div>
      <table className="mono w-full text-2xs">
        <thead><tr className="text-faint"><th className="text-left">bid</th><th className="text-right">size</th><th className="text-right">ask</th><th className="text-right">size</th></tr></thead>
        <tbody>{Array.from({ length: Math.max(bids.length, asks.length, 1) }).slice(0, 10).map((_, i) => (
          <tr key={i}><td className="text-up">{bids[i] ? price(bids[i][0]) : ""}</td><td className="text-right text-dim">{bids[i] ? num(bids[i][1], 1) : ""}</td>
            <td className="text-right text-down">{asks[i] ? price(asks[i][0]) : ""}</td><td className="text-right text-dim">{asks[i] ? num(asks[i][1], 1) : ""}</td></tr>
        ))}</tbody>
      </table>
    </div>
  );
  return (
    <Panel title={title} sub={`server ${ts(b.server_ts)} · exchange ${ts(b.exchange_ts)}`}>
      <div className="grid grid-cols-2 gap-3">{side("UP", b.up_bids, b.up_asks, "text-up")}{side("DOWN", b.down_bids, b.down_asks, "text-down")}</div>
    </Panel>
  );
}

export default function TxDetailPage() {
  return <Suspense><TxDetail /></Suspense>;
}

function TxDetail() {
  const id = useSearchParams().get("id") || "";
  const { data: t, error } = usePoll<any>(`/api/transactions/${id}`, 5000);
  if (error) return <div className="page"><ErrorNote error={error} /></div>;
  if (!t) return <div className="page text-faint">Loading…</div>;
  const snap = t.entry_snapshot || {};
  const pc = t.profit_calculation;
  const mom = snap.momentum || {};
  return (
    <div className="page space-y-3">
      <div className="flex flex-wrap items-center gap-3">
        <Link href="/transactions" className="text-2xs text-dim hover:text-ink">← transactions</Link>
        <h1 className="mono text-lg font-bold">{t.id}</h1>
        <span className={`mono text-sm font-semibold uppercase ${statusColor(t.status)}`}>{t.status}</span>
        <Pill kind="SIMULATED" />
        {t.fee_estimated && <Pill kind="ESTIMATED">FEE ESTIMATED</Pill>}
        <Link href={`/replay?id=${t.market_id}`} className="ml-auto text-2xs text-info hover:underline">replay this market →</Link>
      </div>
      <div className="grid-auto">
        <Stat label="Account / strategy" value={t.account_name} sub={`strategy ${t.strategy_key}`} />
        <Stat label="Asset · outcome" value={<span>{t.asset} <span className={t.outcome === "UP" ? "text-up" : "text-down"}>{t.outcome}</span></span>} sub={`${t.market_duration} · ${t.position}`} />
        <Stat label="Entry price (VWAP)" value={price(t.entry_price)} sub={`decision ask ${price(t.decision_ask)} · limit ${price(t.limit_price)}`} />
        <Stat label="Shares filled" value={num(t.filled_shares, 2)} sub={`requested ${num(t.requested_shares, 2)} · unfilled ${num(t.unfilled_shares, 2)}`} />
        <Stat label="Entry time remaining" value={t.entry_secs_remaining != null ? `T-${t.entry_secs_remaining.toFixed(2)}s` : "—"} />
        <Stat label="Holding duration" value={dur(t.holding_seconds)} />
        <Stat label="Settlement outcome" value={t.settlement_outcome || "pending"} />
        <Stat label="Net profit" value={<span className={pnlClass(t.net_profit)}>{signedUsd(t.net_profit, 4)}</span>} sub={pc.realised ? "realised" : "not realised — awaiting official settlement"} />
      </div>
      <div className="grid grid-cols-1 gap-3 xl:grid-cols-3">
        <Panel title="Profit calculation">
          <KV rows={[
            ["1. Shares", num(t.filled_shares, 4)], ["2. Executable price (VWAP)", price(t.entry_price)],
            ["3. Gross cost", usd(pc.gross_cost, 6)], ["4. Platform trading fee", `${usd(pc.trading_fee, 6)}${t.fee_estimated ? " (estimated)" : ""}`],
            ["5. Slippage (in gross cost)", usd(pc.slippage_included_in_gross, 6)], ["   Spread cost vs mid (in gross)", usd(pc.spread_cost_vs_mid_included_in_gross, 6)],
            ["   Gas fee", `${usd(pc.gas_fee, 6)} (estimated: relayer-paid)`], ["   Network fee", usd(pc.network_fee, 6)],
            ["6. Total investment", usd(pc.total_cost, 6)], ["7. Potential payout", usd(pc.potential_payout, 6)],
            ["8. Gross potential profit", usd((pc.potential_payout ?? 0) - (pc.gross_cost ?? 0), 6)],
            ["9. Net potential profit", usd(pc.potential_net_if_win, 6)],
            ["10. Actual settlement payout", pc.actual_payout != null ? usd(pc.actual_payout, 6) : "pending"],
            ["11. Actual net P&L", pc.net_profit != null ? signedUsd(pc.net_profit, 6) : "pending"], ["ROI", pct(pc.roi)],
          ]} />
        </Panel>
        <Panel title="Execution details">
          <KV rows={[
            ["Order type / TIF", `${t.order?.order_type} / ${t.order?.tif}`], ["Order status", t.order?.status],
            ["Decision time", ts(t.order?.decision_ts)], ["Executed time", ts(t.order?.executed_ts)],
            ["Simulated latency", t.order?.executed_ts ? `${t.order.executed_ts - t.order.decision_ts} ms` : "—"],
            ["Reserved at submission", usd(t.order?.reserved_amount, 6)], ["Failure / note", t.order?.failure_reason || t.notes || "—"],
            ["Signal", t.signal ? `#${t.signal.id} ${t.signal.decision}` : "—"], ["Experiment", t.experiment_id || "—"],
          ]} />
          <div className="mt-3"><DataTable rows={t.fills} empty="No fills (order not executed)." cols={[
            { key: "ts", label: "Fill time", render: (r: any) => ts(r.ts) }, { key: "price", label: "Price", render: (r: any) => price(r.price) },
            { key: "shares", label: "Shares", render: (r: any) => num(r.shares, 2) }, { key: "notional", label: "Notional", render: (r: any) => usd(r.notional, 4) },
            { key: "fee", label: "Fee", render: (r: any) => usd(r.fee, 5) }, { key: "role", label: "Role", align: "center" },
          ]} /></div>
        </Panel>
        <Panel title="Entry market snapshot (what the bot knew)">
          <KV rows={[
            ["Market", t.market?.slug], ["Settles", ts(t.market?.close_ts)],
            ["Favourite", `${snap.favourite} ${pct(snap.fav_prob)}`], ["UP bid/ask", `${price(snap.up?.bid)} / ${price(snap.up?.ask)}`],
            ["DOWN bid/ask", `${price(snap.down?.bid)} / ${price(snap.down?.ask)}`],
            ["Underlying spot", `${spot(snap.spot)} (${snap.spot_source})`], ["Settlement threshold", spot(snap.open_price)],
            ["Distance", snap.dist_bps != null ? `${spot(snap.dist_abs)} (${num(snap.dist_bps, 2)} bp)` : "—"],
            ["Est. 60s TWAP", spot(snap.twap60_est)],
            ["Momentum 1/3/5s", `${num(mom.mom_1s, 4)} / ${num(mom.mom_3s, 4)} / ${num(mom.mom_5s, 4)}`],
            ["Momentum 10/30/60s", `${num(mom.mom_10s, 4)} / ${num(mom.mom_30s, 4)} / ${num(mom.mom_60s, 4)}`],
            ["Vol 30s (bp/s) · accel", `${num(snap.vol_30s, 3)} · ${num(snap.accel, 4)}`],
            ["Fee schedule", `rate ${snap.fee?.rate} exp ${snap.fee?.exponent} ${snap.fee?.verified ? "verified" : "ESTIMATED"}`],
            ["Final result", t.market?.winner ? `${t.market.winner} won (settle ref ${spot(t.market.close_price)})` : "pending"],
          ]} />
        </Panel>
      </div>
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        <Book title="Order book at decision" b={t.books?.decision} />
        <Book title="Order book at execution (after latency)" b={t.books?.execution} />
      </div>
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        <Panel title="Fees & costs (itemised)">
          <DataTable rows={t.fees} cols={[{ key: "kind", label: "Kind" }, { key: "amount", label: "Amount", render: (r: any) => usd(r.amount, 6) },
            { key: "estimated", label: "Estimated", align: "center", render: (r: any) => r.estimated ? <span className="text-warn">yes</span> : "no" },
            { key: "formula", label: "Basis", align: "left", render: (r: any) => <span className="text-2xs text-dim">{r.formula}</span> }]} />
        </Panel>
        <Panel title="Ledger entries">
          <DataTable rows={t.ledger} cols={[{ key: "ts", label: "Time", render: (r: any) => ts(r.ts) }, { key: "kind", label: "Kind", align: "left" },
            { key: "amount", label: "Amount", render: (r: any) => signedUsd(r.amount, 6) }, { key: "cash_after", label: "Avail after", render: (r: any) => usd(r.cash_after, 4) },
            { key: "note", label: "Note", align: "left", render: (r: any) => <span className="text-2xs text-dim">{r.note}</span> }]} />
        </Panel>
      </div>
      {t.signal?.detail_json && null}
    </div>
  );
}
