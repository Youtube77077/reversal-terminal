"use client";
import clsx from "clsx";
import { RotateCcw } from "lucide-react";
import { useState } from "react";
import { post } from "@/lib/api";
import { ErrorNote, inputCls } from "./ui";

const OPTIONS = [
  { key: "paper", title: "Paper trading", sub: "All paper trades, signals, P&L, experiments and balance history. Balances go back to the amount below." },
  { key: "live", title: "Live trading records", sub: "This app's record of live trades and P&L. Your real Polymarket wallet and positions are NOT touched." },
  { key: "research", title: "Analytics & market data", sub: "Recorded markets, checkpoints, reversal statistics, observations and history." },
] as const;

/** Reset stats to zero. A full database backup is made first so nothing is lost for good. */
export default function ResetCard({ onDone, bare }: { onDone?: () => void; bare?: boolean }) {
  const [sel, setSel] = useState<Record<string, boolean>>({ paper: true, live: false, research: false });
  const [bal, setBal] = useState("20");
  const [pw, setPw] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [res, setRes] = useState<any>(null);
  const any = Object.values(sel).some(Boolean);
  const go = async () => {
    if (!confirm("Reset the selected stats to zero? A backup is saved first.")) return;
    setBusy(true); setErr(null); setRes(null);
    try {
      const r = await post("/api/admin/reset", { ...sel, starting_balance: Number(bal), password: pw, confirm: "RESET" });
      setRes(r); onDone?.();
    } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  };
  return (
    <div className={clsx(!bare && "panel p-5")}>
      {!bare && <h2 className="panel-title mb-1">Reset stats</h2>}
      <p className="mb-3 text-[13px] text-dim">Start fresh from zero. A complete backup of the database is saved first.</p>
      <div className="space-y-2">
        {OPTIONS.map((o) => (
          <button key={o.key} onClick={() => setSel((s) => ({ ...s, [o.key]: !s[o.key] }))}
            className={clsx("flex w-full items-start gap-3 rounded-2xl px-4 py-3 text-left transition", sel[o.key] ? "bg-cash/15 ring-1 ring-cash/50" : "bg-panel2/60")}>
            <span className={clsx("mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-md text-[12px] font-black", sel[o.key] ? "bg-cash text-oncash" : "bg-panel2")}>{sel[o.key] ? "✓" : ""}</span>
            <span><span className="block text-[15px] font-semibold">{o.title}</span><span className="block text-[12.5px] text-dim">{o.sub}</span></span>
          </button>
        ))}
      </div>
      <div className="mt-3 grid grid-cols-2 gap-2">
        <label className="text-[12px] text-dim">Paper balance after reset
          <input className={inputCls + " mt-1 py-2.5"} inputMode="decimal" value={bal} onChange={(e) => setBal(e.target.value)} /></label>
        <label className="text-[12px] text-dim">App password
          <input type="password" className={inputCls + " mt-1 py-2.5"} value={pw} onChange={(e) => setPw(e.target.value)} /></label>
      </div>
      <button onClick={go} disabled={!any || busy}
        className="mt-4 flex w-full items-center justify-center gap-2 rounded-full bg-down py-3.5 text-[15px] font-bold text-white transition active:scale-[.98] disabled:opacity-40">
        <RotateCcw size={16} />{busy ? "Resetting…" : "Reset to zero"}</button>
      <ErrorNote error={err} />
      {res && <div className="mt-3 rounded-2xl bg-up/10 px-4 py-3 text-[13px] text-up">Reset done: {res.reset.join(", ")}. Backup saved.</div>}
    </div>
  );
}
