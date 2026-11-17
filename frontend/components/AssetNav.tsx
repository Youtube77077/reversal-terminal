"use client";
import clsx from "clsx";
import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { Suspense } from "react";

const ITEMS = [["", "All markets"], ...["BTC", "ETH", "SOL", "XRP", "DOGE", "HYPE", "BNB"].map((a) => [a, a])];

export default function AssetNav() {
  return <Suspense><AssetNavInner /></Suspense>;
}

function AssetNavInner() {
  const p = (usePathname() || "").replace(/\/$/, "");
  const s = useSearchParams().get("s") || "";
  const cur = p.endsWith("/asset") ? s : "";
  return (
    <div className="-mx-1 flex items-center gap-1.5 overflow-x-auto px-1 pb-1">
      {ITEMS.map(([sym, label]) => (
        <Link key={sym || "all"} href={sym ? `/analytics/asset/?s=${sym}` : "/analytics"}
          className={clsx("whitespace-nowrap rounded-full px-3.5 py-1.5 text-[13px] font-semibold transition active:scale-95",
            cur === sym ? "bg-ink text-bg" : "bg-panel2 text-dim hover:text-ink")}>
          {label}
        </Link>
      ))}
    </div>
  );
}

export function Verdict({ v }: { v?: string | null }) {
  if (!v) return <span className="text-faint">—</span>;
  const cls = v.startsWith("PROFITABLE") ? "border-up/50 bg-up/10 text-up" : v.startsWith("UNPROFITABLE") ? "border-down/50 bg-down/10 text-down"
    : v === "inconclusive" ? "border-warn/40 bg-warn/5 text-warn" : "border-line2 text-faint";
  return <span className={clsx("whitespace-nowrap rounded-sm border px-1.5 py-[1px] text-2xs font-semibold", cls)}>{v}</span>;
}
