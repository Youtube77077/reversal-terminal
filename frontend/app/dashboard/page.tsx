"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import AssetCard from "@/components/AssetCard";
import { ErrorNote, Panel, Pill, Rate, Stat } from "@/components/ui";
import { usePoll } from "@/lib/api";
import { dur, int, pct, pnlClass, signedUsd, ts, usd } from "@/lib/format";
import { useLive } from "@/lib/live";

const ASSETS: [string, string][] = [["BTC", "Bitcoin"], ["ETH", "Ethereum"], ["SOL", "Solana"], ["XRP", "XRP"],
  ["DOGE", "Dogecoin"], ["HYPE", "Hyperliquid"], ["BNB", "BNB"]];

export default function Overview() {
  const router = useRouter();
  const { tick, connected, events } = useLive();
  const { data: ov, error } = usePoll<any>("/api/overview", 5000);
  const st = ov?.stats || {};
  const b = ov?.balances || {};
  const exp = ov?.experiment;
  const live = tick?.assets || {};
  const statuses = tick?.asset_status || {};
  const netTone = (v: number) => (v > 0 ? "up" : v < 0 ? "down" : undefined) as any;
  return (
    <div className="page space-y-4">
      <ErrorNote error={error} />
      <div className="grid grid-cols-1 gap-3 xl:grid-cols-[1fr_380px]">
        <Panel title="Operating status" right={<><Pill kind="PAPER">PAPER · SIMULATED</Pill><Pill kind={connected ? "LIVE" : "OFFLINE"} /></>}>
          <div className="grid-auto">
            <Stat label="Operating mode" value="PAPER" sub="live execution disabled" />
            <Stat label="Connection" value={connected ? "Connected" : "Offline"} tone={connected ? "up" : "down"} sub={`collector ${ov?.collector?.running ? "running" : "stopped"}`} />
            <Stat label="Experiment start" value={exp ? ts(exp.started_ts) : "—"} sub={exp?.id || "no experiment"} onClick={() => router.push("/experiments")} />
            <Stat label="Experiment duration" value={exp ? (exp.duration_hours ? `${exp.duration_hours}h` : "unlimited") : "—"} sub={exp ? `elapsed ${dur(exp.elapsed_seconds)}` : undefined} />
            <Stat label="Time remaining" value={exp?.remaining_seconds != null ? dur(exp.remaining_seconds) : "—"} tone={exp?.status === "running" ? "up" : "dim"} sub={exp?.status} />
            <Stat label="Markets monitored" value={int(ov?.assets_monitored)} sub={`${ov?.collector?.active_markets ?? 0} active now`} />
            <Stat label="Markets discovered" value={int(st.markets_discovered)} onClick={() => router.push("/markets")} />
            <Stat label="Markets resolved" value={int(st.markets_resolved)} onClick={() => router.push("/markets?status=resolved")} />
            <Stat label="Observations" value={int(st.observations)} sub={`${int(st.checkpoints)} checkpoints`} />
            <Stat label="Trading signals" value={int(st.signals)} sub={`${int(st.signals_accepted)} accepted`} onClick={() => router.push("/trading")} />
            <Stat label="Simulated orders" value={int(st.orders)} onClick={() => router.push("/transactions")} />
            <Stat label="Filled orders" value={int(st.filled_orders)} onClick={() => router.push("/transactions?status=filled,won,lost")} />
            <Stat label="Winning trades" value={int(st.wins)} tone="up" onClick={() => router.push("/transactions?result=win")} />
            <Stat label="Losing trades" value={int(st.losses)} tone="down" onClick={() => router.push("/transactions?result=loss")} />
            <div className="rounded border border-line bg-panel2/60 px-3 py-2">
              <div className="label">Overall win rate</div>
              <div className="mt-0.5 text-[15px]"><Rate rate={st.win_rate?.rate} n={st.win_rate?.n} lo={st.win_rate?.ci_low} hi={st.win_rate?.ci_high} flag={st.win_rate?.sample} /></div>
            </div>
            {["T-10", "T-5", "T-3", "T-1"].map((k) => {
              const r = st.reversal_frequency?.[k];
              return (
                <Link key={k} href="/analytics" className="rounded border border-line bg-panel2/60 px-3 py-2 hover:border-line2">
                  <div className="label">Reversal freq {k}</div>
                  <div className="mt-0.5 text-[15px]"><Rate rate={r?.rate} n={r?.n} lo={r?.ci_low} hi={r?.ci_high} flag={r?.sample} /></div>
                </Link>
              );
            })}
          </div>
        </Panel>
        <Panel title="Live event feed" pad={false}>
          <div className="max-h-[360px] overflow-y-auto">
            {events.length === 0 && <div className="p-3 text-2xs text-faint">Waiting for events…</div>}
            {events.slice(0, 80).map((e, i) => (
              <div key={i} className="flex gap-2 border-b border-line/50 px-3 py-1 text-2xs">
                <span className="mono shrink-0 text-faint">{ts(e.ts, false)}</span>
                <span className={`shrink-0 ${e.level === "ERROR" ? "text-down" : e.level === "WARNING" ? "text-warn" : "text-info"}`}>{e.category}</span>
                <span className="min-w-0 truncate text-dim" title={e.message}>{e.message}</span>
              </div>
            ))}
          </div>
        </Panel>
      </div>

      <Panel title="Paper capital — all accounts" sub="Realised and unrealised results are shown separately. Unrealised marks use the current best bid (estimate)."
        right={<Link href="/trading" className="text-2xs text-dim hover:text-ink">manage accounts →</Link>}>
        <div className="grid-auto">
          <Stat label="Starting virtual balance" value={usd(b.initial)} sub={`${ov?.accounts ?? 0} accounts`} />
          <Stat label="Current equity" value={usd(b.equity)} sub="cash + reserved + marks" />
          <Stat label="Available balance" value={usd(b.available)} />
          <Stat label="Capital committed" value={usd((b.open_cost || 0) + (b.reserved || 0))} sub={`open ${usd(b.open_cost)} · reserved ${usd(b.reserved)}`} />
          <Stat label="Gross profit (settled)" value={usd(st.gross_profit, 4)} tone="up" />
          <Stat label="Gross losses (settled)" value={usd(st.gross_loss, 4)} tone="down" />
          <Stat label="Trading fees" value={usd(st.fees, 4)} sub="0.07·p·(1-p) per share" />
          <Stat label="Slippage" value={usd(st.slippage, 4)} sub="vs decision ask (in cost)" />
          <Stat label="Net P&L (realised)" value={<span className={pnlClass(st.net_pnl)}>{signedUsd(st.net_pnl, 4)}</span>} tone={netTone(st.net_pnl)} />
          <Stat label="Unrealised P&L (est.)" value={<span className={pnlClass(b.unrealized)}>{signedUsd(b.unrealized, 4)}</span>} sub="mark-to-bid, estimate" />
          <Stat label="Return on investment" value={pct(st.roi)} sub="net / settled cost" tone={netTone(st.roi)} />
          <Stat label="Max drawdown" value={pct(ov?.max_drawdown_pct_worst_account)} sub="worst account vs peak" tone="warn" />
        </div>
      </Panel>

      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4 2xl:grid-cols-7">
        {ASSETS.map(([a, n]) => (
          <AssetCard key={a} asset={a} name={n} state={live[a]} status={statuses[a]?.status} detail={statuses[a]?.detail} />
        ))}
      </div>
    </div>
  );
}
