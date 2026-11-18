"use client";
import { useState } from "react";
import { RateBars, TimeChart } from "@/components/Chart";
import { BarChart, XYLines, seriesColor } from "@/components/Charts2";
import Drill from "@/components/Drill";
import AssetNav, { Verdict } from "@/components/AssetNav";
import Link from "next/link";
import { DataTable, ErrorNote, Field, inputCls, Panel, Rate, SectionNote, Select, Tabs } from "@/components/ui";
import { qs, usePoll } from "@/lib/api";
import { isNum, num, pct, price } from "@/lib/format";

const ASSETS = ["ALL", "BTC", "ETH", "SOL", "XRP", "DOGE", "HYPE", "BNB"];
const T = [120, 90, 60, 45, 30, 20, 15, 10, 7, 5, 3, 2, 1];

export default function Analytics() {
  const [tab, setTab] = useState("intervals");
  const [asset, setAsset] = useState("ALL");
  const [minProb, setMinProb] = useState("");
  const [maxPrice, setMaxPrice] = useState("");
  const [tm, setTm] = useState("10");
  const [drill, setDrill] = useState<any>(null);
  const a = asset === "ALL" ? undefined : asset;
  const { data: iv, error } = usePoll<any[]>(`/api/analytics/intervals${qs({ asset: a, min_fav_prob: minProb, max_price: maxPrice })}`, 30000);
  const { data: br } = usePoll<any>(`/api/analytics/breakdowns${qs({ asset: a, t_minus: tm || undefined })}`, 30000);
  const { data: ca } = usePoll<any>(`/api/analytics/cross-asset${qs({ t_minus: tm || 10, max_price: maxPrice || 0.2 })}`, 60000);
  const { data: strat } = usePoll<any[]>("/api/strategies/compare", 15000);
  const { data: hist } = usePoll<any>(`/api/historical/stats${qs({ asset: a })}`, 20000);
  const { data: summ } = usePoll<any[]>("/api/analytics/assets-summary", 20000);
  const [minN, setMinN] = useState("30");
  const { data: pmap } = usePoll<any>(`/api/analytics/profit-map${qs({ min_n: minN })}`, 30000);
  const { data: curves } = usePoll<any>("/api/analytics/reversal-curves", 60000);
  const { data: odds } = usePoll<any>("/api/analytics/odds", 60000);
  const { data: ser } = usePoll<any>("/api/analytics/series", 30000);

  const rateCols = (k: string, label: string) => [
    { key: k, label, align: "left" as const, render: (r: any) => (k === "t_minus" ? `T-${r.t_minus}` : r[k]) },
    { key: "resolved", label: "Resolved n" },
    { key: "favourite_wins", label: "Fav W" }, { key: "favourite_losses", label: "Fav L" },
    { key: "underdog_wins", label: "Dog W" }, { key: "underdog_losses", label: "Dog L" },
    { key: "reversal_rate", label: "Reversal %", render: (r: any) => <Rate rate={r.reversal_rate} n={r.resolved} lo={r.reversal_ci_low} hi={r.reversal_ci_high} flag={r.sample} /> },
    { key: "actual_fav_win_prob", label: "Actual fav win", render: (r: any) => pct(r.actual_fav_win_prob) },
    { key: "implied_fav_prob", label: "Implied fav", render: (r: any) => pct(r.implied_fav_prob) },
    { key: "calibration_error", label: "Calib. err", render: (r: any) => <span className={(r.calibration_error ?? 0) > 0 ? "text-warn" : "text-info"}>{pct(r.calibration_error)}</span> },
    { key: "brier", label: "Brier", render: (r: any) => num(r.brier, 4) },
    { key: "log_loss", label: "Log loss", render: (r: any) => num(r.log_loss, 4) },
    { key: "avg_entry_price", label: "Avg ask", render: (r: any) => price(r.avg_entry_price) },
    { key: "avg_exec_price", label: "Avg exec px", render: (r: any) => price(r.avg_exec_price) },
    { key: "avg_potential_payout_per_dollar", label: "Payout / $", render: (r: any) => num(r.avg_potential_payout_per_dollar, 1) },
    { key: "theoretical_ev_per_share", label: "Theo EV/sh", render: (r: any) => num(r.theoretical_ev_per_share, 4) },
    { key: "realistic_ev_per_share", label: "Real EV/sh [95% CI]", render: (r: any) => (
      <span className="inline-flex flex-col items-end leading-tight"><span className={(r.realistic_ev_per_share ?? 0) > 0 ? "text-up" : "text-down"}>{num(r.realistic_ev_per_share, 4)}</span>
        <span className="text-2xs text-faint">{isNum(r.realistic_ev_ci_low) ? `[${num(r.realistic_ev_ci_low, 3)}, ${num(r.realistic_ev_ci_high, 3)}]` : ""}</span></span>) },
    { key: "breakeven_prob", label: "Break-even", render: (r: any) => pct(r.breakeven_prob) },
    { key: "p_value_vs_breakeven", label: "p (>BE)", render: (r: any) => <span className={(r.p_value_vs_breakeven ?? 1) < 0.05 ? "text-up" : "text-dim"}>{num(r.p_value_vs_breakeven, 3)}</span> },
  ];

  return (
    <div className="page space-y-3">
      <AssetNav />
      <Panel title="Every market at a glance" sub="Realised paper P&L and key-checkpoint reversal rates per asset. Click a row for the full per-market analytics.">
        <DataTable exportName="markets_compared" rows={summ || []} onRow={(r) => (window.location.href = `/analytics/asset/?s=${r.asset}`)} cols={[
          { key: "asset", label: "Market", align: "left", render: (r: any) => <Link href={`/analytics/asset/?s=${r.asset}`} className="mono font-bold text-ink hover:text-accent">{r.asset}</Link> },
          { key: "trades", label: "Trades" }, { key: "wins", label: "W" }, { key: "losses", label: "L" },
          { key: "win_rate", label: "Win rate", render: (r: any) => <Rate rate={r.win_rate} n={r.settled} lo={r.win_ci_low} hi={r.win_ci_high} flag={r.sample} /> },
          { key: "breakeven_win_rate", label: "Break-even", render: (r: any) => pct(r.breakeven_win_rate) },
          { key: "net_pnl", label: "Net P&L", render: (r: any) => <span className={(r.net_pnl ?? 0) > 0 ? "text-up" : (r.net_pnl ?? 0) < 0 ? "text-down" : ""}>{num(r.net_pnl, 4)}</span> },
          { key: "fees", label: "Fees", render: (r: any) => num(r.fees, 4) },
          { key: "roi", label: "ROI", render: (r: any) => pct(r.roi, 1) },
          { key: "ev_per_trade", label: "EV/trade [CI]", render: (r: any) => `${num(r.ev_per_trade, 4)}${isNum(r.ev_ci_low) ? ` [${num(r.ev_ci_low, 3)}, ${num(r.ev_ci_high, 3)}]` : ""}` },
          ...([10, 5, 3, 1] as const).map((t) => ({ key: `rev_T${t}`, label: `Rev T-${t}`, sort: (r: any) => r[`rev_T${t}`]?.rate,
            render: (r: any) => <Rate rate={r[`rev_T${t}`]?.rate} n={r[`rev_T${t}`]?.n} lo={r[`rev_T${t}`]?.ci_low} hi={r[`rev_T${t}`]?.ci_high} flag={r[`rev_T${t}`]?.sample} /> })),
          { key: "verdict", label: "Verdict", align: "center", render: (r: any) => <Verdict v={r.verdict} /> },
        ]} />
      </Panel>
      <Panel title="Real flip odds vs Polymarket price — every market" sub={`Updates as each 5-minute market resolves. ${odds?.note || ""}`}>
        {odds?.all?.length ? (<>
          <XYLines xs={odds.all.map((r: any) => r.t)} xLabel={(t) => `T-${t}`} series={[
            { name: "Real flip rate", values: odds.all.map((r: any) => r.actual), n: odds.all.map((r: any) => r.n), color: "#00d64b" },
            { name: "Polymarket price", values: odds.all.map((r: any) => r.market_price), color: "#ff9f0a" },
            { name: "Model estimate", values: odds.all.map((r: any) => r.model), color: "#409cff" },
          ]} />
          <div className="mt-3"><DataTable exportName="odds_vs_price" rows={[
            ...odds.all.map((r: any) => ({ asset: "ALL", ...r })),
            ...Object.entries(odds.assets || {}).flatMap(([a, rows]: any) => rows.map((r: any) => ({ asset: a, ...r }))),
          ]} maxHeight={420} cols={[
            { key: "asset", label: "Coin", align: "left" }, { key: "t", label: "T-", render: (r: any) => `T-${r.t}` },
            { key: "n", label: "n" },
            { key: "actual", label: "Real flip %", render: (r: any) => <Rate rate={r.actual} n={r.n} lo={r.ci_low} hi={r.ci_high} /> },
            { key: "market_price", label: "Polymarket price", render: (r: any) => pct(r.market_price) },
            { key: "edge_vs_price", label: "Edge (real − price − fee)", render: (r: any) => <span className={(r.edge_vs_price ?? 0) > 0 ? "text-up" : "text-down"}>{pct(r.edge_vs_price)}</span> },
            { key: "model", label: "Model %", render: (r: any) => pct(r.model) },
            { key: "avg_abs_dist_bps", label: "Avg distance", render: (r: any) => `${num(r.avg_abs_dist_bps, 1)}bp` },
            { key: "model_trades", label: "Model buys (won)", render: (r: any) => `${r.model_trades} (${r.model_trade_wins})` },
          ]} /></div>
        </>) : <div className="text-faint">Collecting data…</div>}
      </Panel>
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <Panel title="Reversal rate by time left — every market" sub="How often the favourite ended up losing, at each second before close. Tap names to hide/show.">
          {curves?.all ? <XYLines xs={T} xLabel={(t) => `T-${t}`} series={[
            { name: "All", values: curves.all.map((r: any) => r.rate), n: curves.all.map((r: any) => r.n), color: "#e0e0e0" },
            ...Object.entries(curves.assets || {}).map(([a, rows]: any, i) => ({ name: a, values: rows.map((r: any) => r.rate), n: rows.map((r: any) => r.n), color: seriesColor(i) })),
          ]} /> : <div className="text-faint">Loading…</div>}
        </Panel>
        <Panel title="Cumulative profit by strategy" sub="Realised P&L over time for each strategy account.">
          <TimeChart title="pnl_by_strategy" height={240} series={Object.entries(ser?.by_strategy || {}).map(([k, pts]: any, i) => ({
            name: k, color: seriesColor(i), width: 2, data: pts.map((p: any) => ({ time: p.t, value: p.v })) }))} />
        </Panel>
        <Panel title="Profit by market"><BarChart data={(ser?.pnl_by_asset || []).map((d: any) => ({ x: d.x, v: d.pnl, trades: d.trades, wins: d.wins }))} sub={(d) => `${d.trades} trades · ${d.wins} won`} /></Panel>
        <Panel title="Profit by strategy"><BarChart data={(ser?.pnl_by_strategy || []).map((d: any) => ({ x: d.x, v: d.pnl, trades: d.trades, wins: d.wins }))} sub={(d) => `${d.trades} trades · ${d.wins} won`} /></Panel>
        <Panel title="Win rate by market"><BarChart money={false} data={(ser?.pnl_by_asset || []).map((d: any) => ({ x: d.x, v: d.win_rate ?? 0, trades: d.trades }))} sub={(d) => `n=${d.trades}`} /></Panel>
        <Panel title="Profit by hour (last 72h)"><BarChart data={(ser?.hourly || []).slice(-24).map((d: any) => ({ x: new Date(d.t).getHours() + "h", v: d.pnl, trades: d.trades }))} sub={(d) => `${d.trades} trades`} /></Panel>
      </div>
      <Panel title="Statistical analytics" sub="Resolved observations only · 95% Wilson intervals · each checkpoint is a separate statistic · LIVE experimental data (historical shown separately)"
        right={<>
          <Select value={asset} onChange={setAsset} options={ASSETS.map((x) => ({ value: x, label: x === "ALL" ? "All assets" : x }))} />
          <Field label=""><input className={inputCls + " w-28"} placeholder="min fav prob" value={minProb} onChange={(e) => setMinProb(e.target.value)} /></Field>
          <Field label=""><input className={inputCls + " w-28"} placeholder="max dog ask" value={maxPrice} onChange={(e) => setMaxPrice(e.target.value)} /></Field>
          <Select value={tm} onChange={setTm} options={[{ value: "", label: "breakdowns: all T" }, ...T.map((t) => ({ value: String(t), label: `T-${t}` }))]} />
        </>}>
        <ErrorNote error={error} />
        <Tabs value={tab} onChange={setTab} tabs={[
          { key: "intervals", label: "Time intervals" }, { key: "profitmap", label: "Profit map (all markets)" }, { key: "types", label: "Reversal types" }, { key: "calibration", label: "Calibration" },
          { key: "breakdowns", label: "Distance & momentum" }, { key: "cross", label: "Cross-asset" }, { key: "strategy", label: "Simulated trading" },
          { key: "historical", label: "Historical (separate)" },
        ]} />
        <div className="mt-3 space-y-3">
          {tab === "intervals" && (<>
            <RateBars label="probability-reversal rate by checkpoint (bars grey when n<30)"
              rows={(iv || []).map((r) => ({ x: `T-${r.t_minus}`, rate: r.reversal_rate ?? null, lo: r.reversal_ci_low, hi: r.reversal_ci_high, n: r.resolved }))} />
            <DataTable exportName="time_intervals" rows={iv || []} cols={rateCols("t_minus", "Interval")} onRow={(r) => setDrill({ asset: a, t_minus: r.t_minus })}
              rowClass={(r) => (r.key ? "bg-accent/5" : undefined)} />
            <SectionNote>T-10, T-5, T-3 and T-1 are highlighted. Realistic EV per $1 share = P(underdog wins) − (book-walk price + taker fee). p-value: one-sided binomial test that the true reversal rate exceeds the fee-adjusted break-even.</SectionNote>
          </>)}
          {tab === "profitmap" && (<>
            <div className="flex items-center gap-2 text-2xs text-dim">min sample per cell
              <input className={inputCls + " w-16"} value={minN} onChange={(e) => setMinN(e.target.value)} /> <span>{pmap?.note}</span></div>
            <DataTable exportName="profit_map" rows={pmap?.cells || []} maxHeight={640} onRow={(r) => setDrill({ asset: r.asset === "ALL" ? undefined : r.asset, t_minus: r.t_minus, price_bucket: r.price_bucket })} cols={[
              { key: "asset", label: "Market", align: "left" }, { key: "t_minus", label: "T-", render: (r: any) => `T-${r.t_minus}` },
              { key: "price_bucket", label: "Entry price", align: "left" }, { key: "resolved", label: "n" }, { key: "reversals", label: "Rev." },
              { key: "reversal_rate", label: "Reversal %", render: (r: any) => <Rate rate={r.reversal_rate} n={r.resolved} lo={r.reversal_ci_low} hi={r.reversal_ci_high} flag={r.sample} /> },
              { key: "avg_exec_price", label: "Avg exec px", render: (r: any) => price(r.avg_exec_price) },
              { key: "breakeven_prob", label: "Break-even", render: (r: any) => pct(r.breakeven_prob) },
              { key: "executable", label: "Exec." },
              { key: "realistic_ev_per_share", label: "Real EV/sh", render: (r: any) => <span className={(r.realistic_ev_per_share ?? 0) > 0 ? "text-up" : "text-down"}>{num(r.realistic_ev_per_share, 4)}</span> },
              { key: "realistic_ev_ci_low", label: "EV CI low", render: (r: any) => num(r.realistic_ev_ci_low, 4) },
              { key: "realistic_ev_per_dollar", label: "EV per $1", render: (r: any) => pct(r.realistic_ev_per_dollar, 1) },
              { key: "p_value_vs_breakeven", label: "p", render: (r: any) => num(r.p_value_vs_breakeven, 3) },
              { key: "verdict", label: "Verdict", align: "center", render: (r: any) => <Verdict v={r.verdict} /> },
            ]} />
          </>)}
          {tab === "types" && (
            <DataTable exportName="reversal_types" rows={br?.event_types || []} cols={[
              { key: "t_minus", label: "Interval", align: "left", render: (r: any) => `T-${r.t_minus}` },
              ...(["probability_reversal", "price_crossover", "underlying_reversal", "settlement_reversal"] as const).map((k) => ({
                key: k, label: k.replace(/_/g, " "), render: (r: any) => <Rate rate={r[k]?.rate} n={r[k]?.n} lo={r[k]?.ci_low} hi={r[k]?.ci_high} flag={r[k]?.sample} />,
              })),
            ]} />
          )}
          {tab === "calibration" && (<>
            <RateBars label="actual favourite win rate by implied-probability bin" rows={(br?.calibration || []).map((c: any) => ({ x: c.bin, rate: c.actual, lo: c.ci_low, hi: c.ci_high, n: c.n }))} />
            <DataTable exportName="calibration" rows={br?.calibration || []} cols={[
              { key: "bin", label: "Implied bin", align: "left" }, { key: "implied", label: "Mean implied", render: (r: any) => pct(r.implied) },
              { key: "actual", label: "Actual", render: (r: any) => <Rate rate={r.actual} n={r.n} lo={r.ci_low} hi={r.ci_high} /> },
              { key: "gap", label: "Implied − actual", render: (r: any) => pct(r.implied - r.actual) },
            ]} />
          </>)}
          {tab === "breakdowns" && (<>
            <div className="label">By settlement distance (|spot − opening reference|)</div>
            <DataTable exportName="by_distance" rows={br?.distance || []} cols={rateCols("dist_bucket", "Distance").slice(0, 8)} />
            <div className="label">By underlying momentum direction (10 s)</div>
            <DataTable exportName="by_momentum" rows={br?.momentum || []} cols={rateCols("momentum_dir", "Momentum").slice(0, 8)} />
          </>)}
          {tab === "cross" && (<>
            <div className="text-2xs text-dim">Leaderboard at T-{ca?.t_minus} (underdog ask ≤ {ca?.max_price}). Ranked by: {ca?.ranking_basis}. Gross payout is never used for ranking.</div>
            <DataTable exportName="cross_asset" rows={ca?.leaderboard || []} cols={[
              { key: "rank", label: "#" }, { key: "asset", label: "Asset", align: "left" },
              ...rateCols("asset", "").slice(1, 2), ...rateCols("asset", "").slice(6, 7),
              { key: "avg_entry_price", label: "Avg ask", render: (r: any) => price(r.avg_entry_price) },
              { key: "avg_liquidity_usd", label: "Avg liq $", render: (r: any) => num(r.avg_liquidity_usd, 1) },
              { key: "avg_spread", label: "Avg spread", render: (r: any) => price(r.avg_spread) },
              ...rateCols("asset", "").slice(17, 21),
            ]} />
            <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
              <Panel title={`Return correlation (${ca?.correlation?.window_s}s returns, n=${ca?.correlation?.n ?? 0})`}>
                {ca?.correlation?.matrix && Object.keys(ca.correlation.matrix).length ? (
                  <table className="mono w-full text-2xs"><thead><tr><th></th>{Object.keys(ca.correlation.matrix).map((k) => <th key={k} className="text-dim">{k}</th>)}</tr></thead>
                    <tbody>{Object.entries(ca.correlation.matrix).map(([r, row]: any) => (
                      <tr key={r}><td className="text-dim">{r}</td>{Object.keys(ca.correlation.matrix).map((c) => {
                        const v = row[c]; return <td key={c} className="text-center" style={{ background: isNum(v) ? `rgba(163,230,53,${Math.abs(v) * 0.35})` : undefined }}>{num(v, 2)}</td>;
                      })}</tr>))}</tbody></table>
                ) : <div className="text-2xs text-faint">Needs ≥30 aligned return windows.</div>}
              </Panel>
              <Panel title="Simultaneous reversals">
                <div className="space-y-1 text-xs">
                  <div>Windows: <span className="mono">{ca?.simultaneous?.windows ?? 0}</span> · with ≥2 asset reversals: <span className="mono">{ca?.simultaneous?.multi_reversal_windows ?? 0}</span></div>
                  <div className="flex items-center justify-between">P(other asset reverses | BTC reversed) <Rate rate={ca?.simultaneous?.given_btc_reversed?.rate} n={ca?.simultaneous?.given_btc_reversed?.n} lo={ca?.simultaneous?.given_btc_reversed?.ci_low} hi={ca?.simultaneous?.given_btc_reversed?.ci_high} /></div>
                  <div className="flex items-center justify-between">P(other asset reverses | BTC held) <Rate rate={ca?.simultaneous?.given_btc_held?.rate} n={ca?.simultaneous?.given_btc_held?.n} lo={ca?.simultaneous?.given_btc_held?.ci_low} hi={ca?.simultaneous?.given_btc_held?.ci_high} /></div>
                </div>
              </Panel>
            </div>
          </>)}
          {tab === "strategy" && (
            <DataTable exportName="simulated_trading" rows={strat || []} cols={[
              { key: "account", label: "Account", align: "left" }, { key: "trades", label: "Trades" }, { key: "wins", label: "W" }, { key: "losses", label: "L" },
              { key: "win_rate", label: "Win rate", render: (r: any) => <Rate rate={r.win_rate} n={r.settled} lo={r.win_ci_low} hi={r.win_ci_high} flag={r.sample} /> },
              { key: "breakeven_win_rate", label: "Break-even", render: (r: any) => pct(r.breakeven_win_rate) },
              { key: "net_pnl", label: "Net P&L", render: (r: any) => <span className={(r.net_pnl ?? 0) >= 0 ? "text-up" : "text-down"}>{num(r.net_pnl, 4)}</span> },
              { key: "ev_per_trade", label: "EV/trade [CI]", render: (r: any) => `${num(r.ev_per_trade, 4)} ${isNum(r.ev_ci_low) ? `[${num(r.ev_ci_low, 3)}, ${num(r.ev_ci_high, 3)}]` : ""}` },
              { key: "p_value_vs_breakeven", label: "p", render: (r: any) => num(r.p_value_vs_breakeven, 3) },
            ]} />
          )}
          {tab === "historical" && (<>
            <div className="rounded border border-warn/40 bg-warn/5 px-3 py-2 text-2xs text-warn">{hist?.warning}</div>
            <div className="text-2xs text-dim">{hist?.source} · markets ingested {hist?.markets_ingested ?? 0} (with prices {hist?.markets_with_prices ?? 0}). Run an ingest from Strategy Lab → Historical.</div>
            <DataTable exportName="historical_by_horizon" rows={hist?.by_horizon || []} cols={[
              { key: "horizon_s", label: "Horizon", align: "left", render: (r: any) => `~T-${r.horizon_s}s` },
              { key: "rate", label: "Reversal %", render: (r: any) => <Rate rate={r.rate} n={r.n} lo={r.ci_low} hi={r.ci_high} flag={r.sample} /> },
            ]} />
            <DataTable exportName="historical_by_prob" rows={hist?.by_prob_bucket || []} cols={[
              { key: "horizon_s", label: "Horizon", align: "left", render: (r: any) => `~T-${r.horizon_s}s` }, { key: "prob_bucket", label: "Fav prob", align: "left" },
              { key: "rate", label: "Reversal %", render: (r: any) => <Rate rate={r.rate} n={r.n} lo={r.ci_low} hi={r.ci_high} flag={r.sample} /> },
            ]} />
          </>)}
        </div>
      </Panel>
      <Drill filter={drill} onClose={() => setDrill(null)} />
    </div>
  );
}
