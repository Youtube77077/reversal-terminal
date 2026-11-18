"use client";
import clsx from "clsx";
import { usePoll } from "@/lib/api";

const NAMES: Record<string, string> = { BTC: "Bitcoin", ETH: "Ethereum", SOL: "Solana", XRP: "XRP", DOGE: "Dogecoin", HYPE: "Hyperliquid", BNB: "BNB" };

/** Show a dollar amount with sensible precision for any coin (BTC $53 vs DOGE $0.0001). */
function money(v: number | null | undefined, ref: number) {
  if (v == null || !isFinite(v)) return "—";
  const d = ref >= 1000 ? 2 : ref >= 10 ? 3 : ref >= 1 ? 4 : 5;
  return "$" + v.toFixed(d);
}
const pc = (v: number | null | undefined, d = 3) => (v == null ? "—" : `${v.toFixed(d)}%`);

/** "How each coin moves" — learned from every recorded 5-minute market. */
export default function CoinMoves() {
  const { data } = usePoll<any>("/api/analytics/movement", 300000);
  const assets = Object.entries<any>(data?.assets || {});
  return (
    <section className="panel animate-rise p-5">
      <div className="text-[19px] font-bold tracking-tight">How each coin moves in 5 minutes</div>
      <p className="mt-1 text-[13px] leading-relaxed text-dim">
        Learned from {data?.markets ?? "…"} recorded markets and updated every 5 minutes. Every coin has a different price, so
        moves are shown in dollars <b>and</b> in % — the % lets you compare coins. “Normal” = what happens in half of all
        markets; “Big” = only 1 in 10 markets moves more than this.
      </p>
      <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-2 2xl:grid-cols-4">
        {assets.map(([a, x]) => (
          <div key={a} className="rounded-3xl bg-panel2/60 p-4">
            <div className="flex items-baseline justify-between">
              <div><span className="text-[18px] font-bold">{a}</span> <span className="text-[12px] text-faint">{NAMES[a]}</span></div>
              <span className="num text-[13px] text-dim">≈ {money(x.price, x.price)}</span>
            </div>
            <div className="mt-3 grid grid-cols-2 gap-2">
              <Stat label="Normal 5-min move" main={money(x.move_5m_usd?.median, x.price)} sub={pc(x.move_5m_pct?.median)} />
              <Stat label="Big 5-min move (1 in 10)" main={money(x.move_5m_usd?.p90, x.price)} sub={pc(x.move_5m_pct?.p90)} />
              <Stat label="Normal move, last 60s" main={money(x.last_60s_usd?.median, x.price)} sub={pc(x.last_60s_pct?.median)} />
              <Stat label="Normal move, last 10s" main={money(x.last_10s_usd?.median, x.price)} sub={`big: ${money(x.last_10s_usd?.p90, x.price)}`} />
            </div>
            <div className="mt-3 space-y-1.5 text-[13px]">
              <Row k="Crosses the price to beat in the last 60s" v={`${Math.round(x.pct_markets_crossing_last_60s * 100)}% of markets`} />
              <Row k="…in the last 2 minutes" v={`${Math.round(x.pct_markets_crossing_last_120s * 100)}% (avg ${x.crosses_last_120s_avg.toFixed(1)} times)`} />
              <Row k="UP won" v={`${Math.round(x.up_win_rate * 100)}%`} tone={Math.abs(x.up_win_rate - 0.5) > 0.06 ? "warn" : undefined} />
              <Row k="Model correction learned" v={`×${x.sigma_scale.toFixed(2)}`} />
            </div>
          </div>
        ))}
      </div>
      <div className="mt-4 rounded-2xl bg-panel2/60 p-4 text-[13px] leading-relaxed text-dim">
        <b className="text-ink">What this tells the bots:</b> about 1 in 5 markets still crosses the price to beat in the last minute,
        so the last minute really can flip — but rarely by much. <b className="text-ink">Model correction</b> = how much more
        the coin moved at the end than the flip-chance model expected (×1.0 = exactly right). Every coin moved 1.5–1.9× more.
        Turning that correction on for trading was tested and made Smart future trading <i>worse</i> ($100 → $121 instead of
        $216), because the strategy's rules are already tuned on real results — so the bots keep their tested settings and this
        is shown for learning.
      </div>
    </section>
  );
}

function Stat({ label, main, sub }: { label: string; main: string; sub?: string }) {
  return (
    <div className="rounded-2xl bg-panel/70 px-3 py-2">
      <div className="text-[11px] text-dim">{label}</div>
      <div className="num text-[17px] font-bold">{main}</div>
      {sub && <div className="num text-[11px] text-faint">{sub}</div>}
    </div>
  );
}

function Row({ k, v, tone }: { k: string; v: string; tone?: "warn" }) {
  return (
    <div className="flex justify-between gap-3"><span className="text-dim">{k}</span>
      <span className={clsx("num shrink-0 font-semibold", tone === "warn" && "text-warn")}>{v}</span></div>
  );
}
