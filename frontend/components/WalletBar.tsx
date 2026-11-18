"use client";
import clsx from "clsx";
import { Plus } from "lucide-react";
import { useState } from "react";
import NameSheet from "@/components/NameSheet";
import { post } from "@/lib/api";
import { useWallet } from "@/lib/wallet";

/** Horizontal wallet switcher: Main 1 · Testing 1 · Testing 2 · + */
export default function WalletBar({ onGreen }: { onGreen?: boolean }) {
  const { wallets, wallet, select, reload } = useWallet();
  const [adding, setAdding] = useState(false);
  return (
    <div className="-mx-1 flex gap-2 overflow-x-auto px-1 pb-1">
      {wallets.map((w) => (
        <button key={w.id} onClick={() => select(w.id)}
          className={clsx("shrink-0 whitespace-nowrap rounded-full px-4 py-2 text-[14px] font-bold transition active:scale-95",
            wallet?.id === w.id ? (onGreen ? "bg-black text-white" : "bg-ink text-bg") : onGreen ? "bg-black/10" : "bg-panel2 text-dim")}>
          {w.name}
        </button>
      ))}
      <button onClick={() => setAdding(true)} aria-label="New wallet"
        className={clsx("flex shrink-0 items-center gap-1 rounded-full px-3 py-2 text-[14px] font-bold", onGreen ? "bg-black/10" : "bg-panel2 text-dim")}>
        <Plus size={15} />New</button>
      <NameSheet open={adding} title="New wallet" cta="Create wallet" initial={`Testing ${wallets.length}`}
        onClose={() => setAdding(false)}
        onSave={async (name) => { const w = await post("/api/wallets", { name }); reload(); select(w.id); }} />
    </div>
  );
}
