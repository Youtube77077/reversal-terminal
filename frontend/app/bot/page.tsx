"use client";
import clsx from "clsx";
import { Check, ChevronDown, Delete } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";
import { post, usePoll } from "@/lib/api";
import { signedUsd, usd } from "@/lib/format";

type Unit = "percent" | "amount";

export default function BotPage() {
  return <Suspense><Bot /></Suspense>;
}

function Sheet({ open, onClose, title, children }: { open: boolean; onClose: () => void; title: string; children: React.ReactNode }) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-[60] bg-black/50 backdrop-blur-sm animate-fade" onClick={onClose}>
      <div onClick={(e) => e.stopPropagation()}
        className="safe-bottom absolute inset-x-0 bottom-0 mx-auto max-h-[85vh] max-w-[560px] overflow-y-auto rounded-t-4xl bg-bg px-5 pt-3 text-ink animate-sheet lg:bottom-auto lg:top-1/2 lg:-translate-y-1/2 lg:rounded-4xl lg:pb-6">
        <div className="mx-auto mb-3 h-1 w-10 rounded-full bg-line2 lg:hidden" />
        <h3 className="mb-3 text-[24px] font-bold tracking-tight">{title}</h3>
        {children}
      </div>
    </div>
  );
}

function Bot() {
  const sp = useSearchParams();
  const { data: accounts, reload } = usePoll<any[]>("/api/accounts", 4000);
  const { data: strategies } = usePoll<any[]>("/api/strategies", 0);
  const { data: summary } = usePoll<any>("/api/summary", 5000);
  const [aid, setAid] = useState<number | null>(sp.get("acct") ? Number(sp.get("acct")) : null);
  const [unit, setUnit] = useState<Unit>("percent");
  const [val, setVal] = useState("25");
  const [sl, setSl] = useState(100);
  const [tpMode, setTpMode] = useState<"off" | "percent" | "amount">("off");
  const [tpVal, setTpVal] = useState("100");
  const [strat, setStrat] = useState<string | null>(null);
  const [sheet, setSheet] = useState<null | "acct" | "sl" | "tp" | "strat">(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (aid === null && accounts?.length) setAid(accounts.find((a) => a.mode !== "live")?.id ?? accounts[0].id);
  }, [accounts, aid]);
  const acct = accounts?.find((a) => a.id === aid);
  const ss = acct?.session;
  const runningSession = ss?.active && ss.state === "running" && !acct?.halted_reason;
  const ended = ss?.active && !runningSession;
  useEffect(() => { if (acct && !strat) setStrat(acct.strategy_key); }, [acct, strat]);
  const balance = acct?.summary?.equity ?? 0;
  const num = Number(val || 0);
  const budget = unit === "percent" ? (balance * num) / 100 : num;
  const tpTarget = tpMode === "percent" ? budget * Number(tpVal || 0) / 100 : tpMode === "amount" ? Number(tpVal || 0) : null;
  const stratObj = strategies?.find((s) => s.key === strat);
  const isLive = acct?.mode === "live";
  const liveBlocked = isLive && !summary?.live_armed;

  const press = (k: string) => {
    setErr(null);
    setVal((v) => {
      if (k === "<") return v.length > 1 ? v.slice(0, -1) : "0";
      if (k === ".") return v.includes(".") ? v : v + ".";
      const nv = v === "0" ? k : v + k;
      if (nv.split(".")[1]?.length > 2) return v;
      if (unit === "percent" && Number(nv) > 100) return "100";
      return nv.length > 7 ? v : nv;
    });
  };

  const start = async () => {
    if (!acct) return;
    setBusy(true); setErr(null);
    try {
      await post(`/api/accounts/${acct.id}/session`, {
        risk_budget_mode: unit, risk_budget_value: num, stop_loss_pct: sl, take_profit_mode: tpMode,
        take_profit_value: tpMode === "off" ? 0 : Number(tpVal || 0), strategy_key: strat,
      });
      (window as any).ReversalNative?.haptic("success");
      if (navigator.vibrate) navigator.vibrate(20);
      reload();
    } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  };
  const stop = async () => {
    if (!acct) return;
    setBusy(true);
    try { await post(`/api/accounts/${acct.id}/session/stop`); reload(); } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  };

  const display = useMemo(() => (unit === "percent" ? `${val}%` : `$${val}`), [unit, val]);

  return (
    <div className="min-h-[calc(100vh-80px)] bg-cash text-oncash">
      <div className="mx-auto flex min-h-[calc(100vh-80px)] max-w-[560px] flex-col px-5 pb-32 pt-2 animate-rise lg:pb-10 lg:pt-10">
        {/* top controls */}
        <div className="flex items-center justify-between gap-2">
          <button onClick={() => setSheet("acct")} className="flex min-w-0 items-center gap-2 rounded-full bg-black/10 px-4 py-2.5 text-[14px] font-semibold active:scale-95">
            <span className={clsx("h-2 w-2 shrink-0 rounded-full", isLive ? "bg-[#7a0000]" : "bg-black/60")} />
            <span className="truncate">{acct ? acct.name : "Select account"}</span><ChevronDown size={15} className="shrink-0" />
          </button>
          <div className="flex rounded-full bg-black/10 p-1 text-[14px] font-bold">
            {(["amount", "percent"] as Unit[]).map((u) => (
              <button key={u} disabled={runningSession} onClick={() => { setUnit(u); setVal(u === "percent" ? "25" : "5"); }}
                className={clsx("rounded-full px-4 py-1.5 transition", unit === u ? "bg-black text-cash" : "text-oncash/70")}>{u === "amount" ? "$" : "%"}</button>
            ))}
          </div>
        </div>

        {runningSession || ended ? (
          <div className="mt-8 flex flex-1 flex-col">
            <div className="text-center text-[15px] font-semibold opacity-70">{runningSession ? "Bot running" : "Bot stopped"} · {isLive ? "REAL MONEY" : "paper"}</div>
            <div className={clsx("money mt-2 text-center text-[72px]")}>{signedUsd(ss.realized_pnl)}</div>
            <div className="mt-1 text-center text-[15px] opacity-70">{acct?.halted_reason || `session P&L · strategy ${acct?.strategy_key}`}</div>
            <div className="mt-8 space-y-3 rounded-4xl bg-black/10 p-5 text-[15px] font-semibold">
              <Bar label="Risk budget used" value={ss.budget_used_pct} left={`${usd(ss.loss_so_far + ss.open_at_risk)} of ${usd(ss.stop_loss_limit)}`} />
              {ss.take_profit_target != null && <Bar label="Take profit" value={ss.tp_progress_pct} left={`${usd(Math.max(0, ss.realized_pnl))} of ${usd(ss.take_profit_target)}`} />}
              <div className="grid grid-cols-3 gap-2 pt-2 text-center">
                <Mini k="Budget" v={usd(ss.risk_budget)} /><Mini k="Stop loss" v={`${ss.stop_loss_pct}%`} />
                <Mini k="Open risk" v={usd(ss.open_at_risk)} />
              </div>
            </div>
            <div className="mt-auto space-y-3 pt-8">
              <Link href="/activity" className="block rounded-full bg-black/10 py-4 text-center text-[17px] font-bold active:scale-[.98]">View activity</Link>
              {runningSession
                ? <button onClick={stop} disabled={busy} className="w-full rounded-full bg-black py-4 text-[17px] font-bold text-white active:scale-[.98]">Stop bot</button>
                : <button onClick={stop} disabled={busy} className="w-full rounded-full bg-black py-4 text-[17px] font-bold text-white active:scale-[.98]">New session</button>}
            </div>
          </div>
        ) : (
          <>
            <div className="mt-4 text-center text-[15px] font-semibold opacity-70">Risk {unit === "percent" ? "of balance" : "amount"}</div>
            <div className="money mt-1 text-center text-[76px] min-[400px]:text-[90px] lg:text-[110px]">{display}</div>
            <div className="text-center text-[15px] font-semibold opacity-75">
              {unit === "percent" ? `= ${usd(budget)} of ${usd(balance)}` : `of ${usd(balance)} balance`}
            </div>
            <button onClick={() => setSheet("strat")} className="mx-auto mt-4 flex items-center gap-1 rounded-full bg-black/10 px-4 py-2 text-[14px] font-semibold active:scale-95">
              Strategy {strat} · {stratObj?.name ?? "…"}<ChevronDown size={15} />
            </button>
            <div className="mt-4 grid grid-cols-3 gap-y-1 text-center">
              {["1", "2", "3", "4", "5", "6", "7", "8", "9", ".", "0", "<"].map((k) => (
                <button key={k} onClick={() => press(k)} className="rounded-2xl py-2.5 text-[28px] font-semibold transition active:scale-90 active:bg-black/10 min-[400px]:py-3.5">
                  {k === "<" ? <Delete className="mx-auto" size={28} /> : k === "." ? "," : k}
                </button>
              ))}
            </div>
            <div className="mt-4 grid grid-cols-2 gap-3">
              <button onClick={() => setSheet("sl")} className="rounded-full bg-black/10 py-4 text-[16px] font-bold active:scale-[.98]">Stop loss {sl}%</button>
              <button onClick={() => setSheet("tp")} className="rounded-full bg-black/10 py-4 text-[16px] font-bold active:scale-[.98]">
                Take profit {tpMode === "off" ? "off" : tpMode === "percent" ? `${tpVal}%` : `$${tpVal}`}</button>
            </div>
            {err && <div className="mt-3 rounded-2xl bg-black/15 px-4 py-2 text-center text-[14px] font-semibold">{err}</div>}
            {liveBlocked ? (
              <Link href="/live" className="mt-3 block w-full rounded-full bg-black py-4 text-center text-[17px] font-bold text-white">Arm live trading first</Link>
            ) : (
              <button onClick={start} disabled={busy || !acct || num <= 0}
                className="mt-3 w-full rounded-full bg-black py-4 text-[17px] font-bold text-white transition active:scale-[.98] disabled:opacity-50">
                {busy ? "Starting…" : `Start bot${isLive ? " · REAL MONEY" : ""}`}</button>
            )}
            <p className="mt-3 text-center text-[12px] font-medium opacity-60">
              Max loss {usd(budget * sl / 100)}{tpTarget ? ` · stops at +${usd(tpTarget)}` : ""} · open positions count as fully at risk
            </p>
          </>
        )}
      </div>

      <Sheet open={sheet === "acct"} onClose={() => setSheet(null)} title="Account">
        {(accounts || []).map((a) => (
          <button key={a.id} onClick={() => { setAid(a.id); setStrat(a.strategy_key); setSheet(null); }}
            className="flex w-full items-center gap-3 border-b border-line py-3 text-left last:border-0">
            <span className={clsx("flex h-11 w-11 items-center justify-center rounded-full text-[16px] font-black", a.mode === "live" ? "bg-down text-white" : "bg-cash text-oncash")}>{a.strategy_key}</span>
            <span className="min-w-0 flex-1"><span className="block truncate text-[16px] font-semibold">{a.name}</span>
              <span className="block text-[13px] text-dim">{a.mode === "live" ? "REAL MONEY" : "paper"} · {usd(a.summary.equity)}{a.session?.active ? ` · ${a.session.state.replace(/_/g, " ")}` : ""}</span></span>
            {a.id === aid && <Check size={18} className="text-accent" />}
          </button>
        ))}
        <Link href="/live" className="mt-3 block py-3 text-center text-[14px] font-semibold text-accent">+ Add live account</Link>
      </Sheet>

      <Sheet open={sheet === "sl"} onClose={() => setSheet(null)} title="Stop loss">
        <p className="mb-4 text-[14px] text-dim">Share of the risk budget the bot may lose. 100% = keep trading until the risk budget is $0.</p>
        <div className="money mb-2 text-center text-[56px]">{sl}%</div>
        <input type="range" min={5} max={100} step={5} value={sl} onChange={(e) => setSl(Number(e.target.value))} className="w-full" />
        <div className="mt-4 grid grid-cols-5 gap-2">{[10, 25, 50, 75, 100].map((v) => (
          <button key={v} onClick={() => setSl(v)} className={clsx("rounded-full py-2.5 text-[14px] font-semibold", sl === v ? "bg-ink text-bg" : "bg-panel")}>{v}%</button>))}</div>
        <button onClick={() => setSheet(null)} className="mb-4 mt-6 w-full rounded-full bg-cash py-4 text-[16px] font-bold text-oncash">Done · max loss {usd(budget * sl / 100)}</button>
      </Sheet>

      <Sheet open={sheet === "tp"} onClose={() => setSheet(null)} title="Take profit">
        <div className="mb-4 grid grid-cols-3 gap-2">
          {(["off", "percent", "amount"] as const).map((m) => (
            <button key={m} onClick={() => setTpMode(m)} className={clsx("rounded-full py-2.5 text-[14px] font-semibold", tpMode === m ? "bg-ink text-bg" : "bg-panel")}>
              {m === "off" ? "Off" : m === "percent" ? "% of budget" : "$ amount"}</button>))}
        </div>
        {tpMode !== "off" && (<>
          <input inputMode="decimal" value={tpVal} onChange={(e) => setTpVal(e.target.value.replace(/[^0-9.]/g, ""))}
            className="num w-full rounded-2xl bg-panel px-4 py-4 text-center text-[40px] font-semibold outline-none" />
          <div className="mt-3 flex flex-wrap justify-center gap-2">
            {(tpMode === "percent" ? [25, 50, 100, 200, 500] : [1, 5, 10, 25, 50]).map((v) => (
              <button key={v} onClick={() => setTpVal(String(v))} className="rounded-full bg-panel px-4 py-2 text-[14px] font-semibold">{tpMode === "percent" ? `${v}%` : `$${v}`}</button>))}
          </div>
        </>)}
        <p className="mt-4 text-[14px] text-dim">The bot stops once realised session profit reaches {tpTarget ? usd(tpTarget) : "the target"}.</p>
        <button onClick={() => setSheet(null)} className="mb-4 mt-5 w-full rounded-full bg-cash py-4 text-[16px] font-bold text-oncash">Done</button>
      </Sheet>

      <Sheet open={sheet === "strat"} onClose={() => setSheet(null)} title="Strategy">
        {(strategies || []).map((s) => (
          <button key={s.key} onClick={() => { setStrat(s.key); setSheet(null); }} className="flex w-full items-start gap-3 border-b border-line py-3 text-left last:border-0">
            <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-panel text-[15px] font-black">{s.key}</span>
            <span className="min-w-0 flex-1"><span className="block text-[16px] font-semibold">{s.name}</span>
              <span className="block text-[13px] leading-snug text-dim">{s.description}</span></span>
            {s.key === strat && <Check size={18} className="mt-2 text-accent" />}
          </button>
        ))}
      </Sheet>
    </div>
  );
}

function Bar({ label, value, left }: { label: string; value: number | null | undefined; left: string }) {
  const v = Math.max(0, Math.min(1, value ?? 0));
  return (
    <div>
      <div className="mb-1.5 flex justify-between text-[14px]"><span>{label}</span><span className="num opacity-70">{left}</span></div>
      <div className="h-2.5 overflow-hidden rounded-full bg-black/15"><div className="h-full rounded-full bg-black transition-all duration-500" style={{ width: `${v * 100}%` }} /></div>
    </div>
  );
}

function Mini({ k, v }: { k: string; v: string }) {
  return <div className="rounded-2xl bg-black/10 py-2.5"><div className="text-[12px] opacity-60">{k}</div><div className="num text-[16px] font-bold">{v}</div></div>;
}
