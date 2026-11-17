"use client";
import clsx from "clsx";
import { Check, ChevronRight, X } from "lucide-react";
import { useMemo, useState } from "react";
import { ASSET_COLORS, Avatar, ErrorNote, ListRow } from "@/components/ui";
import { qs, usePoll } from "@/lib/api";
import { price, usd } from "@/lib/format";

const COLORS = ["#00d64b", "#ff7a45", "#e85ac8", "#409cff", "#ffb020", "#9b6bff", "#2ec4b6", "#ff453a"];

export default function ActivityPage() {
  const [aid, setAid] = useState<number | null>(null);
  const [limit, setLimit] = useState(150);
  const { data: accounts } = usePoll<any[]>("/api/accounts", 15000);
  const { data, error } = usePoll<any>(`/api/transactions${qs({ account_id: aid ?? undefined, limit })}`, 5000);
  const rows: any[] = data?.rows || [];
  const groups = useMemo(() => {
    const g: [string, any[]][] = [];
    for (const r of rows) {
      const d = new Date(r.created_ts);
      const today = new Date();
      const key = d.toDateString() === today.toDateString() ? "Today"
        : d.toLocaleDateString(undefined, { month: "long", year: "numeric", day: d.getMonth() === today.getMonth() && d.getFullYear() === today.getFullYear() ? "numeric" : undefined });
      const last = g[g.length - 1];
      if (last && last[0] === key) last[1].push(r); else g.push([key, [r]]);
    }
    return g;
  }, [rows]);

  return (
    <div className="page max-w-[900px]">
      <ErrorNote error={error} />
      <div className="-mx-4 flex gap-4 overflow-x-auto px-4 pb-2 pt-1">
        <button onClick={() => setAid(null)} className="flex w-[76px] shrink-0 flex-col items-center gap-2">
          <Avatar label="All" color="#00d64b" size={68} ring={aid === null} />
          <span className="text-[14px] font-semibold">All</span>
        </button>
        {(accounts || []).map((a, i) => (
          <button key={a.id} onClick={() => setAid(a.id)} className="flex w-[76px] shrink-0 flex-col items-center gap-2">
            <Avatar label={a.strategy_key} color={a.mode === "live" ? "#ff453a" : COLORS[i % COLORS.length]} size={68} ring={aid === a.id} />
            <span className="w-full truncate text-center text-[13px] font-semibold">{a.name.replace(/^[A-J] · /, "")}</span>
          </button>
        ))}
      </div>

      {groups.length === 0 && <div className="py-16 text-center text-[15px] text-dim">No activity yet. Start a bot from the $ tab.</div>}
      {groups.map(([k, items]) => (
        <section key={k} className="pt-5">
          <h2 className="mb-1 text-[28px] font-bold tracking-tight">{k}</h2>
          {items.map((t) => {
            const won = t.status === "won", lost = t.status === "lost";
            const dead = ["cancelled", "expired"].includes(t.status);
            const open = ["filled", "partially_filled", "pending", "unresolved"].includes(t.status);
            const amt = won || lost ? t.net_profit : t.total_cost || t.limit_price * t.requested_shares;
            return (
              <ListRow key={t.id} href={`/transactions/view/?id=${t.id}`}
                icon={
                  <div className="relative">
                    <Avatar label={t.asset[0]} color={ASSET_COLORS[t.asset]} size={52} />
                    {(won || lost) && (
                      <span className={clsx("absolute -bottom-0.5 -right-0.5 flex h-5 w-5 items-center justify-center rounded-full ring-2 ring-bg", won ? "bg-up" : "bg-down")}>
                        {won ? <Check size={12} strokeWidth={3.5} className="text-black" /> : <X size={12} strokeWidth={3.5} className="text-white" />}
                      </span>)}
                  </div>}
                title={`${t.asset} · bought ${t.outcome}`}
                sub={`${t.account_name}${t.mode === "live" ? " · REAL" : ""}`}
                meta={`${new Date(t.created_ts).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })} · ${price(t.entry_price ?? t.limit_price)} × ${(t.filled_shares || t.requested_shares).toFixed(0)} · ${t.status.replace(/_/g, " ")}`}
                right={
                  dead ? <span className="num text-[17px] font-semibold text-faint line-through">{usd(t.limit_price * t.requested_shares)}</span>
                    : open ? <span className="rounded-full bg-panel px-4 py-2 text-[14px] font-semibold">Pending</span>
                    : <span className={clsx("num text-[17px] font-semibold", won ? "text-up" : "text-ink")}>{won ? "+" : "−"}{usd(Math.abs(amt))}</span>} />
            );
          })}
        </section>
      ))}
      {rows.length >= limit && (
        <button onClick={() => setLimit(limit + 150)} className="mt-6 flex w-full items-center justify-center gap-1 rounded-full bg-panel py-3.5 text-[15px] font-semibold">
          Load more <ChevronRight size={16} /></button>
      )}
    </div>
  );
}
