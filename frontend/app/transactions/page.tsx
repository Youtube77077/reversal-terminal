"use client";
import { Download } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { Button, DataTable, ErrorNote, Field, inputCls, Panel, Select } from "@/components/ui";
import { qs, usePoll } from "@/lib/api";
import { dur, num, pct, pnlClass, price, signedUsd, statusColor, ts, usd } from "@/lib/format";

const STATUSES = ["", "signal", "pending", "partially_filled", "filled", "won", "lost", "cancelled", "expired", "unresolved"];
const ASSETS = ["", "BTC", "ETH", "SOL", "XRP", "DOGE", "HYPE", "BNB"];
const STRATS = ["", "A", "B", "C", "D", "E", "F", "G", "H", "I", "J"];


function TxInner() {
  const sp = useSearchParams();
  const router = useRouter();
  const [f, setF] = useState<Record<string, string>>({
    asset: "", status: sp.get("status") || "", strategy: "", result: sp.get("result") || "", min_price: "", max_price: "",
    min_secs: "", max_secs: "", start: "", end: "", q: "",
  });
  const set = (k: string) => (v: string) => setF((x) => ({ ...x, [k]: v }));
  const params = { ...f, start: f.start ? new Date(f.start).getTime() : "", end: f.end ? new Date(f.end).getTime() : "", limit: 1000 };
  const { data, error } = usePoll<any>(`/api/transactions${qs(params)}`, 5000);
  const exportUrl = (fmt: string) => `/api/transactions/export${qs({ fmt, asset: f.asset, status: f.status, strategy: f.strategy, result: f.result })}`;
  return (
    <div className="page space-y-3">
      <Panel title="Filters">
        <div className="grid grid-cols-2 gap-2 md:grid-cols-4 xl:grid-cols-11">
          <Field label="Asset"><Select value={f.asset} onChange={set("asset")} options={ASSETS.map((a) => ({ value: a, label: a || "All" }))} /></Field>
          <Field label="Strategy"><Select value={f.strategy} onChange={set("strategy")} options={STRATS.map((a) => ({ value: a, label: a || "All" }))} /></Field>
          <Field label="Status"><Select value={f.status} onChange={set("status")} options={STATUSES.map((a) => ({ value: a, label: a || "All" }))} /></Field>
          <Field label="Result"><Select value={f.result} onChange={set("result")} options={[{ value: "", label: "All" }, { value: "win", label: "Winning" }, { value: "loss", label: "Losing" }]} /></Field>
          <Field label="Entry ≥"><input className={inputCls} value={f.min_price} onChange={(e) => set("min_price")(e.target.value)} placeholder="0.01" /></Field>
          <Field label="Entry ≤"><input className={inputCls} value={f.max_price} onChange={(e) => set("max_price")(e.target.value)} placeholder="0.05" /></Field>
          <Field label="T-remaining ≥ s"><input className={inputCls} value={f.min_secs} onChange={(e) => set("min_secs")(e.target.value)} /></Field>
          <Field label="T-remaining ≤ s"><input className={inputCls} value={f.max_secs} onChange={(e) => set("max_secs")(e.target.value)} /></Field>
          <Field label="From"><input type="datetime-local" className={inputCls} value={f.start} onChange={(e) => set("start")(e.target.value)} /></Field>
          <Field label="To"><input type="datetime-local" className={inputCls} value={f.end} onChange={(e) => set("end")(e.target.value)} /></Field>
          <Field label="Search id"><input className={inputCls} value={f.q} onChange={(e) => set("q")(e.target.value)} placeholder="TX-…" /></Field>
        </div>
      </Panel>
      <Panel title={`Transactions (${data?.total ?? 0})`} sub="Every simulated order is recorded. Payout is never counted as profit before official settlement."
        right={<>
          <a href={exportUrl("csv")}><Button size="sm"><Download size={11} />CSV</Button></a>
          <a href={exportUrl("json")}><Button size="sm"><Download size={11} />JSON</Button></a>
        </>}>
        <ErrorNote error={error} />
        <DataTable rows={data?.rows || []} onRow={(r) => router.push(`/transactions/view/?id=${r.id}`)} maxHeight={720} cols={[
          { key: "id", label: "Tx ID", render: (r) => <span className="mono text-info">{r.id}</span> },
          { key: "created_ts", label: "Timestamp", render: (r) => ts(r.created_ts) },
          { key: "asset", label: "Asset" },
          { key: "market_slug", label: "Market", align: "left", render: (r) => <span className="mono text-2xs text-dim">{r.market_slug}</span> },
          { key: "market_duration", label: "Dur", align: "center" },
          { key: "position", label: "Pos", align: "center" },
          { key: "outcome", label: "UP/DOWN", align: "center", render: (r) => <span className={r.outcome === "UP" ? "text-up" : "text-down"}>{r.outcome}</span> },
          { key: "entry_price", label: "Entry", render: (r) => price(r.entry_price ?? r.limit_price) },
          { key: "filled_shares", label: "Shares", render: (r) => num(r.filled_shares, 2) },
          { key: "requested_shares", label: "Req qty", render: (r) => num(r.requested_shares, 2) },
          { key: "unfilled_shares", label: "Unfilled", render: (r) => num(r.unfilled_shares, 2) },
          { key: "gross_cost", label: "Gross cost", render: (r) => usd(r.gross_cost, 4) },
          { key: "trading_fee", label: "Fee", render: (r) => <span title={r.fee_estimated ? "estimated" : "verified fee schedule"}>{usd(r.trading_fee, 5)}{r.fee_estimated ? "*" : ""}</span> },
          { key: "slippage", label: "Slippage", render: (r) => usd(r.slippage, 4) },
          { key: "total_cost", label: "Total cost", render: (r) => usd(r.total_cost, 4) },
          { key: "settlement_outcome", label: "Settled", align: "center", render: (r) => r.settlement_outcome || "—" },
          { key: "gross_payout", label: "Payout", render: (r) => usd(r.gross_payout, 4) },
          { key: "net_profit", label: "Net P&L", render: (r) => <span className={pnlClass(r.net_profit)}>{signedUsd(r.net_profit, 4)}</span> },
          { key: "roi", label: "ROI", render: (r) => <span className={pnlClass(r.roi)}>{pct(r.roi, 1)}</span> },
          { key: "holding_seconds", label: "Held", render: (r) => dur(r.holding_seconds) },
          { key: "strategy_key", label: "Strat", align: "center", render: (r) => <span title={r.account_name}>{r.strategy_key}</span> },
          { key: "entry_secs_remaining", label: "Entry T-", render: (r) => r.entry_secs_remaining != null ? `${r.entry_secs_remaining.toFixed(1)}s` : "—" },
          { key: "status", label: "Status", align: "center", render: (r) => <span className={statusColor(r.status)}>{r.status}</span> },
        ]} />
        <p className="mt-1 text-2xs text-faint">* fee marked estimated when the market fee schedule could not be verified.</p>
      </Panel>
    </div>
  );
}

export default function TransactionsPage() {
  return <Suspense><TxInner /></Suspense>;
}
