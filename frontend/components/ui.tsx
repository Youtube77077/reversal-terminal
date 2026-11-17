"use client";
import clsx from "clsx";
import { ChevronDown, ChevronUp, Download, X } from "lucide-react";
import { ReactNode, useMemo, useState } from "react";
import { downloadText, toCSV } from "@/lib/api";
import { isNum, pct } from "@/lib/format";

export function Panel({ title, right, children, className, pad = true, sub }: {
  title?: ReactNode; right?: ReactNode; children: ReactNode; className?: string; pad?: boolean; sub?: ReactNode;
}) {
  return (
    <section className={clsx("panel animate-rise", className)}>
      {(title || right) && (
        <header className="flex flex-wrap items-start justify-between gap-3 px-5 pb-1 pt-4">
          <div className="min-w-0">
            <h2 className="panel-title">{title}</h2>
            {sub && <div className="mt-0.5 text-[12px] leading-snug text-dim">{sub}</div>}
          </div>
          <div className="flex shrink-0 flex-wrap items-center gap-2">{right}</div>
        </header>
      )}
      <div className={clsx(pad && "px-5 pb-5 pt-3")}>{children}</div>
    </section>
  );
}

export function Stat({ label, value, sub, tone, onClick, title }: {
  label: string; value: ReactNode; sub?: ReactNode; tone?: "up" | "down" | "warn" | "dim"; onClick?: () => void; title?: string;
}) {
  return (
    <div title={title} onClick={onClick}
      className={clsx("min-w-0 rounded-2xl bg-panel2/70 px-4 py-3", onClick && "cursor-pointer transition active:scale-[.98] hover:bg-panel2")}>
      <div className="label truncate">{label}</div>
      <div className={clsx("num mt-1 truncate text-[19px] font-semibold tracking-tight",
        tone === "up" && "text-up", tone === "down" && "text-down", tone === "warn" && "text-warn", tone === "dim" && "text-dim")}>
        {value}
      </div>
      {sub && <div className="mt-0.5 truncate text-[11px] text-faint">{sub}</div>}
    </div>
  );
}

const STATUS_STYLES: Record<string, string> = {
  LIVE: "bg-up/15 text-up",
  SIMULATED: "bg-info/15 text-info",
  OFFLINE: "bg-down/15 text-down",
  DEGRADED: "bg-warn/15 text-warn",
  PAPER: "bg-info/15 text-info",
  REAL: "bg-down/20 text-down",
  DISABLED: "bg-panel2 text-faint",
  WAITING: "bg-panel2 text-dim",
  UNAVAILABLE: "bg-warn/15 text-warn",
  ESTIMATED: "bg-warn/10 text-warn",
};

export function Pill({ kind, children, className }: { kind: string; children?: ReactNode; className?: string }) {
  const k = kind.toUpperCase();
  return (
    <span className={clsx("inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2.5 py-[3px] text-[11px] font-semibold",
      STATUS_STYLES[k] || "bg-panel2 text-dim", className)}>
      {k === "LIVE" && <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-up" />}
      {children ?? k}
    </span>
  );
}

export function statusKind(s?: string | null): string {
  switch (s) {
    case "live": case "ok": return "LIVE";
    case "degraded": return "DEGRADED";
    case "waiting": case "starting": case "unknown": return "WAITING";
    case "unavailable": return "UNAVAILABLE";
    case "disabled": return "DISABLED";
    default: return "OFFLINE";
  }
}

export function Button({ children, onClick, tone = "default", disabled, className, size = "md", title, type }: {
  children: ReactNode; onClick?: () => void; tone?: "default" | "primary" | "danger" | "ghost" | "warn" | "solid"; disabled?: boolean;
  className?: string; size?: "sm" | "md" | "lg"; title?: string; type?: "button" | "submit";
}) {
  return (
    <button type={type || "button"} title={title} disabled={disabled} onClick={onClick}
      className={clsx(
        "inline-flex items-center justify-center gap-1.5 whitespace-nowrap rounded-full font-semibold transition active:scale-[.97] disabled:cursor-not-allowed disabled:opacity-40",
        size === "sm" ? "px-3 py-1 text-[12px]" : size === "lg" ? "px-6 py-3.5 text-[16px]" : "px-4 py-2 text-[13px]",
        tone === "default" && "bg-panel2 text-ink hover:brightness-110",
        tone === "primary" && "bg-cash text-oncash hover:brightness-105",
        tone === "solid" && "bg-ink text-bg hover:opacity-90",
        tone === "danger" && "bg-down/15 text-down hover:bg-down/25",
        tone === "warn" && "bg-warn/15 text-warn hover:bg-warn/25",
        tone === "ghost" && "text-dim hover:text-ink",
        className,
      )}>
      {children}
    </button>
  );
}

export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return (
    <label className="flex min-w-0 flex-col gap-1.5">
      {label && <span className="label">{label}</span>}
      {children}
      {hint && <span className="text-[11px] text-faint">{hint}</span>}
    </label>
  );
}

export const inputCls = "num w-full rounded-xl bg-panel2 px-3 py-2 text-[13px] text-ink outline-none ring-0 placeholder:text-faint focus:ring-2 focus:ring-accent/40";

export function Select({ value, onChange, options, className }: {
  value: any; onChange: (v: string) => void; options: (string | { value: any; label: string })[]; className?: string;
}) {
  return (
    <select value={value ?? ""} onChange={(e) => onChange(e.target.value)} className={clsx(inputCls, "w-auto pr-7", className)}>
      {options.map((o) => typeof o === "string"
        ? <option key={o} value={o}>{o}</option>
        : <option key={String(o.value)} value={o.value}>{o.label}</option>)}
    </select>
  );
}

export function Tabs({ tabs, value, onChange }: { tabs: { key: string; label: string }[]; value: string; onChange: (k: string) => void }) {
  return (
    <div className="-mx-1 flex gap-1.5 overflow-x-auto px-1 pb-1">
      {tabs.map((t) => (
        <button key={t.key} onClick={() => onChange(t.key)}
          className={clsx("whitespace-nowrap rounded-full px-3.5 py-1.5 text-[13px] font-semibold transition active:scale-[.97]",
            value === t.key ? "bg-ink text-bg" : "bg-panel2 text-dim hover:text-ink")}>
          {t.label}
        </button>
      ))}
    </div>
  );
}

export function SampleTag({ n, flag }: { n?: number | null; flag?: string | null }) {
  const f = flag || (!isNum(n) || n < 30 ? "insufficient" : n < 200 ? "small" : "ok");
  return (
    <span title={f === "ok" ? "adequate sample" : f === "small" ? "small sample: < 200" : "insufficient sample: < 30 — not evidence"}
      className={clsx("num text-[10px]", f === "ok" ? "text-faint" : f === "small" ? "text-warn" : "text-down")}>
      n={isNum(n) ? n : 0}{f !== "ok" && " ⚠"}
    </span>
  );
}

/** A rate ALWAYS shown with its sample size and 95% Wilson CI. */
export function Rate({ rate, n, lo, hi, flag, digits = 2 }: { rate?: number | null; n?: number | null; lo?: number | null; hi?: number | null; flag?: string | null; digits?: number }) {
  return (
    <span className="inline-flex flex-col items-end leading-tight">
      <span className="num font-semibold">{pct(rate, digits)}</span>
      <span className="num text-[10px] text-faint">
        {isNum(lo) && isNum(hi) ? `[${pct(lo, 1)}–${pct(hi, 1)}] ` : ""}<SampleTag n={n} flag={flag} />
      </span>
    </span>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="rounded-2xl bg-panel2/50 px-4 py-8 text-center text-[13px] text-faint">{children}</div>;
}

export function ErrorNote({ error }: { error?: string | null }) {
  if (!error) return null;
  return <div className="rounded-2xl bg-down/10 px-4 py-3 text-[13px] text-down">Request failed: {error}</div>;
}

export function Drawer({ open, onClose, title, children, wide }: { open: boolean; onClose: () => void; title: ReactNode; children: ReactNode; wide?: boolean }) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-[60] flex items-end justify-center bg-black/60 backdrop-blur-sm animate-fade lg:items-stretch lg:justify-end" onClick={onClose}>
      <div onClick={(e) => e.stopPropagation()}
        className={clsx("max-h-[92vh] w-full overflow-y-auto rounded-t-4xl bg-bg shadow-2xl animate-sheet lg:max-h-none lg:animate-pop lg:rounded-none lg:rounded-l-4xl",
          wide ? "lg:w-[min(1100px,92vw)]" : "lg:w-[min(720px,92vw)]")}>
        <div className="sticky top-0 z-10 flex items-center justify-between bg-bg/95 px-5 py-4 backdrop-blur">
          <div className="mx-auto h-1 w-10 rounded-full bg-line2 lg:hidden" />
          <div className="absolute left-5 top-4 max-w-[75%] truncate text-[17px] font-bold">{title}</div>
          <button onClick={onClose} className="ml-auto rounded-full bg-panel2 p-2 text-dim hover:text-ink"><X size={16} /></button>
        </div>
        <div className="px-5 pb-10 pt-2">{children}</div>
      </div>
    </div>
  );
}

export type Col<T> = {
  key: string; label: ReactNode; render?: (r: T) => ReactNode; align?: "left" | "right" | "center";
  sort?: (r: T) => any; className?: string; title?: string;
};

export function DataTable<T extends Record<string, any>>({ rows, cols, onRow, exportName, dense = true, maxHeight, empty, rowClass }: {
  rows: T[]; cols: Col<T>[]; onRow?: (r: T) => void; exportName?: string; dense?: boolean; maxHeight?: number;
  empty?: ReactNode; rowClass?: (r: T) => string | undefined;
}) {
  const [sortKey, setSortKey] = useState<string | null>(null);
  const [asc, setAsc] = useState(false);
  const sorted = useMemo(() => {
    if (!sortKey) return rows;
    const c = cols.find((x) => x.key === sortKey);
    const get = c?.sort || ((r: T) => r[sortKey]);
    return [...rows].sort((a, b) => {
      const va = get(a), vb = get(b);
      if (va === vb) return 0;
      if (va === null || va === undefined) return 1;
      if (vb === null || vb === undefined) return -1;
      return (va > vb ? 1 : -1) * (asc ? 1 : -1);
    });
  }, [rows, sortKey, asc, cols]);
  return (
    <div>
      {exportName && rows.length > 0 && (
        <div className="mb-1.5 flex justify-end gap-1">
          <Button size="sm" tone="ghost" onClick={() => downloadText(`${exportName}.csv`, toCSV(rows))}><Download size={12} />CSV</Button>
          <Button size="sm" tone="ghost" onClick={() => downloadText(`${exportName}.json`, JSON.stringify(rows, null, 1), "application/json")}><Download size={12} />JSON</Button>
        </div>
      )}
      <div className="overflow-auto rounded-2xl bg-bg/40" style={maxHeight ? { maxHeight } : undefined}>
        <table className="w-full border-collapse text-[12.5px]">
          <thead className="sticky top-0 z-[1] bg-panel">
            <tr>
              {cols.map((c) => (
                <th key={c.key} title={c.title}
                  onClick={() => { if (sortKey === c.key) setAsc(!asc); else { setSortKey(c.key); setAsc(false); } }}
                  className={clsx("cursor-pointer select-none whitespace-nowrap px-3 py-2 text-[11px] font-semibold text-faint hover:text-ink",
                    c.align === "left" || (!c.align && c === cols[0]) ? "text-left" : c.align === "center" ? "text-center" : "text-right")}>
                  <span className="inline-flex items-center gap-0.5">{c.label}
                    {sortKey === c.key && (asc ? <ChevronUp size={11} /> : <ChevronDown size={11} />)}</span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sorted.length === 0 && (
              <tr><td colSpan={cols.length} className="px-3 py-8 text-center text-faint">{empty || "No data yet."}</td></tr>
            )}
            {sorted.map((r, i) => (
              <tr key={i} onClick={onRow ? () => onRow(r) : undefined}
                className={clsx("border-t border-line/60", onRow && "row-hover cursor-pointer", rowClass?.(r))}>
                {cols.map((c) => (
                  <td key={c.key} className={clsx("whitespace-nowrap px-3", dense ? "py-1.5" : "py-2.5",
                    c.align === "left" || (!c.align && c === cols[0]) ? "text-left" : c.align === "center" ? "text-center" : "num text-right",
                    c.className)}>
                    {c.render ? c.render(r) : (r[c.key] ?? "—")}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function KV({ rows }: { rows: [ReactNode, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-[minmax(120px,auto)_1fr] gap-x-4 gap-y-1.5 text-[13px]">
      {rows.map(([k, v], i) => (
        <div key={i} className="contents">
          <dt className="text-dim">{k}</dt>
          <dd className="num min-w-0 break-all text-ink">{v ?? "—"}</dd>
        </div>
      ))}
    </dl>
  );
}

export function SectionNote({ children }: { children: ReactNode }) {
  return <p className="mt-2 text-[11.5px] leading-relaxed text-faint">{children}</p>;
}

/** Cash-App style list row: round icon, title + subtitle, right side value or pill. */
export function ListRow({ icon, title, sub, meta, right, onClick, href }: {
  icon: ReactNode; title: ReactNode; sub?: ReactNode; meta?: ReactNode; right?: ReactNode; onClick?: () => void; href?: string;
}) {
  const inner = (
    <div className="flex items-center gap-4 py-3">
      <div className="shrink-0">{icon}</div>
      <div className="min-w-0 flex-1">
        <div className="truncate text-[16px] font-semibold">{title}</div>
        {sub && <div className="truncate text-[14px] text-dim">{sub}</div>}
        {meta && <div className="truncate text-[13px] text-faint">{meta}</div>}
      </div>
      {right && <div className="shrink-0 text-right">{right}</div>}
    </div>
  );
  if (href) return <a href={href} className="block rounded-2xl px-1 transition active:scale-[.99]">{inner}</a>;
  return <div onClick={onClick} className={clsx("rounded-2xl px-1", onClick && "cursor-pointer transition active:scale-[.99]")}>{inner}</div>;
}

export function Avatar({ label, color, size = 48, ring }: { label: ReactNode; color?: string; size?: number; ring?: boolean }) {
  return (
    <div className={clsx("flex items-center justify-center rounded-full font-bold text-white", ring && "ring-2 ring-accent")}
      style={{ width: size, height: size, background: color || "rgb(var(--panel2))", fontSize: size * 0.38 }}>
      {label}
    </div>
  );
}

export const ASSET_COLORS: Record<string, string> = {
  BTC: "#F7931A", ETH: "#627EEA", SOL: "#9945FF", XRP: "#23292F", DOGE: "#C2A633", HYPE: "#50D2C1", BNB: "#F3BA2F",
};
