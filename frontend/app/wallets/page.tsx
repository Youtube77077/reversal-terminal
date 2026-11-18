"use client";
import clsx from "clsx";
import { KeyRound, Pencil, Plus, Trash2 } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { Button, ErrorNote, inputCls } from "@/components/ui";
import { api, post } from "@/lib/api";
import { signedUsd, usd } from "@/lib/format";
import { useWallet } from "@/lib/wallet";

export default function WalletsPage() {
  const { wallets, wallet, select, reload } = useWallet();
  const [amt, setAmt] = useState<Record<number, string>>({});
  const [err, setErr] = useState<string | null>(null);
  const run = async (fn: () => Promise<any>) => { setErr(null); try { await fn(); reload(); } catch (e: any) { setErr(e.message); } };

  return (
    <div className="page max-w-[760px] space-y-3">
      <p className="text-[14px] text-dim">Each wallet has its own practice money and can have its own Polymarket keys. Use them to test different strategies side by side.</p>
      <ErrorNote error={err} />
      {wallets.map((w) => {
        const bal = w.paper.cash + w.paper.reserved;
        const a = amt[w.id] ?? "";
        const ss = w.paper.session;
        return (
          <div key={w.id} className={clsx("panel p-5 animate-rise", wallet?.id === w.id && "ring-2 ring-cash/60")}>
            <div className="flex items-center gap-2">
              <button onClick={() => select(w.id)} className="min-w-0 flex-1 text-left">
                <div className="truncate text-[20px] font-bold">{w.name}{w.is_main && <span className="ml-2 rounded-full bg-cash/15 px-2 py-0.5 text-[11px] font-bold text-accent">MAIN</span>}</div>
                <div className="text-[13px] text-dim">{wallet?.id === w.id ? "Selected" : "Tap to select"} · {w.keys?.configured ? "Polymarket keys added" : "no Polymarket keys"}</div>
              </button>
              <button title="Rename" onClick={() => { const n = prompt("Rename wallet", w.name); if (n) run(() => api(`/api/wallets/${w.id}`, { method: "PATCH", body: JSON.stringify({ name: n }) })); }}
                className="rounded-full bg-panel2 p-2.5"><Pencil size={16} /></button>
              {!w.is_main && (
                <button title="Delete" onClick={() => confirm(`Delete "${w.name}"?`) && run(() => api(`/api/wallets/${w.id}`, { method: "DELETE" }))}
                  className="rounded-full bg-down/15 p-2.5 text-down"><Trash2 size={16} /></button>)}
            </div>
            <div className="mt-4 grid grid-cols-2 gap-2">
              <div className="rounded-2xl bg-panel2/60 px-4 py-3"><div className="text-[12px] text-dim">Practice money</div><div className="num text-[22px] font-bold">{usd(bal)}</div></div>
              <div className="rounded-2xl bg-panel2/60 px-4 py-3"><div className="text-[12px] text-dim">Bot</div>
                <div className="text-[15px] font-bold">{ss?.active ? (ss.state === "running" ? "Running" : "Stopped") : "Off"}{ss?.active && <span className={clsx("num ml-2", ss.realized_pnl >= 0 ? "text-up" : "text-down")}>{signedUsd(ss.realized_pnl)}</span>}</div></div>
            </div>
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <input className={inputCls + " w-28 py-2.5"} inputMode="decimal" placeholder="$ amount" value={a} onChange={(e) => setAmt({ ...amt, [w.id]: e.target.value })} />
              <Button tone="primary" disabled={!Number(a)} onClick={() => run(() => post(`/api/accounts/${w.paper.id}/deposit`, { amount: Number(a) }))}>Add</Button>
              <Button disabled={!Number(a)} onClick={() => run(() => post(`/api/accounts/${w.paper.id}/withdraw`, { amount: Number(a) }))}>Remove</Button>
              <Button tone="warn" disabled={a === ""} onClick={() => confirm(`Set practice money to $${Number(a) || 0}?`) && run(() => post(`/api/accounts/${w.paper.id}/reset`, { balance: Number(a) || 0 }))}>Set to</Button>
              <Link href={`/live/?wallet=${w.id}`} className="ml-auto inline-flex items-center gap-1.5 rounded-full bg-panel2 px-4 py-2 text-[13px] font-semibold"><KeyRound size={14} />API keys</Link>
            </div>
          </div>
        );
      })}
      <button onClick={() => { const n = prompt("Name for the new wallet", `Testing ${wallets.length}`); if (n) run(async () => { const w = await post("/api/wallets", { name: n }); select(w.id); }); }}
        className="flex w-full items-center justify-center gap-2 rounded-full bg-panel py-4 text-[16px] font-bold active:scale-[.99]"><Plus size={18} />New wallet</button>
    </div>
  );
}
