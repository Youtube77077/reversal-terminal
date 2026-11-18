"use client";
import clsx from "clsx";
import { ChevronRight, Eye, EyeOff, PiggyBank, Play, RotateCcw, Wallet } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import BankCard from "@/components/BankCard";
import { TimeChart } from "@/components/Chart";
import { BarChart } from "@/components/Charts2";
import ResetCard from "@/components/ResetCard";
import WalletBar from "@/components/WalletBar";
import { useWallet, walletBalance } from "@/lib/wallet";
import { ASSET_COLORS, Avatar, Button, Drawer, ErrorNote, Field, inputCls, ListRow, Select, Tabs } from "@/components/ui";
import { post, usePoll } from "@/lib/api";
import { dur, isNum, pct, price, signedUsd, usd } from "@/lib/format";
import { useLive } from "@/lib/live";

const NAMES: Record<string, string> = { BTC: "Bitcoin", ETH: "Ethereum", SOL: "Solana", XRP: "XRP", DOGE: "Dogecoin", HYPE: "Hyperliquid", BNB: "BNB" };
const MORE = [
  { href: "/scanner", t: "Reversal Scanner", s: "Live cheap-underdog finder", e: "📡" },
  { href: "/strategy-lab", t: "Strategy Lab", s: "What each strategy does, backtests", e: "🧪" },
  { href: "/replay", t: "Market Replay", s: "Watch any market second by second", e: "⏯️" },
  { href: "/experiments", t: "Experiments", s: "24h / 48h research runs & reports", e: "📈" },
  { href: "/transactions", t: "Transactions", s: "Every trade, export CSV/JSON", e: "🧾" },
  { href: "/live", t: "Live trading", s: "API keys, real-money switch", e: "🔐" },
];

export default function Home() {
  const { data: sum, error, reload } = usePoll<any>("/api/summary", 5000);
  const { data: ov } = usePoll<any>("/api/overview", 20000);
  const [mode, setMode] = useState("all");
  const { data: ser } = usePoll<any>(`/api/analytics/series?mode=${mode}`, 20000);
  const { tick } = useLive();
  const { wallet, reload: reloadW } = useWallet();
  const [hide, setHide] = useState(false);
  const [funds, setFunds] = useState(false);
  const [resetOpen, setResetOpen] = useState(false);
  useEffect(() => { try { setHide(localStorage.getItem("rt_hide") === "1"); } catch {} }, []);
  const toggleHide = () => { setHide(!hide); try { localStorage.setItem("rt_hide", hide ? "0" : "1"); } catch {} };
  const running = (sum?.accounts || []).filter((a: any) => a.session?.active && a.session.state === "running" && !a.halted_reason);
  const st = ov?.stats || {};
  const live = !!sum?.live_armed;
  const eq = useMemo(() => (ser?.equity || []).map((p: any) => ({ time: p.t, value: p.v })), [ser]);
  const cum = useMemo(() => (ser?.cum_pnl || []).map((p: any) => ({ time: p.t, value: p.v })), [ser]);

  return (
    <div className="page">
      <ErrorNote error={error} />
      <div className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1fr)_420px] xl:gap-8">
        <div className="min-w-0 space-y-5">
          <div className="grid grid-cols-1 items-center gap-6 lg:grid-cols-[460px_1fr]">
            <div className="space-y-3"><WalletBar />
            <BankCard balance={walletBalance(wallet)} todayPnl={wallet?.paper?.session?.realized_pnl ?? 0} running={running.length} live={live} hidden={hide} /></div>
            <div className="space-y-3">
              <div className="flex items-center">
                <span className="text-[15px] font-semibold text-dim">{wallet?.name} · practice money</span>
                <button onClick={toggleHide} className="ml-auto rounded-full p-2 text-dim hover:text-ink" aria-label="Hide balance">{hide ? <Eye size={20} /> : <EyeOff size={20} />}</button>
              </div>
              <div className="grid grid-cols-3 gap-2">
                <MiniStat k="Realised" v={hide ? "••" : signedUsd(sum?.realized)} tone={sum?.realized} />
                <MiniStat k="Unrealised" v={hide ? "••" : signedUsd(sum?.unrealized)} tone={sum?.unrealized} />
                <MiniStat k="In trades" v={hide ? "••" : usd(sum?.open_cost)} />
              </div>
              <div className="grid grid-cols-3 gap-2">
                <Link href="/bot" className="flex flex-col items-center gap-1.5 rounded-3xl bg-cash py-4 text-oncash transition active:scale-[.97]">
                  <Play size={20} fill="currentColor" /><span className="text-[13px] font-bold">Start bot</span></Link>
                <button onClick={() => setFunds(true)} className="flex flex-col items-center gap-1.5 rounded-3xl bg-panel py-4 transition active:scale-[.97]">
                  <Wallet size={20} /><span className="text-[13px] font-bold">Funds</span></button>
                <button onClick={() => setResetOpen(true)} className="flex flex-col items-center gap-1.5 rounded-3xl bg-panel py-4 transition active:scale-[.97]">
                  <RotateCcw size={20} /><span className="text-[13px] font-bold">Reset stats</span></button>
              </div>
              <Link href="/live" className={clsx("flex items-center gap-3 rounded-3xl px-5 py-4 transition active:scale-[.99]", live ? "bg-down/15" : "bg-panel")}>
                <span className={clsx("h-3 w-3 rounded-full", live ? "bg-down live-pulse" : "bg-info")} />
                <span className="text-[15px] font-semibold">{live ? "Live trading is ON — real money" : "Paper trading (virtual money)"}</span>
                <ChevronRight size={17} className="ml-auto text-faint" />
              </Link>
            </div>
          </div>

          <section className="panel p-5">
            <div className="mb-3 flex flex-wrap items-center gap-3">
              <h2 className="panel-title">Balance over time</h2>
              <div className="ml-auto"><Tabs value={mode} onChange={setMode} tabs={[{ key: "all", label: "All" }, { key: "paper", label: "Paper" }, { key: "live", label: "Live" }]} /></div>
            </div>
            <TimeChart title="balance" height={230} ranges series={[
              { name: "Equity", color: "#00d64b", type: "area", data: eq },
            ]} />
          </section>

          <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
            <section className="panel p-5">
              <h2 className="panel-title mb-3">Cumulative profit</h2>
              <TimeChart title="cumulative_pnl" height={190} series={[{ name: "Realised P&L", color: "#409cff", type: "area", data: cum }]} />
            </section>
            <section className="panel p-5">
              <h2 className="panel-title mb-3">Profit by day</h2>
              <BarChart data={(ser?.daily || []).slice(-14).map((d: any) => ({ x: d.x.slice(5), v: d.pnl, trades: d.trades, wins: d.wins }))}
                sub={(d) => `${d.trades} trades · ${d.wins} won`} />
            </section>
          </div>

          <section className="panel p-5">
            <h2 className="panel-title mb-3">Performance</h2>
            <div className="grid-auto">
              <MiniStat k="Trades" v={String(st.filled_orders ?? 0)} sub={`${st.wins ?? 0} won · ${st.losses ?? 0} lost`} />
              <MiniStat k="Win rate" v={pct(st.win_rate?.rate, 1)} sub={`n=${st.win_rate?.n ?? 0}`} />
              <MiniStat k="Net P&L" v={signedUsd(st.net_pnl)} tone={st.net_pnl} />
              <MiniStat k="ROI" v={pct(st.roi, 1)} tone={st.roi} />
              <MiniStat k="Fees paid" v={usd(st.fees, 2)} />
              <MiniStat k="Reversal T-10" v={pct(st.reversal_frequency?.["T-10"]?.rate, 1)} sub={`n=${st.reversal_frequency?.["T-10"]?.n ?? 0}`} />
              <MiniStat k="Markets resolved" v={String(st.markets_resolved ?? 0)} />
              <MiniStat k="Observations" v={(st.observations ?? 0).toLocaleString()} />
            </div>
          </section>

          {running.length > 0 && (
            <section className="panel p-5">
              <h2 className="panel-title mb-1">Running bots</h2>
              {running.map((a: any) => {
                const ss = a.session;
                return (
                  <ListRow key={a.id} href={`/bot/?acct=${a.id}`}
                    icon={<Avatar label={a.strategy_key} color={a.mode === "live" ? "#ff453a" : "#00b86b"} />}
                    title={a.name}
                    sub={`Budget ${usd(ss.risk_budget)} · SL ${ss.stop_loss_pct}% · TP ${ss.take_profit_target ? usd(ss.take_profit_target) : "off"}`}
                    meta={`${Math.round((ss.budget_used_pct ?? 0) * 100)}% of risk used · ${a.open_positions} open`}
                    right={<span className={clsx("num text-[16px] font-semibold", ss.realized_pnl > 0 ? "text-up" : ss.realized_pnl < 0 ? "text-down" : "")}>{signedUsd(ss.realized_pnl)}</span>} />
                );
              })}
            </section>
          )}
        </div>

        <div className="min-w-0 space-y-5">
          <section className="panel p-5">
            <h2 className="panel-title mb-1">Live markets</h2>
            {Object.keys(NAMES).map((a) => {
              const s = tick?.assets?.[a];
              const fav = s?.favourite;
              return (
                <ListRow key={a} href={`/analytics/asset/?s=${a}`}
                  icon={<Avatar label={a[0]} color={ASSET_COLORS[a]} size={44} />}
                  title={NAMES[a]}
                  sub={s ? `${fav ?? "—"} ${pct(s.fav_prob, 0)} · cheap ${price(s.underdog_ask)}` : "Waiting for market…"}
                  meta={s ? `T-${dur(s.secs_remaining)}` : undefined}
                  right={<ChevronRight size={18} className="text-faint" />} />
              );
            })}
          </section>
          <section className="panel p-5">
            <h2 className="panel-title mb-3">Profit by market</h2>
            <BarChart data={(ser?.pnl_by_asset || []).map((d: any) => ({ x: d.x, v: d.pnl, trades: d.trades, wins: d.wins }))}
              sub={(d) => `${d.trades} trades · ${d.wins} won`} height={170} />
          </section>
          <section className="panel p-5">
            <h2 className="panel-title mb-1">Explore</h2>
            {MORE.map((m) => (
              <ListRow key={m.href} href={m.href}
                icon={<span className="flex h-11 w-11 items-center justify-center rounded-2xl bg-panel2 text-[24px]">{m.e}</span>}
                title={m.t} sub={m.s} right={<ChevronRight size={18} className="text-faint" />} />
            ))}
          </section>
          <p className="px-2 pb-4 text-[11.5px] leading-relaxed text-faint">
            <PiggyBank size={12} className="mr-1 inline" />Paper trading uses virtual funds against real Polymarket order books. Live trading,
            when switched on and armed, places real orders with your own Polymarket wallet; losses are real.
          </p>
        </div>
      </div>
      <FundsSheet open={funds} onClose={() => setFunds(false)} accounts={wallet ? [{ id: wallet.paper.id, name: wallet.name, mode: "paper", equity: walletBalance(wallet) }] : []} onDone={() => { reload(); reloadW(); }} />
      <Drawer open={resetOpen} onClose={() => setResetOpen(false)} title="Reset stats">
        <ResetCard onDone={() => { reload(); setResetOpen(false); }} bare />
      </Drawer>
    </div>
  );
}

function MiniStat({ k, v, sub, tone }: { k: string; v: string; sub?: string; tone?: number | null }) {
  return (
    <div className="rounded-2xl bg-panel2/60 px-3.5 py-3">
      <div className="text-[11.5px] font-medium text-dim">{k}</div>
      <div className={clsx("num mt-0.5 truncate text-[17px] font-semibold", isNum(tone) && tone > 0 && "text-up", isNum(tone) && tone < 0 && "text-down")}>{v}</div>
      {sub && <div className="truncate text-[11px] text-faint">{sub}</div>}
    </div>
  );
}

function FundsSheet({ open, onClose, accounts, onDone }: { open: boolean; onClose: () => void; accounts: any[]; onDone: () => void }) {
  const paper = accounts.filter((a) => a.mode !== "live");
  const aid = paper[0] ? String(paper[0].id) : "";   // always the wallet selected above
  const [amt, setAmt] = useState("20");
  const [err, setErr] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);
  const act = async (action: string) => {
    setErr(null); setOk(null);
    try {
      await post(`/api/accounts/${aid}/${action}`, action === "reset" ? { balance: Number(amt) } : { amount: Number(amt) });
      setOk(`Done · ${paper[0]?.name}`); onDone();
    } catch (e: any) { setErr(e.message); }
  };
  return (
    <Drawer open={open} onClose={onClose} title="Practice money">
      <div className="space-y-4">
        <p className="text-[13px] text-dim">Pick the wallet, then add, withdraw or set its practice money. Real money comes from your Polymarket wallet.</p>
        <Field label="Wallet"><WalletBar /></Field>
        {paper[0] && <div className="text-[15px] font-semibold">{paper[0].name}: <span className="num">{usd(paper[0].equity)}</span></div>}
        <Field label="Amount (USD)"><input className={inputCls + " py-3 text-[20px]"} inputMode="decimal" value={amt} onChange={(e) => setAmt(e.target.value)} /></Field>
        <div className="flex flex-wrap gap-2">{[5, 10, 20, 50, 100, 250, 500].map((v) => <Button key={v} size="sm" onClick={() => setAmt(String(v))}>${v}</Button>)}</div>
        <div className="grid grid-cols-3 gap-2">
          <Button tone="primary" size="lg" onClick={() => act("deposit")}>Add</Button>
          <Button size="lg" onClick={() => act("withdraw")}>Withdraw</Button>
          <Button tone="warn" size="lg" onClick={() => confirm(`Set ${paper[0]?.name ?? "this wallet"}'s practice money to $${amt}?`) && act("reset")}>Set balance</Button>
        </div>
        <ErrorNote error={err} />
        {ok && <div className="text-[13px] text-up">{ok}</div>}
      </div>
    </Drawer>
  );
}
