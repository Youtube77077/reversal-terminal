"use client";
import { useEffect, useState } from "react";
import { TimeChart } from "@/components/Chart";
import { Button, DataTable, ErrorNote, Field, inputCls, KV, Panel, Rate, SectionNote, Select, Stat, Tabs } from "@/components/ui";
import { post, qs, usePoll } from "@/lib/api";
import { int, isNum, num, pct, pnlClass, price, signedUsd, ts, usd } from "@/lib/format";

export default function StrategyLab() {
  const [tab, setTab] = useState("compare");
  return (
    <div className="page space-y-3">
      <Tabs value={tab} onChange={setTab} tabs={[{ key: "compare", label: "Strategy comparison" }, { key: "backtest", label: "Backtester" },
        { key: "calculator", label: "Profitability calculator" }, { key: "historical", label: "Historical data" }, { key: "catalog", label: "What each strategy does" }]} />
      {tab === "compare" && <Compare />}
      {tab === "backtest" && <Backtest />}
      {tab === "calculator" && <Calculator />}
      {tab === "historical" && <Historical />}
      {tab === "catalog" && <Catalog />}
    </div>
  );
}

function Compare() {
  const { data: exps } = usePoll<any[]>("/api/experiments", 0);
  const [eid, setEid] = useState("");
  const { data, error } = usePoll<any[]>(`/api/strategies/compare${qs({ experiment_id: eid })}`, 10000);
  return (
    <Panel title="Strategy comparison — simulated paper results" sub="Each strategy trades its own account. A more complex strategy is not assumed to be better; compare confidence intervals, not point estimates."
      right={<Select value={eid} onChange={setEid} options={[{ value: "", label: "All time" }, ...(exps || []).map((e) => ({ value: e.id, label: e.id }))]} />}>
      <ErrorNote error={error} />
      <DataTable exportName="strategy_comparison" rows={data || []} cols={[
        { key: "account", label: "Account", align: "left" }, { key: "strategy", label: "Strat", align: "center" },
        { key: "trades", label: "Trades" }, { key: "settled", label: "Settled" }, { key: "open", label: "Open" }, { key: "unfilled_or_cancelled", label: "Unfilled" },
        { key: "win_rate", label: "Win rate", render: (r: any) => <Rate rate={r.win_rate} n={r.settled} lo={r.win_ci_low} hi={r.win_ci_high} flag={r.sample} /> },
        { key: "breakeven_win_rate", label: "Break-even", render: (r: any) => pct(r.breakeven_win_rate) },
        { key: "avg_entry_price", label: "Avg entry", render: (r: any) => price(r.avg_entry_price) },
        { key: "gross_profit", label: "Gross +", render: (r: any) => usd(r.gross_profit, 4) },
        { key: "gross_loss", label: "Gross −", render: (r: any) => usd(r.gross_loss, 4) },
        { key: "fees", label: "Fees", render: (r: any) => usd(r.fees, 4) },
        { key: "net_pnl", label: "Net P&L", render: (r: any) => <span className={pnlClass(r.net_pnl)}>{signedUsd(r.net_pnl, 4)}</span> },
        { key: "roi", label: "ROI", render: (r: any) => <span className={pnlClass(r.roi)}>{pct(r.roi)}</span> },
        { key: "max_drawdown", label: "Max DD", render: (r: any) => usd(r.max_drawdown, 4) },
        { key: "ev_per_trade", label: "EV/trade [95% CI]", render: (r: any) => `${num(r.ev_per_trade, 4)}${isNum(r.ev_ci_low) ? ` [${num(r.ev_ci_low, 3)}, ${num(r.ev_ci_high, 3)}]` : ""}` },
        { key: "p_value_vs_breakeven", label: "p", render: (r: any) => <span className={(r.p_value_vs_breakeven ?? 1) < 0.05 ? "text-up" : "text-dim"}>{num(r.p_value_vs_breakeven, 3)}</span> },
        { key: "balance", label: "Balance", render: (r: any) => usd(r.balance, 4) },
      ]} />
    </Panel>
  );
}

function Backtest() {
  const { data: strategies } = usePoll<any[]>("/api/strategies", 0);
  const [key, setKey] = useState("A");
  const [params, setParams] = useState("{}");
  const [train, setTrain] = useState("0.6");
  const [assets, setAssets] = useState("");
  const [bal, setBal] = useState("20");
  const [res, setRes] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    const s = strategies?.find((x) => x.key === key);
    if (s) setParams(JSON.stringify(s.default_params, null, 1));
  }, [key, strategies]);
  const run = async () => {
    setBusy(true); setErr(null);
    try {
      setRes(await post("/api/backtest", { strategy_key: key, params: JSON.parse(params), train_fraction: Number(train), starting_balance: Number(bal),
        assets: assets ? assets.split(",").map((s) => s.trim().toUpperCase()) : [] }));
    } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  };
  const M = ({ m, label }: { m: any; label: string }) => (
    <Panel title={label}>
      {!m ? null : <div className="grid grid-cols-2 gap-2">
        <Stat label="Filled trades" value={int(m.filled_trades)} sub={`${m.signals} signals · ${m.unfilled} unfilled`} />
        <div className="rounded border border-line bg-panel2/60 px-3 py-2"><div className="label">Win rate</div><Rate rate={m.win_rate} n={m.filled_trades} lo={m.win_ci_low} hi={m.win_ci_high} flag={m.sample} /></div>
        <Stat label="Net P&L" value={<span className={pnlClass(m.net_pnl)}>{signedUsd(m.net_pnl, 4)}</span>} sub={`fees ${usd(m.fees, 4)}`} />
        <Stat label="ROI" value={pct(m.roi)} sub={`break-even win ${pct(m.breakeven_win_rate)}`} />
        <Stat label="EV / trade" value={num(m.ev_per_trade, 4)} sub={isNum(m.ev_ci_low) ? `95% CI [${num(m.ev_ci_low, 3)}, ${num(m.ev_ci_high, 3)}]` : "n<2"} />
        <Stat label="Max drawdown" value={usd(m.max_drawdown, 4)} sub={`p vs BE ${num(m.p_value_vs_breakeven, 3)}`} />
      </div>}
    </Panel>
  );
  return (
    <div className="space-y-3">
      <Panel title="Chronological backtester (recorded data, no look-ahead)" sub="Replays this collector's recorded 1-second order-book observations. Execution uses the NEXT recorded second's asks. Historical stats for I/J use only resolved data available before each decision; the test period uses statistics frozen at the train/test split.">
        <div className="grid grid-cols-1 gap-3 md:grid-cols-[220px_1fr]">
          <div className="space-y-2">
            <Field label="Strategy"><Select value={key} onChange={setKey} options={(strategies || []).map((s) => ({ value: s.key, label: `${s.key} · ${s.name}` }))} /></Field>
            <Field label="Train fraction"><input className={inputCls} value={train} onChange={(e) => setTrain(e.target.value)} /></Field>
            <Field label="Starting balance"><input className={inputCls} value={bal} onChange={(e) => setBal(e.target.value)} /></Field>
            <Field label="Assets (comma, blank = all)"><input className={inputCls} value={assets} onChange={(e) => setAssets(e.target.value)} placeholder="BTC,ETH" /></Field>
            <Button tone="primary" onClick={run} disabled={busy}>{busy ? "Running…" : "Run backtest"}</Button>
          </div>
          <Field label="Parameters (JSON)"><textarea className={inputCls + " h-56"} value={params} onChange={(e) => setParams(e.target.value)} /></Field>
        </div>
        <ErrorNote error={err || res?.error} />
      </Panel>
      {res && !res.error && (<>
        <Panel title="Data coverage">
          <KV rows={[["Markets in range", res.coverage.markets_in_range], ["Markets with observations", res.coverage.markets_with_observations],
            ["Observations", int(res.coverage.observations)], ["Synced-book coverage", pct(res.coverage.book_coverage_pct)],
            ["Period", `${ts(res.coverage.first_ts)} → ${ts(res.coverage.last_ts)}`], ["Train/test split", ts(res.split_ts)], ["Limitation", res.coverage.limitation]]} />
        </Panel>
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-3"><M m={res.train} label="Training period (in-sample)" /><M m={res.test} label="Test period (OUT-OF-SAMPLE)" /><M m={res.all} label="Whole range" /></div>
        <Panel title="Equity curve">
          <TimeChart title="backtest_equity" height={200} series={[{ name: "balance", color: "#a3e635", data: res.trades.filter((t: any) => t.filled > 0).map((t: any) => ({ time: t.ts, value: t.balance_after })) }]} />
        </Panel>
        <Panel title="Backtest trades">
          <DataTable exportName="backtest_trades" rows={res.trades} maxHeight={500} cols={[
            { key: "ts", label: "Time", render: (r: any) => ts(r.ts) }, { key: "period", label: "Period", align: "center" }, { key: "asset", label: "Asset" },
            { key: "secs_remaining", label: "T-", render: (r: any) => num(r.secs_remaining, 1) }, { key: "side", label: "Side", align: "center" },
            { key: "decision_ask", label: "Ask", render: (r: any) => price(r.decision_ask) }, { key: "vwap", label: "Fill", render: (r: any) => price(r.vwap) },
            { key: "filled", label: "Shares", render: (r: any) => num(r.filled, 2) }, { key: "fees", label: "Fee", render: (r: any) => usd(r.fees, 5) },
            { key: "winner", label: "Winner", align: "center" }, { key: "pnl", label: "P&L", render: (r: any) => <span className={pnlClass(r.pnl)}>{signedUsd(r.pnl, 4)}</span> },
            { key: "status", label: "Status", align: "center" },
          ]} />
        </Panel>
      </>)}
    </div>
  );
}

function Calculator() {
  const [f, setF] = useState({ entry_price: "0.03", investment: "1", quantity: "", fee_override: "", slippage_per_share: "0", other_costs: "0", reversal_frequency: "0.04" });
  const [r, setR] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  const { data: tbl } = usePoll<any[]>(`/api/calculator/table${qs({ investment: f.investment || 1, slippage_per_share: f.slippage_per_share || 0 })}`, 0);
  useEffect(() => {
    const body: any = { entry_price: Number(f.entry_price), slippage_per_share: Number(f.slippage_per_share || 0), other_costs: Number(f.other_costs || 0) };
    if (f.quantity) body.quantity = Number(f.quantity); else body.investment = Number(f.investment);
    if (f.fee_override) body.fee_override = Number(f.fee_override);
    if (f.reversal_frequency) body.reversal_frequency = Number(f.reversal_frequency);
    post("/api/calculator", body).then((x) => { setR(x); setErr(null); }).catch((e) => setErr(e.message));
  }, [f]);
  const set = (k: string) => (e: any) => setF((x) => ({ ...x, [k]: e.target.value }));
  return (
    <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
      <Panel title="Profitability calculator" sub="EV = P(win) × net profit if win + P(loss) × net loss. Break-even includes fees, slippage and other costs.">
        <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
          <Field label="Entry price"><input className={inputCls} value={f.entry_price} onChange={set("entry_price")} /></Field>
          <Field label="Investment $"><input className={inputCls} value={f.investment} onChange={set("investment")} /></Field>
          <Field label="or quantity"><input className={inputCls} value={f.quantity} onChange={set("quantity")} placeholder="shares" /></Field>
          <Field label="Fee override $" hint="blank = 0.07·p·(1−p)"><input className={inputCls} value={f.fee_override} onChange={set("fee_override")} /></Field>
          <Field label="Slippage / share"><input className={inputCls} value={f.slippage_per_share} onChange={set("slippage_per_share")} /></Field>
          <Field label="Other costs $"><input className={inputCls} value={f.other_costs} onChange={set("other_costs")} /></Field>
          <Field label="Actual reversal freq"><input className={inputCls} value={f.reversal_frequency} onChange={set("reversal_frequency")} /></Field>
        </div>
        <ErrorNote error={err} />
        {r && <div className="mt-3 grid-auto">
          <Stat label="Shares" value={num(r.shares, 2)} /><Stat label="Total cost" value={usd(r.total_cost, 4)} sub={`fee ${usd(r.fee, 5)} (est.)`} />
          <Stat label="Payout if win" value={usd(r.payout_if_win, 2)} /><Stat label="Net if win" value={usd(r.net_profit_if_win, 4)} tone="up" />
          <Stat label="Loss if lose" value={usd(r.net_loss_if_lose, 4)} tone="down" />
          <Stat label="Break-even P(win)" value={pct(r.breakeven_probability, 3)} tone="warn" />
          <Stat label="Expected value" value={<span className={pnlClass(r.expected_value)}>{signedUsd(r.expected_value, 4)}</span>} />
          <Stat label="Expected ROI" value={<span className={pnlClass(r.expected_roi)}>{pct(r.expected_roi)}</span>} />
        </div>}
      </Panel>
      <Panel title="Minimum reversal frequency required" sub={`Investment ${usd(Number(f.investment || 1))} per trade, slippage ${f.slippage_per_share}/share, taker fee 0.07·p·(1−p) (estimated).`}>
        <DataTable exportName="breakeven_table" rows={tbl || []} cols={[
          { key: "price", label: "Entry price", render: (x: any) => usd(x.price) }, { key: "shares", label: "Shares", render: (x: any) => num(x.shares, 2) },
          { key: "fee", label: "Fee", render: (x: any) => usd(x.fee, 5) }, { key: "total_cost", label: "Total cost", render: (x: any) => usd(x.total_cost, 4) },
          { key: "payout_if_win", label: "Payout", render: (x: any) => usd(x.payout_if_win, 2) },
          { key: "odds_multiple", label: "Multiple", render: (x: any) => `${num(x.odds_multiple, 1)}x` },
          { key: "min_reversal_frequency", label: "Min reversal freq", render: (x: any) => <span className="text-warn">{pct(x.min_reversal_frequency, 3)}</span> },
        ]} />
      </Panel>
    </div>
  );
}

function Historical() {
  const [hours, setHours] = useState("24");
  const { data, reload } = usePoll<any>("/api/historical/stats", 5000);
  const ing = data?.ingest;
  return (
    <Panel title="Historical ingest (public Polymarket history)" sub={data?.warning}>
      <div className="flex flex-wrap items-end gap-2">
        <Field label="Hours back"><input className={inputCls + " w-24"} value={hours} onChange={(e) => setHours(e.target.value)} /></Field>
        <Button tone="primary" disabled={ing?.running} onClick={async () => { await post("/api/historical/ingest", { hours: Number(hours) }); reload(); }}>{ing?.running ? "Ingesting…" : "Start ingest"}</Button>
        {ing && <span className="mono text-2xs text-dim">{ing.done}/{ing.total} windows · errors {ing.errors} {ing.finished_ts ? `· finished ${ts(ing.finished_ts)}` : ""}</span>}
      </div>
      <SectionNote>Results appear under Analytics → Historical (separate). They are never blended with live checkpoint statistics or paper-trading P&L.</SectionNote>
      <div className="mt-2"><KV rows={[["Markets ingested", data?.markets_ingested ?? 0], ["With price history", data?.markets_with_prices ?? 0], ["Source", data?.source]]} /></div>
    </Panel>
  );
}

function Catalog() {
  const { data } = usePoll<any[]>("/api/strategies", 0);
  return (
    <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
      {(data || []).map((s) => (
        <Panel key={s.key} title={`${s.key} · ${s.name}`} sub={s.docs?.summary || s.description}
          right={<span className={`rounded-full px-2.5 py-1 text-[11px] font-bold uppercase ${s.docs?.side === "favourite" ? "bg-info/15 text-info" : "bg-warn/15 text-warn"}`}>buys {s.docs?.side || "underdog"}</span>}>
          {s.docs?.how && <ol className="mb-3 list-decimal space-y-1 pl-5 text-[13px] text-dim">{s.docs.how.map((h: string, i: number) => <li key={i}>{h}</li>)}</ol>}
          {s.docs?.idea && <p className="text-[13px]"><b>Idea:</b> <span className="text-dim">{s.docs.idea}</span></p>}
          {s.docs?.risk && <p className="mt-1 text-[13px] text-warn"><b>Risk:</b> {s.docs.risk}</p>}
          <div className="mt-3 space-y-1.5 border-t border-line pt-3">
            {Object.entries(s.default_params).map(([k, v]) => (
              <div key={k} className="flex gap-2 text-[12px]"><span className="mono shrink-0 font-semibold">{k}={JSON.stringify(v)}</span>
                <span className="text-faint">{s.param_docs?.[k] || ""}</span></div>))}
          </div>
        </Panel>
      ))}
    </div>
  );
}
