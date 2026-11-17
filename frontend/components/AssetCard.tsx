"use client";
import clsx from "clsx";
import Link from "next/link";
import { dur, isNum, pct, price, spot } from "@/lib/format";
import { Pill, statusKind } from "./ui";

export default function AssetCard({ asset, name, state, status, detail }: {
  asset: string; name: string; state: any; status?: string; detail?: string | null;
}) {
  const s = state;
  const stale = s?.stale || (s && Date.now() - s.server_ts > 5000);
  const kind = !s ? statusKind(status) : stale ? "OFFLINE" : statusKind(status);
  const fav = s?.favourite;
  const secs = s?.secs_remaining;
  const urgent = isNum(secs) && secs <= 30;
  const distBps = s?.dist_bps;
  return (
    <div className={clsx("panel flex min-w-0 flex-col animate-rise", urgent && "ring-1 ring-warn/50")}>
      <div className="flex items-center justify-between px-4 pb-1 pt-3">
        <div className="flex items-baseline gap-2">
          <span className="text-[17px] font-bold text-ink">{asset}</span>
          <span className="text-2xs text-faint">{name}</span>
        </div>
        <Pill kind={kind} />
      </div>
      {!s ? (
        <div className="px-3 py-4 text-2xs text-faint">{detail || "Waiting for an active 5-minute market…"}</div>
      ) : (
        <div className="space-y-2.5 px-4 pb-4 pt-2">
          <div className="flex items-center justify-between">
            <Link href={`/markets?id=${s.market_id}`} className="mono truncate text-2xs text-dim hover:text-ink" title={s.question}>
              {s.slug}
            </Link>
            <span className={clsx("mono text-xs font-semibold", urgent ? "text-warn" : "text-ink")}>T-{dur(secs)}</span>
          </div>
          <div className="grid grid-cols-2 gap-2">
            {(["UP", "DOWN"] as const).map((side) => {
              const k = side.toLowerCase();
              const isFav = fav === side;
              return (
                <div key={side} className={clsx("rounded-2xl px-3 py-2",
                  isFav ? (side === "UP" ? "bg-up/10" : "bg-down/10") : "bg-panel2/70")}>
                  <div className="flex items-center justify-between">
                    <span className={clsx("text-2xs font-semibold", side === "UP" ? "text-up" : "text-down")}>{side}</span>
                    <span className="text-2xs text-faint">{isFav ? "FAV" : fav ? "CHEAP" : ""}</span>
                  </div>
                  <div className="num text-[22px] font-semibold tracking-tight" title="implied probability from the effective book">
                    {isNum(s.up_prob) ? pct(side === "UP" ? s.up_prob : 1 - s.up_prob, 1) : "—"}</div>
                  <div className="mono flex justify-between text-2xs text-dim">
                    <span title="best bid">b {price(s[`${k}_bid`])}</span>
                    <span title="best ask (executable)">a {price(s[`${k}_ask`])}</span>
                  </div>
                  <div className="mono text-2xs text-faint">spr {price(s[`${k}_spread`])} · liq ${isNum(s[`${k}_ask_liq`]) ? s[`${k}_ask_liq`].toFixed(0) : "—"}</div>
                </div>
              );
            })}
          </div>
          <div className="mono grid grid-cols-2 gap-x-3 gap-y-0.5 text-2xs">
            <span className="text-faint">spot ({s.spot_source})</span><span className="text-right text-ink">{spot(s.spot)}</span>
            <span className="text-faint">threshold (open)</span><span className="text-right text-ink">{spot(s.open_price)}</span>
            <span className="text-faint">distance</span>
            <span className={clsx("text-right", isNum(distBps) ? (distBps >= 0 ? "text-up" : "text-down") : "text-faint")}>
              {isNum(s.dist_abs) ? `${s.dist_abs >= 0 ? "+" : ""}${spot(s.dist_abs)}` : "—"} ({isNum(distBps) ? `${distBps.toFixed(2)}bp` : "—"})
            </span>
            <span className="text-faint">est. 60s TWAP</span><span className="text-right text-dim">{spot(s.twap60_est)}</span>
            <span className="text-faint">favourite</span>
            <span className="text-right">{fav ? <span className={fav === "UP" ? "text-up" : "text-down"}>{fav} {pct(s.fav_prob, 1)}</span> : "—"}</span>
            <span className="text-faint">cheap outcome ask</span><span className="text-right text-warn">{s.underdog ? `${s.underdog} @ ${price(s.underdog_ask)}` : "—"}</span>
          </div>
          {!s.fee_verified && <div className="text-2xs text-warn">fee schedule unverified — estimates used</div>}
          {detail && kind !== "LIVE" && <div className="text-2xs text-warn">{detail}</div>}
        </div>
      )}
    </div>
  );
}
