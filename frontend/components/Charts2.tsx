"use client";
import clsx from "clsx";
import { useEffect, useRef, useState } from "react";

const fmtUsd = (v: number) => `${v < 0 ? "-" : ""}$${Math.abs(v).toFixed(Math.abs(v) >= 100 ? 0 : 2)}`;

/** Animated number that eases from its previous value. */
export function AnimatedNumber({ value, format = (v: number) => v.toFixed(2), duration = 700, className }: {
  value: number | null | undefined; format?: (v: number) => string; duration?: number; className?: string;
}) {
  const [shown, setShown] = useState<number>(value ?? 0);
  const from = useRef<number>(value ?? 0);
  useEffect(() => {
    if (value === null || value === undefined || !isFinite(value)) return;
    const start = performance.now();
    const a = from.current, b = value;
    let raf = 0;
    const step = (t: number) => {
      const k = Math.min(1, (t - start) / duration);
      const e = 1 - Math.pow(1 - k, 3);
      setShown(a + (b - a) * e);
      if (k < 1) raf = requestAnimationFrame(step); else from.current = b;
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [value, duration]);
  if (value === null || value === undefined || !isFinite(value)) return <span className={className}>—</span>;
  return <span className={clsx("num", className)}>{format(shown)}</span>;
}

/** Vertical bar chart; negative values render red below the zero line. */
export function BarChart({ data, height = 190, money = true, label, valueKey = "v", xKey = "x", sub }: {
  data: Record<string, any>[]; height?: number; money?: boolean; label?: string; valueKey?: string; xKey?: string;
  sub?: (d: any) => string;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const [mounted, setMounted] = useState(false);
  useEffect(() => { const t = setTimeout(() => setMounted(true), 30); return () => clearTimeout(t); }, []);
  if (!data.length) return <div className="flex items-center justify-center rounded-2xl bg-panel2/40 text-[13px] text-faint" style={{ height }}>No data yet</div>;
  const vals = data.map((d) => Number(d[valueKey]) || 0);
  const max = Math.max(0, ...vals), min = Math.min(0, ...vals);
  const span = max - min || 1;
  const zeroY = (max / span) * (height - 28);
  const w = 100 / data.length;
  const h = hover !== null ? data[hover] : null;
  return (
    <div className="relative select-none">
      {label && <div className="mb-1 text-[12px] font-semibold text-dim">{label}</div>}
      <div className="relative" style={{ height }}>
        <div className="absolute inset-x-0 border-t border-dashed border-line2" style={{ top: zeroY }} />
        <div className="absolute inset-0 flex items-start" style={{ height: height - 28 }}>
          {data.map((d, i) => {
            const v = vals[i];
            const bh = (Math.abs(v) / span) * (height - 28);
            return (
              <div key={i} className="relative h-full" style={{ width: `${w}%` }}
                onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)} onTouchStart={() => setHover(i)}>
                <div className={clsx("absolute left-[18%] right-[18%] rounded-md transition-all duration-700 ease-out",
                  v >= 0 ? "bg-up" : "bg-down", hover === i ? "opacity-100" : "opacity-80")}
                  style={{ top: v >= 0 ? zeroY - (mounted ? bh : 0) : zeroY, height: mounted ? Math.max(bh, v !== 0 ? 2 : 0) : 0 }} />
              </div>
            );
          })}
        </div>
        <div className="absolute inset-x-0 bottom-0 flex">
          {data.map((d, i) => (
            <div key={i} className="truncate px-0.5 text-center text-[10px] text-faint" style={{ width: `${w}%` }}>{String(d[xKey])}</div>
          ))}
        </div>
        {h && (
          <div className="pointer-events-none absolute right-0 top-0 rounded-xl bg-bg/90 px-3 py-1.5 text-[12px] shadow-lg ring-1 ring-line animate-fade">
            <div className="font-semibold">{String(h[xKey])}</div>
            <div className={clsx("num font-semibold", Number(h[valueKey]) >= 0 ? "text-up" : "text-down")}>
              {money ? fmtUsd(Number(h[valueKey])) : `${(Number(h[valueKey]) * 100).toFixed(1)}%`}</div>
            {sub && <div className="text-faint">{sub(h)}</div>}
          </div>
        )}
      </div>
    </div>
  );
}

const PALETTE = ["#00d64b", "#409cff", "#ff9f0a", "#bf5af2", "#ff453a", "#64d2ff", "#ffd60a", "#30d158", "#ff375f", "#ac8e68", "#5e5ce6", "#66d4cf", "#e0e0e0"];
export const seriesColor = (i: number) => PALETTE[i % PALETTE.length];

/** Multi-series line chart over a categorical x axis (e.g. T-120 … T-1). */
export function XYLines({ xs, series, height = 220, pct = true, xLabel = (x: any) => String(x) }: {
  xs: (string | number)[]; series: { name: string; values: (number | null)[]; color?: string; n?: number[] }[];
  height?: number; pct?: boolean; xLabel?: (x: any) => string;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const vis = series.filter((s) => !hidden.has(s.name));
  const all = vis.flatMap((s) => s.values.filter((v): v is number => v !== null && isFinite(v)));
  const max = Math.max(0.01, ...all), min = Math.min(0, ...all);
  const W = 1000, H = height, padL = 46, padB = 24, padT = 10;
  const x = (i: number) => padL + (i / Math.max(1, xs.length - 1)) * (W - padL - 10);
  const y = (v: number) => padT + (1 - (v - min) / (max - min || 1)) * (H - padT - padB);
  const fmt = (v: number) => (pct ? `${(v * 100).toFixed(1)}%` : v.toFixed(2));
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((k) => min + (max - min) * k);
  return (
    <div>
      <div className="mb-2 flex flex-wrap gap-1.5">
        {series.map((s, i) => (
          <button key={s.name} onClick={() => setHidden((h) => { const n = new Set(h); n.has(s.name) ? n.delete(s.name) : n.add(s.name); return n; })}
            className={clsx("flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-semibold transition", hidden.has(s.name) ? "bg-panel2/40 text-faint" : "bg-panel2 text-ink")}>
            <span className="h-2 w-2 rounded-full" style={{ background: s.color || seriesColor(i) }} />{s.name}
          </button>
        ))}
      </div>
      <div className="relative">
        <svg viewBox={`0 0 ${W} ${H}`} className="w-full" style={{ height }} preserveAspectRatio="none"
          onMouseLeave={() => setHover(null)}
          onMouseMove={(e) => {
            const r = (e.currentTarget as SVGElement).getBoundingClientRect();
            const px = ((e.clientX - r.left) / r.width) * W;
            const i = Math.round(((px - padL) / (W - padL - 10)) * (xs.length - 1));
            setHover(Math.max(0, Math.min(xs.length - 1, i)));
          }}>
          {ticks.map((t, i) => (
            <g key={i}>
              <line x1={padL} x2={W - 10} y1={y(t)} y2={y(t)} stroke="rgb(var(--line))" strokeDasharray="4 6" />
              <text x={padL - 6} y={y(t) + 4} textAnchor="end" fontSize="20" fill="rgb(var(--faint))">{fmt(t)}</text>
            </g>
          ))}
          {xs.map((xx, i) => (
            <text key={i} x={x(i)} y={H - 4} textAnchor="middle" fontSize="20" fill="rgb(var(--faint))">{xLabel(xx)}</text>
          ))}
          {series.map((s, si) => hidden.has(s.name) ? null : (
            <polyline key={s.name} fill="none" stroke={s.color || seriesColor(si)} strokeWidth={3} strokeLinejoin="round" strokeLinecap="round"
              vectorEffect="non-scaling-stroke"
              points={s.values.map((v, i) => (v === null || !isFinite(v) ? null : `${x(i)},${y(v)}`)).filter(Boolean).join(" ")} />
          ))}
          {hover !== null && <line x1={x(hover)} x2={x(hover)} y1={padT} y2={H - padB} stroke="rgb(var(--dim))" strokeWidth={1} vectorEffect="non-scaling-stroke" />}
        </svg>
        {hover !== null && (
          <div className="pointer-events-none absolute right-2 top-2 max-w-[60%] rounded-xl bg-bg/95 px-3 py-2 text-[11.5px] shadow-xl ring-1 ring-line animate-fade">
            <div className="mb-1 font-semibold">{xLabel(xs[hover])}</div>
            {vis.map((s) => (
              <div key={s.name} className="flex justify-between gap-3"><span className="text-dim">{s.name}</span>
                <span className="num font-semibold">{s.values[hover] === null ? "—" : fmt(s.values[hover] as number)}{s.n ? <span className="text-faint"> n={s.n[hover]}</span> : null}</span></div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

/** Tiny inline trend line. */
export function Sparkline({ values, height = 36, className }: { values: number[]; height?: number; className?: string }) {
  if (values.length < 2) return <div style={{ height }} />;
  const max = Math.max(...values), min = Math.min(...values);
  const pts = values.map((v, i) => `${(i / (values.length - 1)) * 100},${100 - ((v - min) / (max - min || 1)) * 100}`).join(" ");
  const up = values[values.length - 1] >= values[0];
  return (
    <svg viewBox="0 0 100 100" preserveAspectRatio="none" className={className} style={{ height, width: "100%" }}>
      <polyline points={pts} fill="none" stroke={up ? "rgb(var(--up))" : "rgb(var(--down))"} strokeWidth={3} vectorEffect="non-scaling-stroke" />
    </svg>
  );
}
