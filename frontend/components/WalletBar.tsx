"use client";
import clsx from "clsx";
import { Plus } from "lucide-react";
import { post } from "@/lib/api";
import { useWallet } from "@/lib/wallet";

/** Horizontal wallet switcher: Main 1 · Testing 1 · Testing 2 · + */
export default function WalletBar({ onGreen }: { onGreen?: boolean }) {
  const { wallets, wallet, select, reload } = useWallet();
  const add = async () => {
    const name = prompt("Name for the new wallet", `Testing ${wallets.length}`);
    if (!name) return;
    const w = await post("/api/wallets", { name });
    reload(); select(w.id);
  };
  return (
    <div className="-mx-1 flex gap-2 overflow-x-auto px-1 pb-1">
      {wallets.map((w) => (
        <button key={w.id} onClick={() => select(w.id)}
          className={clsx("shrink-0 whitespace-nowrap rounded-full px-4 py-2 text-[14px] font-bold transition active:scale-95",
            wallet?.id === w.id ? (onGreen ? "bg-black text-white" : "bg-ink text-bg") : onGreen ? "bg-black/10" : "bg-panel2 text-dim")}>
          {w.name}
        </button>
      ))}
      <button onClick={add} aria-label="New wallet"
        className={clsx("flex shrink-0 items-center gap-1 rounded-full px-3 py-2 text-[14px] font-bold", onGreen ? "bg-black/10" : "bg-panel2 text-dim")}>
        <Plus size={15} />New</button>
    </div>
  );
}
