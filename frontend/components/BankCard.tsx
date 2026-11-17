"use client";
import clsx from "clsx";
import { ArrowUpRight, Wifi } from "lucide-react";
import Link from "next/link";
import { useRef, useState } from "react";
import { AnimatedNumber } from "./Charts2";

const usd = (v: number) => `$${v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

/** A clean, bank-style card showing balance and bot status. Tilts on hover/touch. */
export default function BankCard({ balance, todayPnl, running, live, hidden, href = "/bot" }: {
  balance: number | null | undefined; todayPnl: number | null | undefined; running: number; live: boolean; hidden?: boolean; href?: string;
}) {
  const ref = useRef<HTMLAnchorElement>(null);
  const [tilt, setTilt] = useState({ x: 0, y: 0 });
  const move = (cx: number, cy: number) => {
    const r = ref.current?.getBoundingClientRect();
    if (!r) return;
    const px = (cx - r.left) / r.width - 0.5, py = (cy - r.top) / r.height - 0.5;
    setTilt({ x: -py * 9, y: px * 11 });
  };
  return (
    <Link ref={ref} href={href}
      onMouseMove={(e) => move(e.clientX, e.clientY)} onMouseLeave={() => setTilt({ x: 0, y: 0 })}
      onTouchMove={(e) => move(e.touches[0].clientX, e.touches[0].clientY)} onTouchEnd={() => setTilt({ x: 0, y: 0 })}
      className="card-tilt relative block aspect-[1.586] w-full max-w-[460px] overflow-hidden rounded-[26px] text-white shadow-[0_24px_60px_-18px_rgba(0,140,120,.55)] animate-pop"
      style={{ transform: `perspective(900px) rotateX(${tilt.x}deg) rotateY(${tilt.y}deg)` }}>
      <div className={clsx("absolute inset-0", live
        ? "bg-[radial-gradient(120%_140%_at_0%_0%,#ff6a3d_0%,#d81b60_45%,#4a148c_100%)]"
        : "bg-[radial-gradient(120%_140%_at_0%_0%,#19e07a_0%,#00a88f_42%,#1659c7_100%)]")} />
      <div className="absolute inset-0 opacity-[.18] [background:repeating-radial-gradient(circle_at_85%_120%,transparent_0_22px,rgba(255,255,255,.9)_23px_24px)]" />
      <div className="absolute -right-16 -top-20 h-56 w-56 rounded-full bg-white/10 blur-2xl" />
      <div className="card-shine" />
      <div className="relative flex h-full flex-col justify-between p-5 sm:p-6">
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-2">
            <span className="flex h-8 w-8 items-center justify-center rounded-[10px] bg-white/20 text-[18px] font-black backdrop-blur">$</span>
            <span className="text-[17px] font-bold tracking-[0.18em]">REVERSAL</span>
          </div>
          <div className="flex items-center gap-2">
            <span className={clsx("rounded-full px-2.5 py-1 text-[11px] font-bold tracking-wider backdrop-blur", live ? "bg-white text-[#c2185b] live-pulse" : "bg-white/20")}>
              {live ? "LIVE $" : "PAPER"}</span>
            <Wifi size={20} className="rotate-90 opacity-80" />
          </div>
        </div>
        <div className="flex items-center gap-4">
          <svg width="46" height="34" viewBox="0 0 46 34" className="shrink-0 drop-shadow">
            <defs><linearGradient id="chip" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor="#f6e27a" /><stop offset=".5" stopColor="#d4a93c" /><stop offset="1" stopColor="#f3d36b" /></linearGradient></defs>
            <rect x="1" y="1" width="44" height="32" rx="7" fill="url(#chip)" />
            <path d="M1 12h13M1 22h13M32 12h13M32 22h13M14 1v32M32 1v32M14 17h18" stroke="#a37d22" strokeWidth="1.2" fill="none" opacity=".7" />
          </svg>
          <div className="min-w-0">
            <div className="text-[12px] font-semibold uppercase tracking-wider opacity-80">Balance</div>
            <div className="truncate text-[34px] font-bold leading-none tracking-tight sm:text-[40px]">
              {hidden ? "••••••" : <AnimatedNumber value={balance ?? null} format={usd} />}
            </div>
          </div>
        </div>
        <div className="flex items-end justify-between gap-3">
          <div>
            <div className="num text-[15px] tracking-[0.22em] opacity-90">•••• •••• 5MIN</div>
            <div className="mt-1 flex items-center gap-1.5 text-[12px] font-semibold opacity-90">
              <span className={clsx("h-2 w-2 rounded-full", running ? "bg-white live-pulse" : "bg-white/40")} />
              {running ? `${running} bot${running > 1 ? "s" : ""} running` : "Tap to start your bot"}
            </div>
          </div>
          <div className="text-right">
            <div className="text-[11px] font-semibold uppercase tracking-wider opacity-75">Today</div>
            <div className="num text-[17px] font-bold">{hidden ? "••" : `${(todayPnl ?? 0) >= 0 ? "+" : "-"}${usd(Math.abs(todayPnl ?? 0))}`}</div>
          </div>
        </div>
      </div>
      <span className="absolute bottom-4 right-1/2 hidden translate-x-1/2 items-center gap-1 rounded-full bg-white/15 px-3 py-1 text-[11px] font-semibold backdrop-blur sm:flex">
        Start bot <ArrowUpRight size={12} /></span>
    </Link>
  );
}
