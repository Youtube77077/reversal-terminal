"use client";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import AssetNav, { Verdict } from "@/components/AssetNav";
import { RateBars, TimeChart } from "@/components/Chart";
import Drill from "@/components/Drill";
import { DataTable, ErrorNote, Panel, Rate, SectionNote, Stat, Tabs } from "@/components/ui";
import { usePoll } from "@/lib/api";
import { int, isNum, num, pct, pnlClass, price, signedUsd, usd } from "@/lib/format";
import { useLive } from "@/lib/live";
import AssetCard from "@/components/AssetCard";

const NAMES: Record<string, string> = { BTC: "Bitcoin", ETH: "Ethereum", SOL: "Solana", XRP: "XRP", DOGE: "Dogecoin", HYPE: "Hyperliquid", BNB: "BNB" };

const pnlCols = (label: string, fmt?: (g: any) => string) => [
  { key: "group", label, align: "left" as const, render: (r: any) => (fmt ? fmt(r.group) : String(r.group)) },
  { key: "trades", label: "Trades" }, { key: "wins", label: "W" }, { key: "losses", label: "L" },
  { key: "win_rate", label: "Win rate", render: (r: any) => <Rate rate={r.win_rate} n={r.trades} lo={r.win_ci_low} hi={r.win_ci_high} flag={r.sample} /> },
  { key: "breakeven_win_rate", label: "Break-even", render: (r: any) => pct(r.breakeven_win_rate) },
  { key: "avg_entry", label: "Avg entry", render: (r: any) => price(r.avg_entry) },
  { key: "net_pnl", label: "Net P&L", render: (r: any) => <span className={pnlClass(r.net_pnl)}>{signedUsd(r.net_pnl, 4)}</span> },
  { key: "gross_profit", label: "Gross +", render: (r: any) => usd(r.gross_profit, 4) },
  { key: "gross_loss", label: "Gross −", render: (r: any) => usd(r.gross_loss, 4) },
  { key: "fees", label: "Fees", render: (r: any) => usd(r.fees, 4) },
  { key: "roi", label: "ROI", render: (r: any) => <span className={pnlClass(r.roi)}>{pct(r.roi, 1)}</span> },
  { key: "ev_per_trade", label: "EV/trade [95% CI]", render: (r: any) => `${num(r.ev_per_trade, 4)}${isNum(r.ev_ci_low) ? ` [${num(r.ev_ci_low, 3)}, ${num(r.ev_ci_high, 3)}]` : ""}` },
  { key: "verdict", label: "Verdict", align: "center" as const, render: (r: any) => <Verdict v={r.verdict} /> },
];

const researchCols = (k: string, label: string) => [
  { key: k, label, align: "left" as const, render: (r: any) => (k === "t_minus" ? `T-${r.t_minus}` : r[k]) },
  { key: "resolved", label: "n" }, { key: "reversals", label: "Rev." },
  { key: "reversal_rate", label: "Reversal %", render: (r: any) => <Rate rate={r.reversal_rate} n={r.resolved} lo={r.reversal_ci_low} hi={r.reversal_ci_high} flag={r.sample} /> },
  { key: "implied_fav_prob", label: "Implied fav", render: (r: any) => pct(r.implied_fav_prob) },
  { key: "calibration_error", label: "Calib err", render: (r: any) => pct(r.calibration_error) },
  { key: "brier", label: "Brier", render: (r: any) => num(r.brier, 4) },
  { key: "executable", label: "Exec." }, { key: "insufficient_liquidity", label: "Thin" },
  { key: "avg_entry_price", label: "Avg ask", render: (r: any) => price(r.avg_entry_price) },
  { key: "avg_liquidity_usd", label: "Liq $", render: (r: any) => num(r.avg_liquidity_usd, 1) },
  { key: "avg_abs_dist_bps", label: "|dist| bp", render: (r: any) => num(r.avg_abs_dist_bps, 2) },
  { key: "theoretical_ev_per_share", label: "Theo EV", render: (r: any) => num(r.theoretical_ev_per_share, 4) },
  { key: "realistic_ev_per_share", label: "Real EV [CI]", render: (r: any) => (
    <span className="inline-flex flex-col items-end leading-tight"><span className={(r.realistic_ev_per_share ?? 0) > 0 ? "text-up" : "text-down"}>{num(r.realistic_ev_per_share, 4)}</span>
      <span className="text-2xs text-faint">{isNum(r.realistic_ev_ci_low) ? `[${num(r.realistic_ev_ci_low, 3)}, ${num(r.realistic_ev_ci_high, 3)}]` : ""}</span></span>) },
  { key: "p_value_vs_breakeven", label: "p", render: (r: any) => num(r.p_value_vs_breakeven, 3) },
];

export default function AssetAnalyticsPage() {
  return <Suspense><AssetAnalytics /></Suspense>;
}

function AssetAnalytics() {
  const asset = useSearchParams().get("s") || "BTC";
  const A = (asset || "").toUpperCase();
  const { data: d, error } = usePoll<any>(`/api/analytics/asset/${A}`, 20000);
  const { tick } = useLive();
  const [tab, setTab] = useState("pnl");
  const [drill, setDrill] = useState<any>(null);
  const t = d?.trading || {};
  const m = d?.market_stats || {};
  return (
    <div className="page space-y-3">
      <AssetNav />
      <ErrorNote error={error} />
      <div className="grid grid-cols-1 gap-3 xl:grid-cols-[340px_1fr]">
        <AssetCard asset={A} name={NAMES[A]} state={tick?.assets?.[A]} status={tick?.asset_status?.[A]?.status} detail={tick?.asset_status?.[A]?.detail} />
        <Panel title={`${A} · ${NAMES[A] || ""} — profitability summary`} right={<Verdict v={t.verdict} />}
          sub="Simulated paper trading on real order books. Realised only; open positions excluded.">
          <div className="grid-auto">
            <Stat label="Net P&L (realised)" value={<span className={pnlClass(t.net_pnl)}>{signedUsd(t.net_pnl, 4)}</span>} />
            <Stat label="ROI" value={<span className={pnlClass(t.roi)}>{pct(t.roi)}</span>} sub={`invested ${usd(t.invested, 2)}`} />
            <div className="rounded border border-line bg-panel2/60 px-3 py-2"><div className="label">Win rate</div><Rate rate={t.win_rate} n={t.settled} lo={t.win_ci_low} hi={t.win_ci_high} flag={t.sample} /></div>
            <Stat label="Break-even win rate" value={pct(t.breakeven_win_rate)} sub="incl. fees" tone="warn" />
            <Stat label="EV per trade" value={num(t.ev_per_trade, 4)} sub={isNum(t.ev_ci_low) ? `95% CI [${num(t.ev_ci_low, 3)}, ${num(t.ev_ci_high, 3)}]` : "need ≥2 trades"} />
            <Stat label="p-value vs break-even" value={num(t.p_value_vs_breakeven, 3)} tone={(t.p_value_vs_breakeven ?? 1) < 0.05 ? "up" : "dim"} />
            <Stat label="Trades / orders" value={`${int(t.trades)} / ${int(t.orders)}`} sub={`fill rate ${pct(t.fill_rate, 0)} · partial ${pct(t.partial_fill_rate, 0)}`} />
            <Stat label="Wins / losses" value={`${int(t.wins)} / ${int(t.losses)}`} sub={`${int(t.open)} open`} />
            <Stat label="Gross profit" value={usd(t.gross_profit, 4)} tone="up" />
            <Stat label="Gross loss" value={usd(t.gross_loss, 4)} tone="down" />
            <Stat label="Fees paid" value={usd(t.fees, 4)} sub="estimated per formula" />
            <Stat label="Slippage" value={usd(t.slippage, 4)} />
            <Stat label="Max drawdown" value={usd(t.max_drawdown, 4)} tone="warn" />
            <Stat label="Best / worst trade" value={`${signedUsd(t.best_trade, 3)} / ${signedUsd(t.worst_trade, 3)}`} />
            <Stat label="Avg entry price" value={price(t.avg_entry_price)} />
            <Stat label="Avg holding" value={isNum(t.avg_holding_s) ? `${num(t.avg_holding_s, 0)}s` : "—"} />
          </div>
        </Panel>
      </div>
      <Panel title={`${A} market statistics`}>
        <div className="grid-auto">
          <Stat label="Markets observed" value={int(m.markets)} sub={`${int(m.resolved)} resolved`} />
          <div className="rounded border border-line bg-panel2/60 px-3 py-2"><div className="label">UP resolution rate</div><Rate rate={m.up_win_rate?.rate} n={m.up_win_rate?.n} lo={m.up_win_rate?.ci_low} hi={m.up_win_rate?.ci_high} flag={m.up_win_rate?.sample} /></div>
          <Stat label="Avg |settle move|" value={isNum(m.avg_abs_move_bps) ? `${num(m.avg_abs_move_bps, 2)} bp` : "—"} sub="open → close reference" />
          <Stat label="Realised vol (30s)" value={isNum(m.avg_vol_30s_bps) ? `${num(m.avg_vol_30s_bps, 3)} bp/s` : "—"} />
          <Stat label="Avg spread UP / DOWN" value={`${price(m.avg_up_spread)} / ${price(m.avg_down_spread)}`} />
          <Stat label="Avg top-5 ask liquidity" value={usd(m.avg_top5_ask_liquidity_usd, 0)} />
          <Stat label="Shares traded / s" value={num(m.avg_shares_traded_per_s, 2)} />
          <Stat label="Observations" value={int(m.observations)} sub={`book ${pct(m.book_coverage, 1)} · spot ${pct(m.spot_coverage, 1)}`} />
          <Stat label="Missing seconds" value={int(m.missing_seconds)} tone={m.missing_seconds ? "warn" : undefined} />
        </div>
      </Panel>
      <Panel pad={false}>
        <div className="px-3 pt-2"><Tabs value={tab} onChange={setTab} tabs={[
          { key: "pnl", label: "P&L breakdowns" }, { key: "strategies", label: "By strategy" }, { key: "profit", label: "What's profitable" },
          { key: "intervals", label: "Time intervals" }, { key: "prob", label: "Probability buckets" }, { key: "types", label: "Reversal types" },
          { key: "calibration", label: "Calibration" }, { key: "context", label: "Distance & momentum" },
        ]} /></div>
        <div className="space-y-3 p-3">
          {!d ? <div className="text-faint">Loading…</div> : (<>
            {tab === "pnl" && (<>
              <TimeChart title={`${A}_cum_pnl`} height={200} ranges series={[{ name: "cumulative realised P&L", color: "#a3e635", type: "area",
                data: d.equity_curve.map((p: any) => ({ time: p.ts, value: p.cum_pnl })) }]} />
              <div className="label">By entry price</div><DataTable exportName={`${A}_pnl_by_price`} rows={d.pnl_by_entry_price} cols={pnlCols("Entry price")} />
              <div className="label">By entry time remaining</div><DataTable exportName={`${A}_pnl_by_time`} rows={d.pnl_by_entry_time} cols={pnlCols("Entry window")} />
              <div className="label">By favourite probability at entry</div><DataTable exportName={`${A}_pnl_by_prob`} rows={d.pnl_by_fav_prob} cols={pnlCols("Fav prob")} />
              <div className="label">By settlement distance at entry</div><DataTable exportName={`${A}_pnl_by_dist`} rows={d.pnl_by_distance} cols={pnlCols("Distance")} />
              <div className="label">By momentum at entry</div><DataTable exportName={`${A}_pnl_by_mom`} rows={d.pnl_by_momentum} cols={pnlCols("Momentum")} />
              <div className="label">By side bought</div><DataTable exportName={`${A}_pnl_by_side`} rows={d.pnl_by_side} cols={pnlCols("Side")} />
              <div className="label">By hour of day (UTC)</div><DataTable exportName={`${A}_pnl_by_hour`} rows={d.pnl_by_hour_utc} cols={pnlCols("Hour", (g) => `${String(g).padStart(2, "0")}:00`)} />
              <div className="label">By weekday (UTC)</div><DataTable exportName={`${A}_pnl_by_weekday`} rows={d.pnl_by_weekday_utc} cols={pnlCols("Day")} />
            </>)}
            {tab === "strategies" && (
              <DataTable exportName={`${A}_by_strategy`} rows={d.pnl_by_strategy} cols={[
                { key: "account", label: "Account", align: "left" }, { key: "trades", label: "Trades" }, { key: "wins", label: "W" }, { key: "losses", label: "L" },
                { key: "win_rate", label: "Win rate", render: (r: any) => <Rate rate={r.win_rate} n={r.settled} lo={r.win_ci_low} hi={r.win_ci_high} flag={r.sample} /> },
                { key: "breakeven_win_rate", label: "Break-even", render: (r: any) => pct(r.breakeven_win_rate) },
                { key: "net_pnl", label: "Net P&L", render: (r: any) => <span className={pnlClass(r.net_pnl)}>{signedUsd(r.net_pnl, 4)}</span> },
                { key: "fees", label: "Fees", render: (r: any) => usd(r.fees, 4) }, { key: "roi", label: "ROI", render: (r: any) => pct(r.roi, 1) },
                { key: "max_drawdown", label: "Max DD", render: (r: any) => usd(r.max_drawdown, 4) },
                { key: "ev_per_trade", label: "EV/trade [CI]", render: (r: any) => `${num(r.ev_per_trade, 4)}${isNum(r.ev_ci_low) ? ` [${num(r.ev_ci_low, 3)}, ${num(r.ev_ci_high, 3)}]` : ""}` },
                { key: "verdict", label: "Verdict", align: "center", render: (r: any) => <Verdict v={r.verdict} /> },
              ]} />
            )}
            {tab === "profit" && (<>
              <SectionNote>Every (checkpoint × entry price) cell for {A}, ranked by the LOWER 95% bound of realistic EV per share. Only cells marked PROFITABLE have a confidence interval entirely above zero — and with many cells tested, confirm them out-of-sample before trusting them.</SectionNote>
              <DataTable exportName={`${A}_profit_cells`} rows={d.profit_cells} onRow={(r) => setDrill({ asset: A, t_minus: r.t_minus, price_bucket: r.price_bucket })} cols={[
                { key: "t_minus", label: "T-", render: (r: any) => `T-${r.t_minus}` }, { key: "price_bucket", label: "Entry price", align: "left" },
                ...researchCols("price_bucket", "").slice(1), { key: "verdict", label: "Verdict", align: "center", render: (r: any) => <Verdict v={r.verdict} /> },
              ]} />
            </>)}
            {tab === "intervals" && (<>
              <RateBars label={`${A} probability-reversal rate by checkpoint`} rows={d.intervals.map((r: any) => ({ x: `T-${r.t_minus}`, rate: r.reversal_rate ?? null, lo: r.reversal_ci_low, hi: r.reversal_ci_high, n: r.resolved }))} />
              <DataTable exportName={`${A}_intervals`} rows={d.intervals} cols={researchCols("t_minus", "Interval")} onRow={(r) => setDrill({ asset: A, t_minus: r.t_minus })} rowClass={(r) => (r.key ? "bg-accent/5" : undefined)} />
            </>)}
            {tab === "prob" && <DataTable exportName={`${A}_prob`} rows={d.by_prob_bucket} cols={[{ key: "t_minus", label: "T-", render: (r: any) => `T-${r.t_minus}` }, ...researchCols("prob_bucket", "Fav prob")]} onRow={(r) => setDrill({ asset: A, t_minus: r.t_minus, prob_bucket: r.prob_bucket })} />}
            {tab === "types" && <DataTable exportName={`${A}_types`} rows={d.event_types} cols={[
              { key: "t_minus", label: "Interval", align: "left", render: (r: any) => `T-${r.t_minus}` },
              ...(["probability_reversal", "price_crossover", "underlying_reversal", "settlement_reversal"]).map((k) => ({ key: k, label: k.replace(/_/g, " "),
                render: (r: any) => <Rate rate={r[k]?.rate} n={r[k]?.n} lo={r[k]?.ci_low} hi={r[k]?.ci_high} flag={r[k]?.sample} /> }))]} />}
            {tab === "calibration" && (<>
              <RateBars label="actual favourite win rate by implied bin" rows={d.calibration.map((c: any) => ({ x: c.bin, rate: c.actual, lo: c.ci_low, hi: c.ci_high, n: c.n }))} />
              <DataTable rows={d.calibration} cols={[{ key: "bin", label: "Implied", align: "left" }, { key: "implied", label: "Mean implied", render: (r: any) => pct(r.implied) },
                { key: "actual", label: "Actual", render: (r: any) => <Rate rate={r.actual} n={r.n} lo={r.ci_low} hi={r.ci_high} /> }]} />
            </>)}
            {tab === "context" && (<>
              <div className="label">By settlement distance</div><DataTable rows={d.distance} cols={[{ key: "t_minus", label: "T-", render: (r: any) => `T-${r.t_minus}` }, ...researchCols("dist_bucket", "Distance")]} />
              <div className="label">By momentum direction</div><DataTable rows={d.momentum} cols={[{ key: "t_minus", label: "T-", render: (r: any) => `T-${r.t_minus}` }, ...researchCols("momentum_dir", "Momentum")]} />
            </>)}
          </>)}
        </div>
      </Panel>
      <Drill filter={drill} onClose={() => setDrill(null)} />
    </div>
  );
}
