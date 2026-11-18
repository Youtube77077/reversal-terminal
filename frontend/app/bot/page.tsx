"use client";
import clsx from "clsx";
import { Check, ChevronRight, Delete } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { post, qs, usePoll } from "@/lib/api";
import { price, signedUsd, usd } from "@/lib/format";

/* The 3 simple strategy choices (the rest live in Strategy Lab). */
const CHOICES = [
  { key: "K", name: "Safe favourite", tag: "Recommended", text: "In the last 30 seconds, buys the side that's almost sure to win (95%+). Small wins, rare big losses." },
  { key: "M", name: "Smart favourite", tag: "Data-driven", text: "Like Safe favourite, but only trades when past results prove it beats the fees. Trades less often." },
  { key: "N", name: "Smart long shot", tag: "Experimental", text: "Buys the cheap side only when the coin is close enough to flip and the real chance beats the price + fee. Never buys hopeless 1¢ shots." },
];
const COINS = ["BTC", "ETH", "SOL", "XRP", "DOGE", "HYPE", "BNB"];
const DEFAULTS: Record<string, { max_price: number; min_price: number; entry_max_secs: number; min_edge: number; stake_usd: number }> = {
  K: { max_price: 0.98, min_price: 0.90, entry_max_secs: 30, min_edge: 0, stake_usd: 5 },
  M: { max_price: 0.99, min_price: 0.85, entry_max_secs: 30, min_edge: 0, stake_usd: 5 },
  N: { max_price: 0.15, min_price: 0, entry_max_secs: 45, min_edge: 0.03, stake_usd: 1 },
};
const LOSS = [{ v: 25, l: "¼ of it" }, { v: 50, l: "Half" }, { v: 100, l: "All of it" }];
const WIN = [{ v: 0, l: "Never" }, { v: 50, l: "+50%" }, { v: 100, l: "Double" }, { v: 200, l: "Triple" }];

export default function BotPage() {
  const { data: accounts, reload } = usePoll<any[]>("/api/accounts", 4000);
  const { data: summary } = usePoll<any>("/api/summary", 5000);
  const [real, setReal] = useState(false);
  const [val, setVal] = useState("20");
  const [loss, setLoss] = useState(100);
  const [win, setWin] = useState(0);
  const [strat, setStrat] = useState("K");
  const [coins, setCoins] = useState<string[]>(COINS);
  const [adv, setAdv] = useState(false);
  const [cfg, setCfg] = useState(DEFAULTS.K);
  useEffect(() => setCfg(DEFAULTS[strat] || DEFAULTS.K), [strat]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const liveAcct = accounts?.find((a) => a.mode === "live" && !a.archived);
  // the paper account used by the simple screen = first paper account with the chosen strategy
  const paperAcct = accounts?.find((a) => a.mode !== "live" && a.strategy_key === strat);
  const running = (accounts || []).find((a) => a.session?.active && !a.archived && (real ? a.mode === "live" : a.mode !== "live"));
  const acct = running || (real ? liveAcct : paperAcct);
  const ss = running?.session;
  const armed = !!summary?.live_armed;
  const budget = Number(val || 0);
  const liveBalance = liveAcct?.summary?.equity ?? 0;

  const press = (k: string) => {
    setErr(null);
    setVal((v) => {
      if (k === "<") return v.length > 1 ? v.slice(0, -1) : "0";
      if (k === ".") return v.includes(".") ? v : v + ".";
      const n = v === "0" ? k : v + k;
      if (n.split(".")[1]?.length > 2 || n.length > 7) return v;
      return n;
    });
  };

  const start = async () => {
    if (!acct) return;
    if (budget < 1) return setErr("Budget must be at least $1");
    setBusy(true); setErr(null);
    try {
      if (!real) await post(`/api/accounts/${acct.id}/reset`, { balance: budget });   // practice: account = exactly your budget
      await post(`/api/accounts/${acct.id}/session/start`, {
        risk_budget_mode: real ? "amount" : "percent", risk_budget_value: real ? budget : 100,
        stop_loss_pct: loss, take_profit_mode: win ? "percent" : "off", take_profit_value: win, strategy_key: strat,
        params: { ...cfg, assets: coins.length === COINS.length ? [] : coins },
      });
      (window as any).ReversalNative?.haptic("success");
      reload();
    } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  };
  const stop = async () => {
    if (!running) return;
    setBusy(true);
    try { await post(`/api/accounts/${running.id}/session/stop`); reload(); } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  };

  return (
    <div className="min-h-[calc(100vh-80px)] bg-cash text-oncash">
      <div className="mx-auto max-w-[520px] px-5 pb-32 pt-2 animate-rise lg:pb-10 lg:pt-8">
        {/* 1. practice / real */}
        <div className="flex rounded-full bg-black/10 p-1 text-[15px] font-bold">
          {[false, true].map((r) => (
            <button key={String(r)} disabled={!!running} onClick={() => setReal(r)}
              className={clsx("flex-1 rounded-full py-2.5 transition", real === r ? "bg-black text-white" : "opacity-70")}>
              {r ? "Real money" : "Practice"}</button>
          ))}
        </div>

        {running && ss ? <Running acct={running} ss={ss} busy={busy} onStop={stop} /> : (
          <>
            {real && !armed ? (
              <div className="mt-8 rounded-4xl bg-black/10 p-6 text-center">
                <div className="text-[20px] font-bold">Real money isn't set up yet</div>
                <p className="mt-2 text-[14px] opacity-75">Add your Polymarket keys and switch live trading on. It takes 2 minutes.</p>
                <Link href="/live" className="mt-5 inline-flex items-center gap-1 rounded-full bg-black px-6 py-3.5 text-[16px] font-bold text-white">Set up real money <ChevronRight size={17} /></Link>
              </div>
            ) : (
              <>
                {/* 2. budget */}
                <div className="mt-6 text-center text-[15px] font-semibold opacity-75">{real ? "How much may the bot use?" : "Practice budget"}</div>
                <div className="money mt-1 text-center text-[80px] min-[400px]:text-[92px]">${val}</div>
                {real && <div className="text-center text-[13px] font-semibold opacity-70">Wallet: {usd(liveBalance)}</div>}
                <div className="mt-2 grid grid-cols-3 text-center">
                  {["1", "2", "3", "4", "5", "6", "7", "8", "9", ".", "0", "<"].map((k) => (
                    <button key={k} onClick={() => press(k)} className="rounded-2xl py-2.5 text-[26px] font-semibold transition active:scale-90 active:bg-black/10">
                      {k === "<" ? <Delete className="mx-auto" size={24} /> : k}</button>
                  ))}
                </div>

                {/* 3. stop rules */}
                <Chips label="Stop if I lose" items={LOSS} value={loss} onChange={setLoss} />
                <Chips label="Stop if I win" items={WIN} value={win} onChange={setWin} />

                {/* 4. strategy */}
                <div className="mt-5 text-[13px] font-bold opacity-75">Strategy</div>
                <div className="mt-2 space-y-2">
                  {CHOICES.map((c) => (
                    <button key={c.key} onClick={() => setStrat(c.key)}
                      className={clsx("flex w-full items-start gap-3 rounded-3xl p-4 text-left transition", strat === c.key ? "bg-black text-white" : "bg-black/10")}>
                      <span className={clsx("mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full", strat === c.key ? "bg-cash text-black" : "bg-black/15")}>
                        {strat === c.key && <Check size={14} strokeWidth={3} />}</span>
                      <span><span className="flex items-center gap-2 text-[16px] font-bold">{c.name}
                        <span className={clsx("rounded-full px-2 py-0.5 text-[10px] font-bold uppercase", strat === c.key ? "bg-white/15" : "bg-black/10")}>{c.tag}</span></span>
                        <span className="mt-0.5 block text-[13px] leading-snug opacity-80">{c.text}</span></span>
                    </button>
                  ))}
                </div>

                {/* 5. markets + settings */}
                <div className="mt-5 text-[13px] font-bold opacity-75">Trade on</div>
                <div className="mt-2 flex flex-wrap gap-2">
                  {COINS.map((c) => {
                    const on = coins.includes(c);
                    return <button key={c} onClick={() => setCoins((x) => on ? x.filter((y) => y !== c) : [...x, c])}
                      className={clsx("rounded-full px-4 py-2 text-[14px] font-bold transition active:scale-95", on ? "bg-black text-white" : "bg-black/10 opacity-70")}>{c}</button>;
                  })}
                </div>
                <button onClick={() => setAdv(!adv)} className="mt-4 text-[14px] font-bold underline opacity-80">{adv ? "Hide settings" : "Change settings (prices, timing, stake)"}</button>
                {adv && (
                  <div className="mt-3 grid grid-cols-2 gap-2 animate-fade">
                    <Num label={strat === "N" ? "Max price (¢)" : "Max price (¢)"} value={Math.round(cfg.max_price * 100)} onChange={(v) => setCfg({ ...cfg, max_price: v / 100 })} />
                    <Num label="Min price (¢)" value={Math.round(cfg.min_price * 100)} onChange={(v) => setCfg({ ...cfg, min_price: v / 100 })} />
                    <Num label="Only last … seconds" value={cfg.entry_max_secs} onChange={(v) => setCfg({ ...cfg, entry_max_secs: v })} />
                    <Num label="$ per trade" value={cfg.stake_usd} onChange={(v) => setCfg({ ...cfg, stake_usd: v })} />
                    {strat !== "K" && <Num label="Min edge (points %)" value={Math.round(cfg.min_edge * 100)} onChange={(v) => setCfg({ ...cfg, min_edge: v / 100 })} />}
                  </div>
                )}
                {err && <div className="mt-4 rounded-2xl bg-black/15 px-4 py-3 text-center text-[14px] font-semibold">{err}</div>}
                <button onClick={start} disabled={busy || !acct || budget < 1}
                  className="mt-5 w-full rounded-full bg-black py-4 text-[18px] font-bold text-white transition active:scale-[.98] disabled:opacity-50">
                  {busy ? "Starting…" : real ? `Start with $${val} real money` : `Start practice with $${val}`}</button>
                <p className="mt-3 text-center text-[12.5px] font-medium opacity-70">
                  It can lose at most ${(budget * loss / 100).toFixed(2)}{win ? ` and stops after +$${(budget * win / 100).toFixed(2)}` : ""}.
                  {!real && " Practice uses fake money on real markets."}
                </p>
              </>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function Chips({ label, items, value, onChange }: { label: string; items: { v: number; l: string }[]; value: number; onChange: (v: number) => void }) {
  return (
    <div className="mt-4">
      <div className="text-[13px] font-bold opacity-75">{label}</div>
      <div className="mt-2 flex gap-2">
        {items.map((i) => (
          <button key={i.v} onClick={() => onChange(i.v)}
            className={clsx("flex-1 rounded-full py-2.5 text-[14px] font-bold transition active:scale-95", value === i.v ? "bg-black text-white" : "bg-black/10")}>{i.l}</button>
        ))}
      </div>
    </div>
  );
}

function Running({ acct, ss, busy, onStop }: { acct: any; ss: any; busy: boolean; onStop: () => void }) {
  const { data } = usePoll<any>(`/api/transactions${qs({ account_id: acct.id, limit: 30 })}`, 4000);
  const trades: any[] = data?.rows || [];
  const done = acct.halted_reason || ss.state !== "running";
  const left = Math.max(0, ss.stop_loss_limit - ss.loss_so_far - ss.open_at_risk);
  const msg = useMemo(() => {
    if (acct.halted_reason) return acct.halted_reason;
    if (!trades.length) return "Watching the markets… trades happen in the last seconds of each 5-minute market.";
    return `${trades.length} trade${trades.length > 1 ? "s" : ""} so far`;
  }, [acct.halted_reason, trades.length]);
  return (
    <div className="mt-6">
      <div className="text-center text-[15px] font-semibold opacity-75">{done ? "Bot stopped" : "Bot is running"} · {acct.mode === "live" ? "REAL MONEY" : "practice"}</div>
      <div className="money mt-2 text-center text-[68px]">{signedUsd(ss.realized_pnl)}</div>
      <div className="mt-1 text-center text-[14px] opacity-80">{msg}</div>
      <div className="mt-6 grid grid-cols-3 gap-2 text-center">
        <Box k="Budget" v={usd(ss.risk_budget)} /><Box k="In trades" v={usd(ss.open_at_risk)} /><Box k="Can still use" v={usd(left)} />
      </div>
      <div className="mt-6 text-[13px] font-bold opacity-75">Where your money went</div>
      <div className="mt-2 space-y-2">
        {trades.length === 0 && <div className="rounded-3xl bg-black/10 p-4 text-[14px] opacity-80">No trades yet. Keep the app closed or open — the bot keeps running on the server.</div>}
        {trades.map((t) => {
          const won = t.status === "won", lost = t.status === "lost";
          return (
            <Link key={t.id} href={`/transactions/view/?id=${t.id}`} className="flex items-center gap-3 rounded-3xl bg-black/10 px-4 py-3 active:scale-[.99]">
              <span className="flex h-10 w-10 items-center justify-center rounded-full bg-black/15 text-[14px] font-black">{t.asset[0]}</span>
              <span className="min-w-0 flex-1">
                <span className="block text-[15px] font-bold">{t.asset} · bought {t.outcome} @ {price(t.entry_price ?? t.limit_price)}</span>
                <span className="block text-[12.5px] opacity-75">{new Date(t.created_ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })} · paid {usd(t.total_cost || 0)} · {won ? "won" : lost ? "lost" : t.status === "cancelled" || t.status === "expired" ? "not filled" : "waiting for result"}</span>
              </span>
              <span className="num text-[16px] font-bold">{won || lost ? signedUsd(t.net_profit) : "…"}</span>
            </Link>
          );
        })}
      </div>
      <button onClick={onStop} disabled={busy} className="mt-6 w-full rounded-full bg-black py-4 text-[18px] font-bold text-white active:scale-[.98]">
        {done ? "Done — new run" : "Stop bot"}</button>
    </div>
  );
}

function Box({ k, v }: { k: string; v: string }) {
  return <div className="rounded-2xl bg-black/10 py-3"><div className="text-[12px] font-semibold opacity-70">{k}</div><div className="num text-[17px] font-bold">{v}</div></div>;
}

function Num({ label, value, onChange }: { label: string; value: number; onChange: (v: number) => void }) {
  return (
    <label className="rounded-2xl bg-black/10 px-3 py-2">
      <span className="block text-[11px] font-bold opacity-70">{label}</span>
      <input inputMode="decimal" value={String(value)} onChange={(e) => onChange(Number(e.target.value.replace(/[^0-9.]/g, "")) || 0)}
        className="num w-full bg-transparent text-[18px] font-bold outline-none" />
    </label>
  );
}
