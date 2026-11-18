"use client";
import clsx from "clsx";
import { useState } from "react";
import Drill from "@/components/Drill";
import { DataTable, ErrorNote, Panel, Pill, Rate, SectionNote, Select, Tabs } from "@/components/ui";
import { qs, usePoll } from "@/lib/api";
import { isNum, num, pct, price } from "@/lib/format";
import { useLive } from "@/lib/live";
import { useRealOdds, verdict } from "@/lib/realodds";

const ASSETS = ["ALL", "BTC", "ETH", "SOL", "XRP", "DOGE", "HYPE", "BNB"];
const T = [120, 90, 60, 45, 30, 20, 15, 10, 7, 5, 3, 2, 1];

function rateColor(rate: number | null, n: number) {
  if (!isNum(rate) || n === 0) return "bg-panel2/40 text-faint";
  if (n < 30) return "bg-panel2 text-dim";
  if (rate >= 0.1) return "bg-warn/25 text-warn";
  if (rate >= 0.05) return "bg-warn/15 text-ink";
  if (rate >= 0.02) return "bg-info/10 text-ink";
  return "bg-panel2/70 text-ink";
}

export default function Scanner() {
  const [asset, setAsset] = useState("ALL");
  const [tm, setTm] = useState<string>("");
  const [tab, setTab] = useState("prob");
  const [drill, setDrill] = useState<any>(null);
  const a = asset === "ALL" ? undefined : asset;
  const { data, error } = usePoll<any>(`/api/scanner${qs({ asset: a, t_minus: tm || undefined })}`, 30000);
  const { data: mProb } = usePoll<any>(`/api/scanner/matrix${qs({ asset: a, row: "prob_bucket" })}`, 30000);
  const { data: mPrice } = usePoll<any>(`/api/scanner/matrix${qs({ asset: a, row: "price_bucket" })}`, 30000);
  const { tick } = useLive();
  const real = useRealOdds();
  const opps = (tick?.opportunities || []).sort((x: any, y: any) => x.secs_remaining - y.secs_remaining);
  const matrix = tab === "price" ? mPrice : mProb;
  const rowsKey = tab === "price" ? "price_bucket" : "prob_bucket";

  const statCols = (bucketKey: string, bucketLabel: string) => [
    { key: "t_minus", label: "T-", render: (r: any) => `T-${r.t_minus}` },
    { key: bucketKey, label: bucketLabel, align: "left" as const },
    { key: "opportunities", label: "Opps" },
    { key: "executable", label: "Executable" },
    { key: "insufficient_liquidity", label: "Thin liq." },
    { key: "reversals", label: "Reversals" },
    { key: "non_reversals", label: "Held" },
    { key: "reversal_rate", label: "Reversal %", render: (r: any) => <Rate rate={r.reversal_rate} n={r.resolved} lo={r.reversal_ci_low} hi={r.reversal_ci_high} flag={r.sample} /> },
    { key: "non_reversal_rate", label: "Held %", render: (r: any) => pct(r.non_reversal_rate) },
    { key: "avg_entry_price", label: "Avg ask", render: (r: any) => price(r.avg_entry_price) },
    { key: "avg_liquidity_usd", label: "Avg liq $", render: (r: any) => num(r.avg_liquidity_usd, 1) },
    { key: "avg_spread", label: "Avg spread", render: (r: any) => price(r.avg_spread) },
    { key: "avg_secs_remaining", label: "Avg secs", render: (r: any) => num(r.avg_secs_remaining, 2) },
    { key: "avg_abs_dist_bps", label: "Avg |dist| bp", render: (r: any) => num(r.avg_abs_dist_bps, 2) },
    { key: "avg_abs_mom_10s", label: "Avg |mom10s|", render: (r: any) => num(r.avg_abs_mom_10s, 4) },
    { key: "realistic_ev_per_share", label: "Real EV/sh", render: (r: any) => <span className={(r.realistic_ev_per_share ?? 0) > 0 ? "text-up" : "text-down"}>{num(r.realistic_ev_per_share, 4)}</span> },
  ];

  return (
    <div className="page space-y-3">
      <Panel title="Live reversal opportunities" sub="Markets happening right now where one side is the clear favourite (80%+) and the other side (the underdog) costs 20¢ or less. Updates every second."
        right={<Pill kind="LIVE" />}>
        <DataTable rows={opps} empty="No cheap-underdog situations right now." cols={[
          { key: "asset", label: "Asset" },
          { key: "secs_remaining", label: "T-", render: (r: any) => <span className={r.secs_remaining <= 10 ? "text-warn" : ""}>{r.secs_remaining.toFixed(0)}s</span> },
          { key: "favourite", label: "Fav", align: "center", render: (r: any) => <span className={r.favourite === "UP" ? "text-up" : "text-down"}>{r.favourite}</span> },
          { key: "fav_prob", label: "Fav prob", render: (r: any) => pct(r.fav_prob) },
          { key: "underdog", label: "Cheap", align: "center" },
          { key: "dog_ask", label: "Ask", render: (r: any) => price(r.dog_ask) },
          { key: "poly", label: "Polymarket says underdog wins", render: (r: any) => <b>{pct(r.dog_ask, 1)}</b> },
          { key: "real", label: "Really wins (history)", render: (r: any) => { const x = real(r.fav_prob, r.secs_remaining); return x ? <b className={x.rate > r.dog_ask ? "text-warn" : "text-up"}>{pct(x.rate, 1)} <span className="font-normal text-faint">of {x.n}</span></b> : "—"; } },
          { key: "verdict", label: "What that means", align: "left", render: (r: any) => { const v = verdict(r.dog_ask, real(r.fav_prob, r.secs_remaining)); return <span className={v.tone === "up" ? "text-up" : v.tone === "warn" ? "text-warn" : "text-dim"}>{v.text}</span>; } },
          { key: "dog_ask_size", label: "Size @ask", render: (r: any) => num(r.dog_ask_size, 0) },
          { key: "liquidity_usd", label: "Liq $ ≤ask", render: (r: any) => num(r.liquidity_usd, 2) },
          { key: "spread", label: "Spread", render: (r: any) => price(r.spread) },
          { key: "dist_bps", label: "Dist bp", render: (r: any) => num(r.dist_bps, 2) },
          { key: "mom_toward_dog", label: "Momentum", align: "center", render: (r: any) => r.mom_toward_dog == null ? "—" : r.mom_toward_dog ? <span className="text-up">toward</span> : <span className="text-dim">away</span> },
          { key: "executable", label: "Exec.", align: "center", render: (r: any) => r.executable ? "✓" : <span className="text-warn">thin</span> },
        ]} />
      </Panel>

      <Panel title="Reversal scanner — resolved observations"
        sub={data?.note}
        right={<>
          <Select value={asset} onChange={setAsset} options={ASSETS.map((x) => ({ value: x, label: x === "ALL" ? "All 7 assets (combined)" : x }))} />
          <Select value={tm} onChange={setTm} options={[{ value: "", label: "All checkpoints (separate rows)" }, ...T.map((t) => ({ value: String(t), label: `T-${t} only` }))]} />
        </>}>
        <ErrorNote error={error} />
        <div className="mb-2 text-2xs text-dim">
          {data ? `${data.totals.checkpoints_recorded} checkpoints recorded · ${data.totals.resolved} resolved` : "loading…"} ·
          A reversal = the favourite (the side the market thought would win) ended up losing. Cells with n &lt; 30 are greyed: too few markets to trust.
        </div>
        <Tabs value={tab} onChange={setTab} tabs={[{ key: "prob", label: "By favourite probability" }, { key: "price", label: "By underdog entry price" }, { key: "asset", label: "By asset" }]} />
        {tab !== "asset" && matrix && (
          <div className="mt-3 overflow-x-auto">
            <table className="text-2xs">
              <thead><tr><th className="px-2 py-1 text-left text-faint">{tab === "price" ? "entry price" : "fav prob"}</th>
                {T.map((t) => <th key={t} className={clsx("px-1 py-1 text-center", [10, 5, 3, 1].includes(t) ? "text-accent" : "text-faint")}>T-{t}</th>)}</tr></thead>
              <tbody>
                {matrix.rows.map((row: string) => (
                  <tr key={row}>
                    <td className="mono whitespace-nowrap px-2 py-0.5 text-dim">{row}</td>
                    {T.map((t) => {
                      const c = matrix.cells.find((x: any) => x.row === row && x.t_minus === t);
                      return (
                        <td key={t} className="p-0.5">
                          <button onClick={() => c && setDrill({ asset: a, t_minus: t, [rowsKey]: row })}
                            title={c ? `${pct(c.rate)} [${pct(c.ci_low, 1)}–${pct(c.ci_high, 1)}] n=${c.n}` : "no data"}
                            className={clsx("mono block w-[64px] rounded px-1 py-1 text-center", rateColor(c?.rate ?? null, c?.n ?? 0))}>
                            {c ? <>{pct(c.rate, 1)}<br /><span className="text-faint">n={c.n}</span></> : "·"}
                          </button>
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {tab !== "asset" && (
          <div className="mt-3 rounded-2xl bg-panel2/60 p-4 text-[13px] leading-relaxed text-dim">
            <b className="text-ink">How to read this grid:</b> each box answers <i>“when the market looked like this, how often was the favourite wrong?”</i>
            <br />• <b className="text-ink">Left side</b> = {tab === "price" ? "what the underdog cost (in dollars, $0.05 = 5¢)" : "how sure Polymarket was that the favourite would win"}.
            <br />• <b className="text-ink">Top</b> = time left before the market closes (T-60 = 60 seconds left).
            <br />• <b className="text-ink">Big number</b> = % of those markets where the favourite LOST (the underdog won). <b className="text-ink">n</b> = how many markets that is based on.
            <br />• Example: “0.0% n=57” = seen 57 times, the favourite never lost. Yellow boxes = flips happened often there.
          </div>
        )}
        <div className="mt-3">
          {tab === "prob" && <DataTable exportName="scanner_prob" rows={data?.by_prob_bucket || []} cols={statCols("prob_bucket", "Fav prob")} onRow={(r) => setDrill({ asset: a, t_minus: r.t_minus, prob_bucket: r.prob_bucket })} maxHeight={560} />}
          {tab === "price" && <DataTable exportName="scanner_price" rows={data?.by_price_bucket || []} cols={statCols("price_bucket", "Entry price")} onRow={(r) => setDrill({ asset: a, t_minus: r.t_minus, price_bucket: r.price_bucket })} maxHeight={560} />}
          {tab === "asset" && <DataTable exportName="scanner_asset" rows={data?.by_asset || []} cols={statCols("asset", "Asset")} onRow={(r) => setDrill({ asset: r.asset, t_minus: r.t_minus })} maxHeight={560} />}
        </div>
        <SectionNote><b>Columns:</b> Opps = how many times this happened · Executable = times there were enough sellers to actually buy · Thin liq. = too few sellers · Reversals = favourite lost · Held = favourite won · Avg ask = average underdog price · Avg liq $ = dollars available to buy · Spread = gap between buy and sell price · Avg secs = seconds left · |dist| bp = how far the coin was from its start price (1bp = 0.01%) · mom10s = how fast it moved in the last 10s · Real EV/sh = average profit per $1 share if you had bought the underdog every time (green = would have made money).</SectionNote>
        <SectionNote>Real EV/share = reversal indicator − (book-walk price for $10 + 0.07·p·(1−p) fee), averaged over resolved observations. Theoretical EV ignores fees and depth. Click any row or cell to see the underlying observations.</SectionNote>
      </Panel>
      <Drill filter={drill} onClose={() => setDrill(null)} />
    </div>
  );
}
