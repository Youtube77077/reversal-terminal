"use client";
import clsx from "clsx";
import { Pause, Play, SkipBack, SkipForward } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import { Marker, TimeChart } from "@/components/Chart";
import { Button, DataTable, KV, Panel, Pill, Select } from "@/components/ui";
import { api, qs, usePoll } from "@/lib/api";
import { num, pct, price, spot, ts } from "@/lib/format";

const SPEEDS = [1, 2, 5, 10, 25, 50];

/** Same effective-book formula as the backend (handles one-sided books near expiry). */
function impliedUp(f: any): number | null {
  const bids = [f.up_bid, f.down_ask != null ? 1 - f.down_ask : null].filter((x) => x != null) as number[];
  const asks = [f.up_ask, f.down_bid != null ? 1 - f.down_bid : null].filter((x) => x != null) as number[];
  const b = bids.length ? Math.max(...bids) : null, a = asks.length ? Math.min(...asks) : null;
  if (b != null && a != null) return (a + b) / 2;
  return b ?? a ?? null;
}
const ASSETS = ["", "BTC", "ETH", "SOL", "XRP", "DOGE", "HYPE", "BNB"];

function ReplayInner() {
  const sp = useSearchParams();
  const [asset, setAsset] = useState("");
  const [withTrades, setWithTrades] = useState(false);
  const [id, setId] = useState<number | null>(sp.get("id") ? Number(sp.get("id")) : null);
  const { data: list } = usePoll<any[]>(`/api/replay/markets${qs({ asset, with_trades: withTrades || undefined })}`, 30000);
  const [d, setD] = useState<any>(null);
  const [i, setI] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(5);
  const timer = useRef<any>(null);

  useEffect(() => {
    if (!id && list?.length) setId(list[0].id);
  }, [list, id]);
  useEffect(() => {
    if (!id) return;
    setD(null); setI(0); setPlaying(false);
    api(`/api/replay/${id}`).then(setD);
  }, [id]);
  const frames = d?.frames || [];
  useEffect(() => {
    clearInterval(timer.current);
    if (!playing || !frames.length) return;
    timer.current = setInterval(() => setI((x) => (x + 1 >= frames.length ? (setPlaying(false), x) : x + 1)), 1000 / speed);
    return () => clearInterval(timer.current);
  }, [playing, speed, frames.length]);

  const f = frames[i] || {};
  const upTo = frames.slice(0, i + 1);
  const series = useMemo(() => [
    { name: "UP implied", color: "#22c55e", data: upTo.map((x: any) => ({ time: x.ts, value: impliedUp(x) })) },
    { name: "DOWN implied", color: "#ef4444", data: upTo.map((x: any) => { const u = impliedUp(x); return { time: x.ts, value: u == null ? null : 1 - u }; }) },
    { name: "UP ask", color: "#22c55e", dashed: true, width: 1, data: upTo.map((x: any) => ({ time: x.ts, value: x.up_ask })) },
    { name: "DOWN ask", color: "#ef4444", dashed: true, width: 1, data: upTo.map((x: any) => ({ time: x.ts, value: x.down_ask })) },
  ], [upTo.length, d]); // eslint-disable-line react-hooks/exhaustive-deps
  const under = useMemo(() => [
    { name: "spot", color: "#38bdf8", data: upTo.map((x: any) => ({ time: x.ts, value: x.spot })) },
    { name: "est 60s TWAP", color: "#a78bfa", width: 1, data: upTo.map((x: any) => ({ time: x.ts, value: x.twap60 })) },
    { name: "threshold", color: "#f59e0b", dashed: true, width: 1, data: upTo.map((x: any) => ({ time: x.ts, value: x.open_price })) },
  ], [upTo.length, d]); // eslint-disable-line react-hooks/exhaustive-deps
  const liq = useMemo(() => [
    { name: "UP ask liq $", color: "#22c55e", width: 1, data: upTo.map((x: any) => ({ time: x.ts, value: x.up_ask_liq })) },
    { name: "DOWN ask liq $", color: "#ef4444", width: 1, data: upTo.map((x: any) => ({ time: x.ts, value: x.down_ask_liq })) },
  ], [upTo.length, d]); // eslint-disable-line react-hooks/exhaustive-deps
  const markers: Marker[] = (d?.trades || []).filter((t: any) => (t.entry_ts || t.created_ts) <= (f.ts || 0))
    .map((t: any) => ({ time: t.entry_ts || t.created_ts, label: `${t.strategy_key} ${t.outcome}`, color: t.outcome === "UP" ? "#22c55e" : "#ef4444", position: "belowBar", shape: "arrowUp" }));
  const upProb = impliedUp(f);
  const fav = upProb == null || upProb === 0.5 ? null : upProb > 0.5 ? "UP" : "DOWN";
  const knownTrades = (d?.trades || []).filter((t: any) => (t.entry_ts || t.created_ts) <= (f.ts || 0));
  return (
    <div className="page space-y-3">
      <Panel title="Market replay" right={<>
        <Select value={asset} onChange={setAsset} options={ASSETS.map((a) => ({ value: a, label: a || "All assets" }))} />
        <label className="flex items-center gap-1 text-2xs text-dim"><input type="checkbox" checked={withTrades} onChange={(e) => setWithTrades(e.target.checked)} />with trades</label>
        <Select className="w-72" value={id ?? ""} onChange={(v) => setId(Number(v))} options={(list || []).map((m) => ({ value: m.id, label: `${m.slug} ${m.winner ? `→${m.winner}` : ""} ${m.trades ? `(${m.trades} tx)` : ""}` }))} />
      </>}>
        {!d ? <div className="text-faint">{list?.length === 0 ? "No recorded markets yet." : "Loading…"}</div> : (
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              <Button size="sm" onClick={() => setI(0)}><SkipBack size={12} /></Button>
              <Button size="sm" tone="primary" onClick={() => setPlaying(!playing)}>{playing ? <><Pause size={12} />Pause</> : <><Play size={12} />Play</>}</Button>
              <Button size="sm" onClick={() => setI(frames.length - 1)}><SkipForward size={12} /></Button>
              {SPEEDS.map((s) => <Button key={s} size="sm" tone={speed === s ? "primary" : "default"} onClick={() => setSpeed(s)}>{s}x</Button>)}
              <input type="range" min={0} max={Math.max(0, frames.length - 1)} value={i} onChange={(e) => setI(Number(e.target.value))} className="mx-2 min-w-[200px] flex-1" />
              <span className="mono text-xs">{ts(f.ts, false)} · T-{num(f.secs, 1)}s · {i + 1}/{frames.length}</span>
              <Pill kind="SIMULATED">REPLAY</Pill>
            </div>
            <div className="grid grid-cols-1 gap-3 xl:grid-cols-[1fr_340px]">
              <div className="space-y-3">
                <TimeChart title="replay_prices" height={240} series={series} markers={markers} fit />
                <TimeChart title="replay_underlying" height={160} series={under} fit />
                <TimeChart title="replay_liquidity" height={120} series={liq} fit />
              </div>
              <div className="space-y-3">
                <Panel title="State at this second (what the bot knew)">
                  <KV rows={[["Seconds remaining", num(f.secs, 2)], ["UP bid / ask", `${price(f.up_bid)} / ${price(f.up_ask)}`],
                    ["DOWN bid / ask", `${price(f.down_bid)} / ${price(f.down_ask)}`],
                    ["UP spread / DOWN spread", `${price(f.up_ask != null && f.up_bid != null ? f.up_ask - f.up_bid : null)} / ${price(f.down_ask != null && f.down_bid != null ? f.down_ask - f.down_bid : null)}`],
                    ["Implied UP prob", pct(upProb)],
                    ["Favourite", fav || "—"], ["Spot", spot(f.spot)], ["Threshold", spot(f.open_price)], ["Distance", `${num(f.dist_bps, 2)} bp`],
                    ["Mom 10s", num(f.mom_10s, 4)], ["Data quality", `${f.book_ok ? "book ✓" : "book ✗"} ${f.spot_ok ? "spot ✓" : "spot ✗"}`]]} />
                </Panel>
                <Panel title="Ask depth (top 5)">
                  <div className="grid grid-cols-2 gap-2 text-2xs">
                    {(["up_asks", "down_asks"] as const).map((k) => (
                      <div key={k}><div className={clsx("mb-1 font-semibold", k === "up_asks" ? "text-up" : "text-down")}>{k === "up_asks" ? "UP" : "DOWN"}</div>
                        {(f[k] || []).map((l: any, j: number) => <div key={j} className="mono flex justify-between"><span>{price(l[0])}</span><span className="text-dim">{num(l[1], 0)}</span></div>)}</div>
                    ))}
                  </div>
                </Panel>
                <Panel title="Settlement">
                  <KV rows={[["Final winner", d.resolution?.winner || d.market.winner || "pending"], ["Open ref", spot(d.resolution?.open_price)],
                    ["Settle ref", spot(d.resolution?.close_price)], ["Official", String(d.resolution?.official ?? false)]]} />
                </Panel>
              </div>
            </div>
            <Panel title="Simulated trades in this market">
              <DataTable rows={knownTrades} empty="No trades placed up to this point." cols={[
                { key: "id", label: "Tx", render: (r: any) => <a href={`/transactions/view/?id=${r.id}`} className="text-info">{r.id}</a> },
                { key: "account", label: "Account", align: "left" }, { key: "outcome", label: "Side", align: "center" },
                { key: "entry_secs_remaining", label: "Entry T-", render: (r: any) => num(r.entry_secs_remaining, 1) },
                { key: "entry_price", label: "Entry", render: (r: any) => price(r.entry_price) },
                { key: "filled_shares", label: "Shares", render: (r: any) => num(r.filled_shares, 2) },
                { key: "status", label: "Status", align: "center" }, { key: "net_profit", label: "Net", render: (r: any) => num(r.net_profit, 4) },
                { key: "why", label: "Decision reasons", align: "left", render: (r: any) => <span className="text-2xs text-dim">{r.decision?.reasons ? `fav ${pct(r.decision.reasons.fav_prob)} · ask ${r.decision.reasons.dog_ask} · liq $${num(r.decision.reasons.liq_usd, 1)} · dist ${num(r.decision.reasons.dist_bps, 2)}bp` : ""}</span> },
              ]} />
            </Panel>
          </div>
        )}
      </Panel>
    </div>
  );
}

export default function ReplayPage() {
  return <Suspense><ReplayInner /></Suspense>;
}
