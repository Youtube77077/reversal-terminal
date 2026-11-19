"use client";
import clsx from "clsx";
import { useState } from "react";
import WalletBar from "@/components/WalletBar";
import { usePoll } from "@/lib/api";
import { useWallet } from "@/lib/wallet";

const money = (v: number | null | undefined, sign = true) =>
  v == null ? "—" : `${sign && v > 0 ? "+" : v < 0 ? "−" : ""}$${Math.abs(v).toFixed(2)}`;
const p = (v: number | null | undefined, d = 0) => (v == null ? "—" : `${(v * 100).toFixed(d)}%`);
const c = (v: number | null | undefined) => (v == null ? "—" : `${(v * 100).toFixed(1)}¢`);
const t = (ms: number) => new Date(ms).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });

export default function ReportPage() {
  const { wallet } = useWallet();
  const [mode, setMode] = useState<"paper" | "live">("paper");
  const acct = mode === "live" ? wallet?.live : wallet?.paper;
  const { data: r } = usePoll<any>(acct ? `/api/accounts/${acct.id}/report` : null, 15000);
  const { data: perf } = usePoll<any>(acct ? `/api/accounts/${acct.id}/performance` : null, 30000);
  const s = r?.summary;
  return (
    <div className="page max-w-[1100px] space-y-3">
      <WalletBar />
      <div className="flex rounded-full bg-panel2 p-1 text-[14px] font-bold">
        {(["paper", "live"] as const).map((m) => (
          <button key={m} onClick={() => setMode(m)} className={clsx("flex-1 rounded-full py-2", mode === m ? "bg-ink text-bg" : "text-dim")}>
            {m === "paper" ? "Practice bot" : "Real-money bot"}</button>
        ))}
      </div>
      {acct && perf?.points?.length > 1 && <Perf perf={perf} />}
      {!acct ? <Box>This wallet has no {mode === "live" ? "real-money" : "practice"} bot yet.</Box> : !r ? <Box>Loading…</Box> : !r.trades ? (
        <Box>No finished trades yet for {wallet?.name}. {r.open_trades ? `${r.open_trades} trade(s) still open.` : ""} Signals it skipped will show here as markets finish.</Box>
      ) : (
        <>
          <section className="panel p-5">
            <h2 className="text-[19px] font-bold">{wallet?.name} — results</h2>
            <p className="text-[12px] text-faint">{t(s.first_ts)} → {t(s.last_ts)} · {r.open_trades} open now · updates every 15s</p>
            <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
              <Tile k="Profit / loss" v={money(s.pnl)} tone={s.pnl >= 0 ? "up" : "down"} big />
              <Tile k="Trades" v={`${r.trades}`} sub={`${s.wins} won · ${s.losses} lost`} />
              <Tile k="Win rate" v={p(s.win_rate)} sub={`model expected ${p(s.avg_predicted)}`} />
              <Tile k="Return on money spent" v={p(s.roi, 1)} sub={`spent ${money(s.spent, false)}`} />
              <Tile k="Average win" v={money(s.avg_win)} tone="up" />
              <Tile k="Average loss" v={money(s.avg_loss)} tone="down" />
              <Tile k="Worst dip (drawdown)" v={money(s.max_drawdown)} tone="down" sub="biggest drop from a high point" />
              <Tile k="Longest losing streak" v={`${s.longest_losing_streak} in a row`} sub={`longest winning: ${s.longest_winning_streak}`} />
              <Tile k="Fees paid" v={money(s.fees, false)} />
              <Tile k="Slippage" v={money(s.slippage)} sub={s.slippage > 0 ? "paid more than the price it decided on" : "got the same or a better price than decided"} />
              <Tile k="Fill vs decided price" v={s.avg_fill_minus_decision_price == null ? "—" : `${(s.avg_fill_minus_decision_price * 100).toFixed(2)}¢`}
                sub={`worse in ${p(s.fills_worse_than_decision_pct)} of trades`} />
              <Tile k="Current streak" v={s.current_streak > 0 ? `${s.current_streak} wins` : `${-s.current_streak} losses`} />
            </div>
            <Equity pts={r.equity} />
          </section>

          {r.calibration?.length > 0 && (
            <Table title="Is its predicted chance right? (calibration)"
              help="Each row groups trades by the win chance the bot predicted when it bought. If the bot is accurate, 'actually won' should be close to 'predicted'. Small groups are noisy."
              head={["Predicted", "Trades", "Avg predicted", "Actually won"]}
              rows={r.calibration.map((x: any) => [x.bin, x.trades, p(x.predicted, 1), <b key="a">{p(x.actual, 1)}</b>])} />
          )}
          {r.model_check_all_candidates?.length > 0 && (
            <Table title="Model check on every market it looked at (traded or not)"
              help="Uses the best moment the bot considered in each market. Compares the model's chance, the actual result and the price Polymarket charged."
              head={["Model said", "Markets", "Avg model", "Actually won", "Polymarket price"]}
              rows={r.model_check_all_candidates.map((x: any) => [x.bin, x.n, p(x.predicted, 1), <b key="a">{p(x.actual, 1)}</b>, c(x.price)])} />
          )}
          <Group title="Profit by coin" rows={r.by_coin} />
          <Group title="Profit by buy price" rows={r.by_price} />
          <Group title="Profit by time left when it bought" rows={r.by_time_left} />
          <Group title="Profit by how the trade ended" rows={r.by_exit} />

          {r.skipped && (
            <section className="panel p-5">
              <h3 className="text-[17px] font-bold">Signals it did NOT trade</h3>
              <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
                <Tile k="Markets looked at" v={`${r.skipped.markets_considered}`} sub={`traded ${r.skipped.traded}`} />
                <Tile k="Skipped" v={`${r.skipped.skipped}`} />
                <Tile k="Skipped that would have won" v={`${r.skipped.would_have_won}`} />
                <Tile k="Skipped, if $1 each" v={money(r.skipped.would_have_pnl_per_dollar_each)} tone={r.skipped.would_have_pnl_per_dollar_each >= 0 ? "up" : "down"}
                  sub="positive = it was too careful" />
              </div>
              <div className="mt-3 text-[12px] font-semibold text-dim">Most common reasons it skipped</div>
              <ul className="mt-1 space-y-1 text-[13px]">
                {r.skipped.top_reasons.map((x: any) => <li key={x.reason} className="flex justify-between gap-3"><span className="text-dim">{x.reason}</span><span className="num">{x.count}</span></li>)}
              </ul>
              <Table title="Latest near-misses" inner
                head={["Time", "Coin", "Side", "Price", "Model", "Edge", "Winner", "If $1"]}
                rows={r.skipped.near_misses.map((x: any) => [t(x.ts), x.asset, x.side ?? "—", c(x.ask), p(x.model, 1),
                  x.edge == null ? "—" : `${(x.edge * 100).toFixed(1)} pts`, x.winner ?? "—",
                  <span key="w" className={x.would_pnl > 0 ? "text-up" : "text-down"}>{money(x.would_pnl)}</span>])} />
            </section>
          )}

          <Table title="Latest trades (every detail)"
            help="Decided = the price when it chose to buy. Filled = the price it actually got. Final average vs price to beat = what decided the market (our Chainlink 60-second average)."
            head={["Time", "Coin", "Side", "Left", "Predicted", "Decided", "Filled", "Sold at", "Fees", "Result", "Price to beat", "Final avg", "Winner"]}
            rows={r.recent.map((x: any) => [t(x.ts), x.asset, x.side, x.secs_left == null ? "—" : `${Math.round(x.secs_left)}s`, p(x.predicted, 1),
              c(x.decision_price), c(x.fill_price), x.exit_price ? c(x.exit_price) : "—", money(x.fees, false),
              <b key="r" className={x.pnl > 0 ? "text-up" : "text-down"}>{money(x.pnl)}</b>,
              x.price_to_beat?.toFixed(4) ?? "—", x.final_twap?.toFixed(4) ?? "—", x.winner ?? "—"])} />
        </>
      )}
    </div>
  );
}

function Box({ children }: { children: React.ReactNode }) {
  return <div className="panel p-6 text-[14px] text-dim">{children}</div>;
}

function Tile({ k, v, sub, tone, big }: { k: string; v: string; sub?: string; tone?: "up" | "down"; big?: boolean }) {
  return (
    <div className={clsx("rounded-2xl px-3 py-2.5", big ? "bg-cash/15" : "bg-panel2/60")}>
      <div className="text-[11px] text-dim">{k}</div>
      <div className={clsx("num font-bold", big ? "text-[22px]" : "text-[17px]", tone === "up" && "text-up", tone === "down" && "text-down")}>{v}</div>
      {sub && <div className="text-[11px] text-faint">{sub}</div>}
    </div>
  );
}

function Equity({ pts }: { pts: { ts: number; pnl: number }[] }) {
  if (!pts || pts.length < 2) return null;
  const vals = [0, ...pts.map((x) => x.pnl)];
  const lo = Math.min(...vals), hi = Math.max(...vals), span = hi - lo || 1;
  const W = 600, H = 120;
  const d = vals.map((v, i) => `${i ? "L" : "M"}${(i / (vals.length - 1)) * W},${H - ((v - lo) / span) * H}`).join(" ");
  const zero = H - ((0 - lo) / span) * H;
  return (
    <div className="mt-4">
      <div className="text-[12px] font-semibold text-dim">Profit over time</div>
      <svg viewBox={`0 0 ${W} ${H}`} className="mt-1 h-28 w-full" preserveAspectRatio="none">
        <line x1="0" x2={W} y1={zero} y2={zero} stroke="currentColor" className="text-line" strokeDasharray="4 4" />
        <path d={d} fill="none" strokeWidth="2.5" stroke="currentColor" className={vals[vals.length - 1] >= 0 ? "text-up" : "text-down"} vectorEffect="non-scaling-stroke" />
      </svg>
    </div>
  );
}

function Group({ title, rows }: { title: string; rows?: any[] }) {
  if (!rows?.length) return null;
  return <Table title={title} head={["", "Trades", "Won", "Win rate", "Profit", "Per trade"]}
    rows={rows.map((x) => [x.key, x.trades, x.wins, p(x.win_rate), <b key="p" className={x.pnl >= 0 ? "text-up" : "text-down"}>{money(x.pnl)}</b>, money(x.avg_pnl)])} />;
}

function Table({ title, head, rows, help, inner }: { title: string; head: string[]; rows: any[][]; help?: string; inner?: boolean }) {
  const body = (
    <>
      <h3 className={clsx("font-bold", inner ? "mt-4 text-[14px]" : "text-[17px]")}>{title}</h3>
      {help && <p className="mt-1 text-[12.5px] text-dim">{help}</p>}
      <div className="mt-2 overflow-x-auto">
        <table className="w-full min-w-[560px] text-[13px]">
          <thead className="text-left text-[11px] uppercase tracking-wide text-faint"><tr>{head.map((h) => <th key={h} className="py-2 pr-3">{h}</th>)}</tr></thead>
          <tbody>{rows.map((r, i) => <tr key={i} className="border-t border-line/60">{r.map((v, j) => <td key={j} className="num py-2 pr-3">{v}</td>)}</tr>)}</tbody>
        </table>
      </div>
    </>
  );
  return inner ? body : <section className="panel p-5">{body}</section>;
}


/** Balance over time (includes deposits) + cumulative return % (deposits excluded). */
function Perf({ perf }: { perf: any }) {
  const pts = perf.points as { ts: number; equity: number; pct: number | null; profit: number; contributed: number }[];
  const last = pts[pts.length - 1];
  return (
    <section className="panel p-5">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Tile k="Balance now" v={`$${last.equity.toFixed(2)}`} />
        <Tile k="Money you put in" v={`$${last.contributed.toFixed(2)}`} sub="start + deposits − withdrawals" />
        <Tile k="Profit (deposits excluded)" v={money(last.profit)} tone={last.profit >= 0 ? "up" : "down"} big />
        <Tile k="Cumulative return" v={last.pct == null ? "—" : `${last.pct >= 0 ? "+" : ""}${last.pct.toFixed(1)}%`} tone={(last.pct ?? 0) >= 0 ? "up" : "down"} />
      </div>
      <Line title="Balance over time" sub="Includes money you added — the blue dots are deposits." pts={pts.map((x) => ({ ts: x.ts, v: x.equity }))}
        marks={perf.deposits} fmt={(v) => `$${v.toFixed(0)}`} />
      <Line title="Cumulative return %" sub="Profit divided by the money you put in. Deposits do NOT count as gains." zero
        pts={pts.filter((x) => x.pct != null).map((x) => ({ ts: x.ts, v: x.pct as number }))} fmt={(v) => `${v.toFixed(1)}%`} />
    </section>
  );
}

function Line({ title, sub, pts, fmt, zero, marks }: { title: string; sub: string; pts: { ts: number; v: number }[];
  fmt: (v: number) => string; zero?: boolean; marks?: { ts: number; amount: number }[] }) {
  if (pts.length < 2) return null;
  const W = 600, H = 140;
  const vals = pts.map((p) => p.v).concat(zero ? [0] : []);
  const lo = Math.min(...vals), hi = Math.max(...vals), span = hi - lo || 1;
  const t0 = pts[0].ts, t1 = pts[pts.length - 1].ts, tspan = t1 - t0 || 1;
  const x = (ts: number) => ((ts - t0) / tspan) * W, y = (v: number) => H - ((v - lo) / span) * H;
  const d = pts.map((p, i) => `${i ? "L" : "M"}${x(p.ts).toFixed(1)},${y(p.v).toFixed(1)}`).join(" ");
  const up = pts[pts.length - 1].v >= (zero ? 0 : pts[0].v);
  const tl = (ts: number) => new Date(ts).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  return (
    <div className="mt-5">
      <div className="flex items-baseline justify-between"><div className="text-[14px] font-bold">{title}</div>
        <div className={clsx("num text-[14px] font-bold", up ? "text-up" : "text-down")}>{fmt(pts[pts.length - 1].v)}</div></div>
      <div className="text-[11.5px] text-faint">{sub}</div>
      <svg viewBox={`0 0 ${W} ${H}`} className="mt-2 h-36 w-full" preserveAspectRatio="none">
        {zero && <line x1="0" x2={W} y1={y(0)} y2={y(0)} stroke="currentColor" className="text-line" strokeDasharray="4 4" />}
        <path d={d} fill="none" strokeWidth="2.5" stroke="currentColor" className={up ? "text-up" : "text-down"} vectorEffect="non-scaling-stroke" />
        {(marks || []).filter((m) => m.ts >= t0 && m.ts <= t1).map((m, i) => {
          const near = pts.reduce((a, b) => (Math.abs(b.ts - m.ts) < Math.abs(a.ts - m.ts) ? b : a));
          return <circle key={i} cx={x(m.ts)} cy={y(near.v)} r="5" className="fill-info" vectorEffect="non-scaling-stroke" />;
        })}
      </svg>
      <div className="mt-1 flex justify-between text-[10px] text-faint"><span>{tl(t0)}</span><span>{fmt(lo)} – {fmt(hi)}</span><span>{tl(t1)}</span></div>
    </div>
  );
}
