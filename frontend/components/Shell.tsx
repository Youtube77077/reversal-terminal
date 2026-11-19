"use client";
import clsx from "clsx";
import {
  Activity, BarChart3, Beaker, Cable, ChevronRight, CircleDollarSign, Clock, FlaskConical, History, LayoutGrid,
  LineChart, LogOut, Moon, PlayCircle, Radar, Settings, ShieldAlert, Sun, Wallet, X, Zap,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { post, usePoll } from "@/lib/api";
import { useLive } from "@/lib/live";
import { isNativeApp, useTheme } from "@/lib/theme";
import Explain from "./Explain";

const TABS = [
  { href: "/", label: "Home", icon: Wallet },
  { href: "/markets", label: "Markets", icon: LineChart },
  { href: "/bot", label: "Bot", icon: CircleDollarSign },
  { href: "/activity", label: "Activity", icon: Clock },
  { href: "/analytics", label: "Analytics", icon: BarChart3 },
];

export const MORE = [
  { href: "/wallets", label: "Wallets", sub: "Main 1, testing wallets, money & keys", icon: Wallet },
  { href: "/strategies", label: "Strategy builder", sub: "Create, test, save & share your own strategies", icon: Beaker },
  { href: "/report", label: "Bot report", sub: "Every trade, predicted vs real, fees, drawdown, skipped signals", icon: Activity },
  { href: "/coins", label: "Coin analysis", sub: "Every coin: how it moves, flips, wins, by hour", icon: BarChart3 },
  { href: "/dashboard", label: "Dashboard", sub: "Full operating overview", icon: LayoutGrid },
  { href: "/scanner", label: "Reversal Scanner", sub: "Live cheap-underdog finder", icon: Radar },
  { href: "/trading", label: "Trading Engine", sub: "Accounts, risk limits, orders", icon: Zap },
  { href: "/transactions", label: "Transactions", sub: "Every trade, export CSV/JSON", icon: History },
  { href: "/replay", label: "Market Replay", sub: "Second-by-second playback", icon: PlayCircle },
  { href: "/strategy-lab", label: "Strategy Lab", sub: "Backtests, calculator", icon: Beaker },
  { href: "/experiments", label: "Experiments", sub: "24h/48h runs & reports", icon: FlaskConical },
  { href: "/live", label: "Live trading", sub: "Real-money mode & keys", icon: ShieldAlert },
  { href: "/connections", label: "API Connections", sub: "Data sources & health", icon: Cable },
  { href: "/settings", label: "Settings", sub: "Notifications, backups", icon: Settings },
];

const TITLES: Record<string, string> = {
  "/": "Home", "/markets": "Markets", "/bot": "", "/activity": "Activity", "/analytics": "Analytics",
  ...Object.fromEntries(MORE.map((m) => [m.href, m.label])),
};

function compact(v: number | undefined | null) {
  if (v === undefined || v === null || !isFinite(v)) return "$—";
  if (Math.abs(v) >= 10000) return `$${(v / 1000).toFixed(0)}k`;
  return `$${v >= 100 ? v.toFixed(0) : v.toFixed(v % 1 ? 2 : 0)}`;
}

export default function Shell({ children }: { children: React.ReactNode }) {
  const path = usePathname() || "/";
  const { theme, toggle } = useTheme();
  const { connected } = useLive();
  const { data: sum } = usePoll<any>("/api/summary", 8000);
  const [more, setMore] = useState(false);
  const [native, setNative] = useState(false);
  const [faceid, setFaceid] = useState(false);
  useEffect(() => { setNative(isNativeApp()); try { setFaceid(localStorage.getItem("rt_faceid") === "1"); } catch {} }, []);
  useEffect(() => setMore(false), [path]);
  const norm = path.replace(/\/$/, "") || "/";
  const onBot = norm === "/bot";
  const title = TITLES[norm] ?? TITLES["/" + norm.split("/")[1]] ?? "";
  const live = !!sum?.live_armed;
  const isActive = (href: string) => (href === "/" ? norm === "/" : norm === href || norm.startsWith(href + "/"));

  return (
    <div className={clsx("min-h-screen", onBot && "bg-cash text-oncash")}>
      {/* ---------------- desktop sidebar ---------------- */}
      <aside className="fixed inset-y-0 left-0 z-40 hidden w-[248px] flex-col bg-bg px-4 py-6 lg:flex">
        <Link href="/" className="mb-6 flex items-center gap-2 px-2">
          <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-cash text-[20px] font-black text-oncash">$</span>
          <span className="text-[19px] font-bold tracking-tight text-ink">Reversal</span>
        </Link>
        <nav className="flex flex-col gap-0.5">
          {TABS.map((t) => (
            <Link key={t.href} href={t.href}
              className={clsx("flex items-center gap-3 rounded-2xl px-3 py-2.5 text-[15px] font-semibold transition",
                isActive(t.href) ? "bg-panel text-ink" : "text-dim hover:bg-panel/60 hover:text-ink")}>
              <t.icon size={19} />{t.label}
              {t.href === "/" && <span className="num ml-auto text-[12px] text-faint">{compact(sum?.equity)}</span>}
            </Link>
          ))}
        </nav>
        <div className="mb-1 mt-6 px-3 text-[11px] font-semibold uppercase tracking-wider text-faint">More</div>
        <nav className="flex flex-col gap-0.5 overflow-y-auto">
          {MORE.map((t) => (
            <Link key={t.href} href={t.href}
              className={clsx("flex items-center gap-3 rounded-2xl px-3 py-2 text-[13.5px] font-medium transition",
                isActive(t.href) ? "bg-panel text-ink" : "text-dim hover:bg-panel/60 hover:text-ink")}>
              <t.icon size={16} />{t.label}
            </Link>
          ))}
        </nav>
        <div className="mt-auto space-y-2 px-2 pt-4">
          <div className="flex items-center gap-2 text-[12px]">
            <span className={clsx("h-2 w-2 rounded-full", connected ? "bg-up" : "bg-down")} />
            <span className="text-dim">{connected ? "Data live" : "Offline"}</span>
            <span className={clsx("ml-auto rounded-full px-2 py-0.5 text-[11px] font-bold", live ? "bg-down/20 text-down" : "bg-info/15 text-info")}>
              {live ? "LIVE $" : "PAPER"}</span>
          </div>
          <div className="flex gap-2">
            <button onClick={toggle} className="flex flex-1 items-center justify-center gap-2 rounded-full bg-panel py-2 text-[13px] font-semibold text-dim hover:text-ink">
              {theme === "dark" ? <Sun size={14} /> : <Moon size={14} />}{theme === "dark" ? "Light" : "Dark"}
            </button>
            <button onClick={async () => { await post("/api/auth/logout"); location.href = "/login/"; }}
              className="flex items-center justify-center rounded-full bg-panel px-3 text-dim hover:text-ink" title="Log out"><LogOut size={14} /></button>
          </div>
        </div>
      </aside>

      {/* ---------------- mobile header ---------------- */}
      <header className={clsx("safe-top sticky z-30 lg:hidden", live ? "top-6" : "top-0", onBot ? "bg-cash" : "bg-bg/85 backdrop-blur-xl")}>
        <div className="flex items-center gap-3 px-5 pb-2 pt-3">
          <h1 className={clsx("title-xl min-w-0 flex-1 truncate", onBot && "text-oncash")}>{title}</h1>
          <button onClick={toggle} aria-label="Toggle theme"
            className={clsx("flex h-11 w-11 items-center justify-center rounded-full transition active:scale-95",
              onBot ? "bg-black/10 text-oncash" : "bg-panel text-ink")}>
            {theme === "dark" ? <Sun size={19} /> : <Moon size={19} />}
          </button>
          <button onClick={() => setMore(true)} aria-label="More"
            className={clsx("flex h-11 w-11 items-center justify-center rounded-full text-[15px] font-black transition active:scale-95",
              onBot ? "bg-black/10 text-oncash" : "bg-cash text-oncash")}>
            {live ? "L" : "R"}
          </button>
        </div>
      </header>

      {live && (
        <Link href="/live" className={clsx("fixed left-0 right-0 z-[45] flex items-center justify-center gap-2 bg-down py-1 text-[12px] font-bold text-white lg:left-[248px]", "top-0")}>
          <span className="h-2 w-2 rounded-full bg-white live-pulse" />LIVE TRADING ON — REAL MONEY
        </Link>
      )}
      <main className={clsx("lg:pl-[248px]", live && "pt-6")}>
        {title && norm !== "/" && <h1 className="title-xl mx-auto hidden max-w-[1600px] px-8 pt-8 lg:block">{title}</h1>}
        {!onBot && <Explain />}
        <div key={norm} className="animate-page">{children}</div>
      </main>

      {/* ---------------- floating 5-tab bar (mobile) ---------------- */}
      <nav className="safe-bottom fixed inset-x-0 bottom-0 z-40 flex justify-center px-3 lg:hidden">
        <div className={clsx("flex w-full max-w-[460px] items-center justify-between rounded-full p-1.5 shadow-2xl backdrop-blur-xl",
          onBot ? "bg-black/10" : "bg-panel/90 ring-1 ring-line/60")}>
          {TABS.map((t) => {
            const a = isActive(t.href);
            return (
              <Link key={t.href} href={t.href} aria-label={t.label}
                className={clsx("flex h-12 flex-1 items-center justify-center rounded-full transition-all duration-200 active:scale-95",
                  a ? (onBot ? "bg-black/15 text-oncash" : "bg-panel2 text-ink") : onBot ? "text-oncash/60" : "text-faint")}>
                {t.href === "/" ? <span className="num text-[17px] font-bold">{compact(sum?.equity)}</span>
                  : t.href === "/bot" ? <span className="text-[24px] font-black leading-none">$</span>
                  : <t.icon size={23} strokeWidth={2.4} />}
              </Link>
            );
          })}
        </div>
      </nav>

      {/* ---------------- More sheet (mobile) ---------------- */}
      {more && (
        <div className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm animate-fade lg:hidden" onClick={() => setMore(false)}>
          <div onClick={(e) => e.stopPropagation()} className="safe-bottom absolute inset-x-0 bottom-0 max-h-[88vh] overflow-y-auto rounded-t-4xl bg-bg px-5 pt-3 animate-sheet">
            <div className="mx-auto mb-3 h-1 w-10 rounded-full bg-line2" />
            <div className="mb-2 flex items-center">
              <h2 className="text-[28px] font-bold tracking-tight">More</h2>
              <button onClick={() => setMore(false)} className="ml-auto rounded-full bg-panel p-2.5"><X size={18} /></button>
            </div>
            <div className="mb-3 flex items-center gap-2 text-[13px]">
              <span className={clsx("h-2 w-2 rounded-full", connected ? "bg-up" : "bg-down")} />
              <span className="text-dim">{connected ? "Data live" : "Offline"}</span>
              <span className={clsx("ml-auto rounded-full px-2.5 py-1 text-[12px] font-bold", live ? "bg-down/20 text-down" : "bg-info/15 text-info")}>
                {live ? "LIVE MONEY ARMED" : "PAPER MODE"}</span>
            </div>
            {MORE.map((m) => (
              <Link key={m.href} href={m.href} className="flex items-center gap-4 py-3 active:opacity-70">
                <span className="flex h-11 w-11 items-center justify-center rounded-full bg-panel"><m.icon size={20} /></span>
                <span className="min-w-0 flex-1"><span className="block text-[16px] font-semibold">{m.label}</span>
                  <span className="block truncate text-[13px] text-dim">{m.sub}</span></span>
                <ChevronRight size={18} className="text-faint" />
              </Link>
            ))}
            {native && (
              <div className="mt-2 rounded-3xl bg-panel px-4 py-1">
                <div className="flex items-center py-3">
                  <span className="text-[15px] font-semibold">Face ID lock</span>
                  <button onClick={() => { const v = !faceid; setFaceid(v); try { localStorage.setItem("rt_faceid", v ? "1" : "0"); } catch {} (window as any).ReversalNative?.setFaceID(v); }}
                    className={clsx("ml-auto h-7 w-12 rounded-full p-0.5 transition", faceid ? "bg-cash" : "bg-panel2")}>
                    <span className={clsx("block h-6 w-6 rounded-full bg-white transition", faceid && "translate-x-5")} /></button>
                </div>
                <button onClick={() => (window as any).ReversalNative?.changeServer()} className="w-full border-t border-line py-3 text-left text-[15px] font-semibold">Change server address</button>
              </div>
            )}
            <button onClick={async () => { await post("/api/auth/logout"); location.href = "/login/"; }}
              className="mb-6 mt-3 flex w-full items-center justify-center gap-2 rounded-full bg-panel py-3.5 text-[15px] font-semibold text-down">
              <LogOut size={16} />Log out</button>
          </div>
        </div>
      )}
    </div>
  );
}
