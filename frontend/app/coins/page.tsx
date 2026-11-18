"use client";
import clsx from "clsx";
import { ChevronLeft } from "lucide-react";
import { useState } from "react";
import { usePoll } from "@/lib/api";
import { useLive } from "@/lib/live";

const COINS = ["BTC", "ETH", "SOL", "XRP", "DOGE", "HYPE", "BNB"];
const NAMES: Record<string, string> = { BTC: "Bitcoin", ETH: "Ethereum", SOL: "Solana", XRP: "XRP", DOGE: "Dogecoin", HYPE: "Hyperliquid", BNB: "BNB" };

const dp = (ref: number) => (ref >= 1000 ? 2 : ref >= 10 ? 3 : ref >= 1 ? 4 : 5);
const usd = (v: number | null | undefined, ref: number, sign = false) =>
  v == null || !isFinite(v) ? "—" : `${sign && v > 0 ? "+" : v < 0 ? "−" : ""}$${Math.abs(v).toFixed(dp(ref))}`;
const pc = (v: number | null | undefined, d = 3, sign = false) =>
  v == null || !isFinite(v) ? "—" : `${sign && v > 0 ? "+" : ""}${v.toFixed(d)}%`;
const pct0 = (v: number | null | undefined, d = 1) => (v == null ? "—" : `${(v * 100).toFixed(d)}%`);
const time = (ms: number) => new Date(ms).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

export default function CoinsPage() {
  const { data } = usePoll<any>("/api/analytics/movement", 30000);   // stats refresh every minute on the server
  const [coin, setCoin] = useState<string>("ALL");
  const A = data?.assets || {};
  return (
    <div className="page max-w-[1200px] space-y-3">
      {coin !== "ALL" && (
        <div className="flex items-center gap-2">
          <button onClick={() => setCoin("ALL")} className="flex items-center gap-1 rounded-full bg-panel2 py-2 pl-2 pr-4 text-[14px] font-bold">
            <ChevronLeft size={18} />All coins</button>
          <div className="-mx-1 flex flex-1 gap-2 overflow-x-auto px-1">
            {COINS.map((c) => (
              <button key={c} onClick={() => setCoin(c)}
                className={clsx("shrink-0 rounded-full px-3.5 py-2 text-[13px] font-bold", coin === c ? "bg-ink text-bg" : "bg-panel2 text-dim")}>{c}</button>
            ))}
          </div>
        </div>
      )}
      <p className="px-1 text-[12px] text-faint">
        {data ? `Learned from ${data.markets} recorded markets (last 30 days) · updated ${time(data.generated_ts)} · statistics refresh every minute, live prices every second` : "Loading…"}
      </p>
      {coin === "ALL" ? <><Grid A={A} onPick={setCoin} /><Compare A={A} onPick={setCoin} /></>
        : A[coin] ? <Coin a={coin} x={A[coin]} /> : <div className="panel p-6 text-dim">No data yet for {coin}.</div>}
    </div>
  );
}


/* --------------------------------------------------------------- overview grid (brief) */
function Grid({ A, onPick }: { A: any; onPick: (c: string) => void }) {
  const { tick } = useLive();
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
      {COINS.filter((c) => A[c]).map((c) => {
        const x = A[c]; const s = tick?.assets?.[c]; const ref = x.price;
        const f60 = (x.flip_rates || []).find((r: any) => r.t === 60);
        return (
          <button key={c} onClick={() => onPick(c)} className="panel animate-rise p-4 text-left transition active:scale-[.98]">
            <div className="flex items-baseline justify-between">
              <div><span className="text-[19px] font-bold">{c}</span> <span className="text-[12px] text-faint">{NAMES[c]}</span></div>
              <span className="num text-[13px] font-semibold">{usd(s?.spot ?? ref, ref)}</span>
            </div>
            <div className="mt-1 flex items-center gap-2 text-[12px]">
              {s ? <>
                <span className="rounded-full bg-panel2 px-2 py-0.5 font-semibold">{Math.max(0, Math.round(s.secs_remaining))}s left</span>
                {s.favourite && <span className={clsx("font-bold", s.favourite === "UP" ? "text-up" : "text-down")}>{s.favourite} {pct0(s.fav_prob, 0)}</span>}
                {s.dist_abs != null && <span className="num text-faint">{usd(s.dist_abs, ref, true)} vs line</span>}
              </> : <span className="text-faint">waiting for live market…</span>}
            </div>
            <div className="mt-3 grid grid-cols-3 gap-2">
              <Mini label="Normal 5-min move" v={pc(x.move_5m_pct_full?.median)} />
              <Mini label="Big move (1 in 10)" v={pc(x.move_5m_pct_full?.p90)} />
              <Mini label="Crosses in last 60s" v={pct0(x.pct_markets_crossing_last_60s, 0)} />
              <Mini label="UP won" v={pct0(x.up_win_rate, 0)} />
              <Mini label="Fav. lost at 60s" v={f60 ? pct0(f60.real) : "—"} sub={f60 ? `priced ${pct0(f60.polymarket)}` : undefined} />
              <Mini label="Comebacks from far" v={pct0(x.details?.comeback_from_far_at_60s?.rate)} />
            </div>
            <div className="mt-2 text-right text-[12px] font-semibold text-accent">All details →</div>
          </button>
        );
      })}
    </div>
  );
}

function Mini({ label, v, sub }: { label: string; v: string; sub?: string }) {
  return (
    <div className="rounded-xl bg-panel2/60 px-2.5 py-2">
      <div className="text-[10px] leading-tight text-dim">{label}</div>
      <div className="num text-[15px] font-bold">{v}</div>
      {sub && <div className="num text-[10px] text-faint">{sub}</div>}
    </div>
  );
}

/* --------------------------------------------------------------- all coins side by side */
function Compare({ A, onPick }: { A: any; onPick: (c: string) => void }) {
  const t60 = (x: any) => (x.flip_rates || []).find((r: any) => r.t === 60);
  return (
    <section className="panel p-5">
      <h2 className="text-[19px] font-bold">All 7 coins side by side</h2>
      <p className="mt-1 text-[13px] text-dim">Moves in % so coins with very different prices can be compared. Tap a coin for everything about it.</p>
      <div className="mt-3 overflow-x-auto">
        <table className="w-full min-w-[760px] text-[13px]">
          <thead className="text-left text-[11px] uppercase tracking-wide text-faint">
            <tr><th className="py-2">Coin</th><th>Normal 5-min move</th><th>Big (1 in 10)</th><th>Normal last 60s</th>
              <th>Crosses line, last 60s</th><th>UP won</th><th>Fav. lost at T-60</th><th>Polymarket said</th><th>Markets</th></tr>
          </thead>
          <tbody>
            {COINS.filter((c) => A[c]).map((c) => {
              const x = A[c]; const f = t60(x);
              return (
                <tr key={c} onClick={() => onPick(c)} className="cursor-pointer border-t border-line/60 hover:bg-panel2/50">
                  <td className="py-2.5 font-bold">{c} <span className="font-normal text-faint">{NAMES[c]}</span></td>
                  <td className="num">{pc(x.move_5m_pct_full?.median)}</td>
                  <td className="num">{pc(x.move_5m_pct_full?.p90)}</td>
                  <td className="num">{pc(x.last_60s_pct?.median)}</td>
                  <td className="num">{pct0(x.pct_markets_crossing_last_60s, 0)}</td>
                  <td className="num">{pct0(x.up_win_rate, 0)}</td>
                  <td className="num">{f ? pct0(f.real) : "—"}</td>
                  <td className="num text-dim">{f ? pct0(f.polymarket) : "—"}</td>
                  <td className="num text-dim">{x.markets}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <Help>
        <b>Normal</b> = half of all markets moved less than this. <b>Big</b> = only 1 in 10 moved more. <b>Crosses line</b> = the price went
        from one side of the price to beat to the other at least once in the last minute — that's how often a late flip is possible.
        <b> Fav. lost at T-60</b> = with 60 seconds left, how often the side Polymarket favoured still lost, vs what Polymarket's price said.
      </Help>
    </section>
  );
}

/* --------------------------------------------------------------- one coin, everything */
function Coin({ a, x }: { a: string; x: any }) {
  const { tick } = useLive();
  const s = tick?.assets?.[a];
  const ref = x.price;
  const m = x.move_5m_usd_full || {};
  const mp = x.move_5m_pct_full || {};
  return (
    <>
      {/* live now */}
      <section className="panel p-5">
        <div className="flex items-baseline justify-between">
          <h2 className="text-[22px] font-bold">{a} <span className="text-[14px] font-normal text-faint">{NAMES[a]}</span></h2>
          <span className="num text-dim">≈ {usd(ref, ref)}</span>
        </div>
        {s ? (
          <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
            <Tile label="Time left now" v={`${Math.max(0, Math.round(s.secs_remaining))}s`} />
            <Tile label="Price to beat" v={usd(s.open_price, ref)} />
            <Tile label="Price now" v={usd(s.spot, ref)} sub={s.dist_abs != null ? `${usd(s.dist_abs, ref, true)} from the line` : undefined} />
            <Tile label="Polymarket favourite" v={s.favourite ? `${s.favourite} ${pct0(s.fav_prob, 0)}` : "—"} tone={s.favourite === "UP" ? "up" : s.favourite === "DOWN" ? "down" : undefined} />
            <Tile label="UP share price" v={s.up_ask != null ? `${Math.round(s.up_ask * 100)}¢` : "—"} sub={s.up_bid != null ? `sell ${Math.round(s.up_bid * 100)}¢` : undefined} />
            <Tile label="DOWN share price" v={s.down_ask != null ? `${Math.round(s.down_ask * 100)}¢` : "—"} sub={s.down_bid != null ? `sell ${Math.round(s.down_bid * 100)}¢` : undefined} />
            <Tile label="Distance from line" v={s.dist_bps != null ? `${s.dist_bps >= 0 ? "+" : ""}${(s.dist_bps / 100).toFixed(3)}%` : "—"} />
            <Tile label="Last 10s move" v={usd(s.mom_10s, ref, true)} tone={s.mom_10s > 0 ? "up" : s.mom_10s < 0 ? "down" : undefined} />
          </div>
        ) : <p className="mt-2 text-[13px] text-dim">Waiting for the live market…</p>}
      </section>

      {/* how much it moves */}
      <section className="panel p-5">
        <h3 className="text-[17px] font-bold">How much {a} moves in a 5-minute market</h3>
        <p className="mt-1 text-[13px] text-dim">Measured the way Polymarket settles: the 60-second average at the end vs the 60-second average at the start (the price to beat).</p>
        <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-5">
          <Tile label="Small (1 in 4 less)" v={usd(m.p25, ref)} sub={pc(mp.p25)} />
          <Tile label="Normal (half less)" v={usd(m.median, ref)} sub={pc(mp.median)} big />
          <Tile label="Larger (1 in 4 more)" v={usd(m.p75, ref)} sub={pc(mp.p75)} />
          <Tile label="Big (1 in 10 more)" v={usd(m.p90, ref)} sub={pc(mp.p90)} />
          <Tile label="Record" v={usd(m.max, ref)} sub={pc(mp.max)} />
        </div>
        <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-4">
          <Tile label="Biggest jump up" v={usd(x.biggest_up_usd, ref, true)} tone="up" />
          <Tile label="Biggest drop" v={usd(x.biggest_down_usd, ref, true)} tone="down" />
          <Tile label="Normal high–low swing" v={usd(x.range_5m_usd?.median, ref)} sub={pc(x.range_5m_pct?.median)} />
          <Tile label="Big high–low swing" v={usd(x.range_5m_usd?.p90, ref)} sub={pc(x.range_5m_pct?.p90)} />
        </div>
        <Hist h={x.hist} />
        <Help>The bars show how often each size of move happened: left = finished DOWN by that much, right = finished UP. Tall bars near the middle = most markets end close to the price to beat.</Help>
      </section>

      {/* end of the market */}
      <section className="panel p-5">
        <h3 className="text-[17px] font-bold">The end of the market (where reversals happen)</h3>
        <div className="mt-3 overflow-x-auto">
          <table className="w-full min-w-[520px] text-[13px]">
            <thead className="text-left text-[11px] uppercase tracking-wide text-faint"><tr><th className="py-2">Last…</th><th>Normal move</th><th>Big move (1 in 10)</th></tr></thead>
            <tbody>
              {[["2 minutes", "last_120s"], ["60 seconds", "last_60s"], ["30 seconds", "last_30s"], ["10 seconds", "last_10s"]].map(([l, k]) => (
                <tr key={k} className="border-t border-line/60">
                  <td className="py-2 font-semibold">{l}</td>
                  <td className="num">{usd(x[`${k}_usd`]?.median, ref)} <span className="text-faint">{pc(x[`${k}_pct`]?.median)}</span></td>
                  <td className="num">{usd(x[`${k}_usd`]?.p90, ref)} <span className="text-faint">{pc(x[`${k}_pct`]?.p90)}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
          <Tile label="Crossed the line in last 60s" v={pct0(x.pct_markets_crossing_last_60s, 0)} sub="of markets" />
          <Tile label="Crossed in last 2 min" v={pct0(x.pct_markets_crossing_last_120s, 0)} sub={`avg ${x.crosses_last_120s_avg?.toFixed(1)} times`} />
          <Tile label="Normal price wiggle" v={x.vol_1s_bps != null ? `${x.vol_1s_bps.toFixed(2)} bp/s` : "—"} sub="1 bp = 0.01%" />
          <Tile label="Model correction learned" v={`×${x.sigma_scale?.toFixed(2)}`} sub="1.0 = model exactly right" />
        </div>
      </section>


      {/* lots more detail */}
      <Details a={a} x={x} />
      {/* flip odds */}
      <section className="panel p-5">
        <h3 className="text-[17px] font-bold">How often the favourite lost — real vs Polymarket's price</h3>
        <div className="mt-3 overflow-x-auto">
          <table className="w-full min-w-[520px] text-[13px]">
            <thead className="text-left text-[11px] uppercase tracking-wide text-faint"><tr><th className="py-2">Time left</th><th>Really lost</th><th>Polymarket said</th><th>What it means</th><th>Markets</th></tr></thead>
            <tbody>
              {(x.flip_rates || []).map((r: any) => {
                const diff = r.real - r.polymarket;
                return (
                  <tr key={r.t} className="border-t border-line/60">
                    <td className="py-2 font-semibold">{r.t >= 60 ? `${r.t / 60 === Math.round(r.t / 60) ? r.t / 60 + " min" : r.t + "s"}` : `${r.t}s`}</td>
                    <td className="num font-bold">{pct0(r.real)}</td>
                    <td className="num text-dim">{pct0(r.polymarket)}</td>
                    <td className={clsx("text-[12px]", r.n < 30 ? "text-faint" : diff > 0.01 ? "text-warn" : diff < -0.01 ? "text-up" : "text-dim")}>
                      {r.n < 30 ? "too few markets yet" : diff > 0.01 ? "flips more than priced — underdog cheap" : diff < -0.01 ? "flips less than priced — favourite better" : "about fair"}</td>
                    <td className="num text-faint">{r.n}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      {/* wins, streaks, hours */}
      <section className="panel p-5">
        <h3 className="text-[17px] font-bold">Wins, streaks and time of day</h3>
        <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
          <Tile label="UP won" v={pct0(x.up_win_rate, 0)} tone={x.up_win_rate > 0.5 ? "up" : "down"} sub={`DOWN ${pct0(1 - x.up_win_rate, 0)}`} />
          <Tile label="Longest UP streak" v={`${x.streak_up_max} in a row`} />
          <Tile label="Longest DOWN streak" v={`${x.streak_down_max} in a row`} />
          <Tile label="Our settlement check" v={pct0(x.rule_agreement, 1)} sub="matches the official winner" />
        </div>
        <div className="mt-4 text-[12px] font-semibold text-dim">Normal 5-min move by hour of day (your time)</div>
        <Hours rows={x.by_hour || []} />
      </section>

      {/* recent markets */}
      <section className="panel p-5">
        <h3 className="text-[17px] font-bold">Latest {a} markets</h3>
        <div className="mt-3 overflow-x-auto">
          <table className="w-full min-w-[620px] text-[13px]">
            <thead className="text-left text-[11px] uppercase tracking-wide text-faint">
              <tr><th className="py-2">Start</th><th>Price to beat</th><th>Final 60s average</th><th>Move</th><th>Swing</th><th>Line crosses (2 min)</th><th>Winner</th></tr></thead>
            <tbody>
              {(x.recent || []).map((r: any) => (
                <tr key={r.id} className="border-t border-line/60">
                  <td className="py-2">{time(r.open_ts)}</td>
                  <td className="num">{usd(r.price_to_beat, ref)}</td>
                  <td className="num">{usd(r.final_avg, ref)}</td>
                  <td className={clsx("num", r.move >= 0 ? "text-up" : "text-down")}>{usd(r.move, ref, true)} <span className="text-faint">{pc(r.move_pct, 3, true)}</span></td>
                  <td className="num text-dim">{usd(r.range, ref)}</td>
                  <td className="num">{r.crosses_last_120s}</td>
                  <td className={clsx("font-bold", r.winner === "UP" ? "text-up" : "text-down")}>{r.winner}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}


/* --------------------------------------------------------------- the deep dive */
function Details({ a, x }: { a: string; x: any }) {
  const d = x.details || {};
  const dist = d.dist_from_line_pct || {};
  const fl = d.price_side_flipped_after || {};
  return (
    <section className="panel p-5">
      <h3 className="text-[17px] font-bold">More about how {a} behaves</h3>
      <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Tile label="Average 5-min move" v={pc(d.avg_move_pct)} sub={`spread of moves ±${pc(d.std_move_pct)}`} />
        <Tile label="Average UP finish" v={pc(d.avg_up_move_pct, 3, true)} tone="up" />
        <Tile label="Average DOWN finish" v={pc(d.avg_down_move_pct, 3, true)} tone="down" />
        <Tile label="Time spent above the line" v={pct0(d.time_above_line_avg, 0)} sub="average per market" />
        <Tile label="Close calls" v={pct0(d.close_calls_pct, 1)} sub="finished within 0.01% of the line" />
        <Tile label="Photo finishes" v={pct0(d.very_close_calls_pct, 1)} sub="within 0.003%" />
        <Tile label="Lead changes per market" v={d.lead_changes_avg != null ? d.lead_changes_avg.toFixed(1) : "—"} sub={`record ${d.lead_changes_max ?? "—"}`} />
        <Tile label="Never changed leader" v={pct0(d.no_lead_change_pct, 0)} sub="one side the whole time" />
        <Tile label="Highest point (normal)" v={pc(d.run_up_pct?.median, 3, true)} sub={`big: ${pc(d.run_up_pct?.p90, 3, true)}`} tone="up" />
        <Tile label="Lowest point (normal)" v={pc(d.run_down_pct?.median, 3, true)} sub={`big: ${pc(d.run_down_pct?.p10, 3, true)}`} tone="down" />
        <Tile label="Comebacks from far at 60s" v={pct0(d.comeback_from_far_at_60s?.rate)} sub={`of ${d.comeback_from_far_at_60s?.n ?? 0} markets clearly decided`} />
        <Tile label="UP won, recent" v={pct0(d.up_rate_last_12, 0)} sub={`last 12 · last 48: ${pct0(d.up_rate_last_48, 0)} · last 144: ${pct0(d.up_rate_last_144, 0)}`} />
      </div>
      <div className="mt-4 overflow-x-auto">
        <table className="w-full min-w-[520px] text-[13px]">
          <thead className="text-left text-[11px] uppercase tracking-wide text-faint">
            <tr><th className="py-2">Time left</th><th>Normal distance from line</th><th>Far (1 in 10)</th><th>Price still switched side after this</th></tr></thead>
          <tbody>
            {["T-120", "T-60", "T-30", "T-10"].map((k) => (
              <tr key={k} className="border-t border-line/60">
                <td className="py-2 font-semibold">{k.replace("T-", "")}s</td>
                <td className="num">{pc(dist[k]?.median)}</td>
                <td className="num text-dim">{pc(dist[k]?.p90)}</td>
                <td className="num font-bold">{pct0(fl[k])}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Help>
        <b>Lead change</b> = the price crossed the line to the other side. <b>Close call</b> = the end average finished almost exactly on the
        line. <b>Comebacks from far</b> = with 60 seconds left the price was further from the line than a normal last-minute move, yet it
        still finished on the other side — this is how rare real late reversals are. <b>Price still switched side</b> = how often the side the
        price was on at that moment was NOT the final side.
      </Help>
    </section>
  );
}

/* --------------------------------------------------------------- small pieces */
function Tile({ label, v, sub, tone, big }: { label: string; v: string; sub?: string; tone?: "up" | "down"; big?: boolean }) {
  return (
    <div className={clsx("rounded-2xl px-3 py-2.5", big ? "bg-cash/15" : "bg-panel2/60")}>
      <div className="text-[11px] text-dim">{label}</div>
      <div className={clsx("num text-[17px] font-bold", tone === "up" && "text-up", tone === "down" && "text-down")}>{v}</div>
      {sub && <div className="num text-[11px] text-faint">{sub}</div>}
    </div>
  );
}

function Hist({ h }: { h: any }) {
  if (!h?.counts?.length) return null;
  const max = Math.max(...h.counts, 1);
  return (
    <div className="mt-4">
      <div className="flex h-28 items-end gap-1">
        {h.counts.map((c: number, i: number) => {
          const mid = (h.edges[i] + h.edges[i + 1]) / 2;
          return <div key={i} title={`${mid.toFixed(3)}%: ${c} markets`} className={clsx("flex-1 rounded-t-md", mid >= 0 ? "bg-up/70" : "bg-down/70")} style={{ height: `${(c / max) * 100}%` }} />;
        })}
      </div>
      <div className="mt-1 flex justify-between text-[10px] text-faint"><span>{h.edges[0].toFixed(2)}% (down)</span><span>0</span><span>+{h.edges[h.edges.length - 1].toFixed(2)}% (up)</span></div>
    </div>
  );
}

function Hours({ rows }: { rows: any[] }) {
  if (!rows.length) return null;
  const off = -new Date().getTimezoneOffset() / 60;
  const max = Math.max(...rows.map((r) => r.move_pct), 0.0001);
  const loc = rows.map((r) => ({ ...r, h: (r.hour + off + 24) % 24 })).sort((a, b) => a.h - b.h);
  return (
    <div className="mt-2">
      <div className="flex h-24 items-end gap-1">
        {loc.map((r) => (
          <div key={r.hour} className="flex flex-1 flex-col items-center justify-end" title={`${r.h}:00 — ${r.move_pct.toFixed(3)}% (${r.n} markets)`}>
            <div className={clsx("w-full rounded-t-md", r.n < 6 ? "bg-panel2" : "bg-info/70")} style={{ height: `${(r.move_pct / max) * 100}%` }} />
          </div>
        ))}
      </div>
      <div className="mt-1 flex gap-1 text-[10px] text-faint">{loc.map((r) => <span key={r.hour} className="flex-1 text-center">{r.h}</span>)}</div>
      <Help>Taller = bigger normal move in that hour. Grey bars = fewer than 6 markets so far (not reliable yet). More hours fill in as the server keeps recording.</Help>
    </div>
  );
}

function Help({ children }: { children: React.ReactNode }) {
  return <p className="mt-3 rounded-2xl bg-panel2/50 p-3 text-[12.5px] leading-relaxed text-dim">{children}</p>;
}
