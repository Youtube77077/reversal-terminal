"use client";
import clsx from "clsx";
import { ChevronRight, Eye, EyeOff } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { ASSET_COLORS, Avatar, Button, Drawer, ErrorNote, Field, inputCls, ListRow, Select } from "@/components/ui";
import { post, usePoll } from "@/lib/api";
import { dur, isNum, pct, price, signedUsd, usd } from "@/lib/format";
import { useLive } from "@/lib/live";

const NAMES: Record<string, string> = { BTC: "Bitcoin", ETH: "Ethereum", SOL: "Solana", XRP: "XRP", DOGE: "Dogecoin", HYPE: "Hyperliquid", BNB: "BNB" };
const MORE = [
  { href: "/scanner", t: "Reversal Scanner", s: "Live cheap-underdog finder", e: "📡" },
  { href: "/strategy-lab", t: "Strategy Lab", s: "Backtest & compare strategies", e: "🧪" },
  { href: "/replay", t: "Market Replay", s: "Watch any market second by second", e: "⏯️" },
  { href: "/experiments", t: "Experiments", s: "24h / 48h research runs", e: "📈" },
  { href: "/transactions", t: "Transactions", s: "Every trade, export CSV/JSON", e: "🧾" },
  { href: "/live", t: "Live trading", s: "Real-money mode & API keys", e: "🔐" },
];

export default function Money() {
  const { data: sum, error, reload } = usePoll<any>("/api/summary", 5000);
  const { data: ov } = usePoll<any>("/api/overview", 20000);
  const { tick } = useLive();
  const [hide, setHide] = useState(false);
  const [funds, setFunds] = useState(false);
  useEffect(() => { try { setHide(localStorage.getItem("rt_hide") === "1"); } catch {} }, []);
  const toggleHide = () => { setHide(!hide); try { localStorage.setItem("rt_hide", hide ? "0" : "1"); } catch {} };
  const running = (sum?.accounts || []).filter((a: any) => a.session?.active);
  const st = ov?.stats || {};
  const t10 = st.reversal_frequency?.["T-10"];
  const live = sum?.live_armed;
  const money = (v: any) => (hide ? "••••" : usd(v));

  return (
    <div className="page">
      <ErrorNote error={error} />
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_420px] lg:gap-8">
        <div className="space-y-4">
          {/* hero */}
          <div className="overflow-hidden rounded-4xl">
            <div className="relative h-24 bg-gradient-to-r from-[#1d6f8a] via-[#3f9a6e] to-[#5fb547] px-5 pt-5">
              <div className="absolute inset-0 opacity-30 [background:repeating-radial-gradient(circle_at_20%_120%,transparent_0_18px,rgba(255,255,255,.18)_19px_20px)]" />
              <Link href="/bot" className="relative inline-flex items-center gap-2 rounded-full bg-black/25 px-4 py-2 text-[14px] font-semibold text-white backdrop-blur">
                <span className={clsx("h-2 w-2 rounded-full", running.length ? "animate-pulse bg-white" : "bg-white/50")} />
                {running.length ? `${running.length} bot${running.length > 1 ? "s" : ""} running · ${live ? "LIVE $" : "paper"}` : "Start your bot"}
                <ChevronRight size={15} />
              </Link>
            </div>
            <div className="-mt-6 rounded-t-4xl bg-bg px-1 pt-6">
              <div className="flex items-center">
                <Link href="/trading" className="flex items-center gap-1 text-[17px] font-semibold">Total balance <ChevronRight size={17} /></Link>
                <button onClick={toggleHide} className="ml-auto rounded-full p-2 text-ink" aria-label="Hide balance">{hide ? <Eye size={22} /> : <EyeOff size={22} />}</button>
              </div>
              <div className="money mt-2 text-[64px] lg:text-[84px]">{money(sum?.equity)}</div>
              <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-[14px] text-dim">
                <span>Today <b className={clsx("num", (sum?.today_pnl ?? 0) >= 0 ? "text-up" : "text-down")}>{hide ? "••" : signedUsd(sum?.today_pnl)}</b></span>
                <span>Realised <b className="num text-ink">{hide ? "••" : signedUsd(sum?.realized)}</b></span>
                <span>Open <b className="num text-ink">{hide ? "••" : usd(sum?.open_cost)}</b></span>
              </div>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3 pt-2">
            <Link href="/bot" className="pill py-4 text-[17px]">Run bot</Link>
            <button onClick={() => setFunds(true)} className="pill py-4 text-[17px]">Funds</button>
          </div>

          <Link href="/live" className="flex items-center gap-3 rounded-4xl bg-panel px-6 py-6 transition active:scale-[.99]">
            <span className={clsx("h-7 w-4 rounded-[5px] border-[3px]", live ? "border-down" : "border-cash")} />
            <span className="text-[17px] font-semibold">{live ? "Live trading armed" : "Paper trading"}</span>
            <span className="ml-auto text-[15px] text-dim">{live ? "Real money" : "Go live"}</span>
          </Link>

          <div className="flex items-center gap-4 rounded-4xl bg-panel px-6 py-6">
            <div className="min-w-0 flex-1">
              <div className="text-[15px] font-semibold">Today</div>
              <div className={clsx("money mt-1 text-[40px]", (sum?.today_pnl ?? 0) > 0 && "text-up", (sum?.today_pnl ?? 0) < 0 && "text-down")}>
                {hide ? "••••" : signedUsd(sum?.today_pnl)}</div>
              <div className="mt-1 text-[14px] text-dim">{sum?.today_settled ?? 0} trades settled · win rate {pct(st.win_rate?.rate, 1)}</div>
            </div>
            <div className="flex -space-x-4">
              <span className="flex h-16 w-16 items-center justify-center rounded-full border border-line2 bg-bg text-[26px]">🎯</span>
              <span className="flex h-16 w-16 items-center justify-center rounded-full border border-line2 bg-bg text-[26px]">💸</span>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <Link href="/analytics" className="rounded-4xl bg-panel px-5 py-5 transition active:scale-[.99]">
              <div className="text-[14px] font-semibold text-dim">Reversal T-10</div>
              <div className="money mt-1 text-[28px]">{pct(t10?.rate, 1)}</div>
              <div className="text-[12px] text-faint">n={t10?.n ?? 0} resolved</div>
            </Link>
            <Link href="/transactions" className="rounded-4xl bg-panel px-5 py-5 transition active:scale-[.99]">
              <div className="text-[14px] font-semibold text-dim">Trades</div>
              <div className="money mt-1 text-[28px]">{st.filled_orders ?? 0}</div>
              <div className="text-[12px] text-faint">{st.wins ?? 0} won · {st.losses ?? 0} lost</div>
            </Link>
          </div>

          {running.length > 0 && (
            <section className="pt-4">
              <h2 className="mb-1 text-[28px] font-bold tracking-tight">Your bots</h2>
              {running.map((a: any) => {
                const ss = a.session;
                return (
                  <ListRow key={a.id} href={`/bot/?acct=${a.id}`}
                    icon={<Avatar label={a.strategy_key} color={a.mode === "live" ? "#ff453a" : "#00d64b"} />}
                    title={a.name}
                    sub={`Budget ${usd(ss.risk_budget)} · SL ${ss.stop_loss_pct}% · TP ${ss.take_profit_target ? usd(ss.take_profit_target) : "off"}`}
                    meta={a.halted_reason || `${ss.state.replace(/_/g, " ")} · ${a.open_positions} open`}
                    right={<span className={clsx("num text-[16px] font-semibold", ss.realized_pnl > 0 ? "text-up" : ss.realized_pnl < 0 ? "text-down" : "")}>{signedUsd(ss.realized_pnl)}</span>} />
                );
              })}
            </section>
          )}
        </div>

        <div className="space-y-2">
          <h2 className="pt-2 text-[28px] font-bold tracking-tight">Markets</h2>
          {Object.keys(NAMES).map((a) => {
            const s = tick?.assets?.[a];
            const fav = s?.favourite;
            return (
              <ListRow key={a} href={`/analytics/asset/?s=${a}`}
                icon={<Avatar label={a.slice(0, a === "DOGE" || a === "HYPE" ? 1 : 1)} color={ASSET_COLORS[a]} />}
                title={NAMES[a]}
                sub={s ? `${fav ?? "—"} ${pct(s.fav_prob, 0)} · cheap ${s.underdog ?? ""} ${price(s.underdog_ask)}` : "Waiting for market…"}
                meta={s ? `T-${dur(s.secs_remaining)} · spot ${isNum(s.spot) ? s.spot.toLocaleString(undefined, { maximumFractionDigits: s.spot > 100 ? 2 : 4 }) : "—"}` : undefined}
                right={<span className="pill px-4 py-2 text-[14px]">Open</span>} />
            );
          })}
          <div className="my-4 h-px bg-line" />
          <h2 className="text-[28px] font-bold tracking-tight">More for you</h2>
          {MORE.map((m) => (
            <ListRow key={m.href} href={m.href}
              icon={<span className="flex h-12 w-12 items-center justify-center text-[30px]">{m.e}</span>}
              title={m.t} sub={m.s} right={<span className="pill px-4 py-2 text-[14px]">Start</span>} />
          ))}
          <div className="my-4 h-px bg-line" />
          <p className="mono pb-6 text-[11.5px] leading-relaxed text-faint">
            Paper trading uses virtual funds against real Polymarket order books. Live trading, when armed, places real
            orders with your own Polymarket wallet; losses are real. Statistics show sample sizes and 95% confidence
            intervals; nothing here is financial advice. <Link href="/live" className="text-ink underline">Live terms</Link>
          </p>
        </div>
      </div>
      <FundsSheet open={funds} onClose={() => setFunds(false)} accounts={sum?.accounts || []} onDone={reload} />
    </div>
  );
}

function FundsSheet({ open, onClose, accounts, onDone }: { open: boolean; onClose: () => void; accounts: any[]; onDone: () => void }) {
  const paper = accounts.filter((a) => a.mode !== "live");
  const [aid, setAid] = useState<string>("");
  const [amt, setAmt] = useState("10");
  const [err, setErr] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);
  useEffect(() => { if (!aid && paper.length) setAid(String(paper[0].id)); }, [paper, aid]);
  const act = async (action: string) => {
    setErr(null); setOk(null);
    try {
      await post(`/api/accounts/${aid}/${action}`, action === "reset" ? { balance: Number(amt) } : { amount: Number(amt) });
      setOk(`${action} done`); onDone();
    } catch (e: any) { setErr(e.message); }
  };
  return (
    <Drawer open={open} onClose={onClose} title="Virtual funds">
      <div className="space-y-4">
        <p className="text-[13px] text-dim">Paper accounts only. Every change is recorded in the account ledger; past trades are never modified. Live balances come from your real wallet.</p>
        <Field label="Account"><Select value={aid} onChange={setAid} className="w-full" options={paper.map((a) => ({ value: String(a.id), label: `${a.name} · ${usd(a.equity)}` }))} /></Field>
        <Field label="Amount (USD)"><input className={inputCls + " py-3 text-[20px]"} inputMode="decimal" value={amt} onChange={(e) => setAmt(e.target.value)} /></Field>
        <div className="flex flex-wrap gap-2">{[5, 10, 20, 50, 100, 250, 500].map((v) => <Button key={v} size="sm" onClick={() => setAmt(String(v))}>${v}</Button>)}</div>
        <div className="grid grid-cols-3 gap-2">
          <Button tone="primary" size="lg" onClick={() => act("deposit")}>Add</Button>
          <Button size="lg" onClick={() => act("withdraw")}>Withdraw</Button>
          <Button tone="warn" size="lg" onClick={() => confirm(`Reset balance to $${amt}?`) && act("reset")}>Reset</Button>
        </div>
        <ErrorNote error={err} />
        {ok && <div className="text-[13px] text-up">{ok}</div>}
      </div>
    </Drawer>
  );
}
