"use client";
import { Download } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { createChart, ColorType, IChartApi, ISeriesApi, LineStyle, UTCTimestamp } from "lightweight-charts";

export type SeriesDef = {
  name: string;
  color: string;
  data: { time: number; value: number | null | undefined }[]; // time in ms
  priceScale?: "left" | "right";
  type?: "line" | "area" | "histogram";
  dashed?: boolean;
  width?: number;
};

export type Marker = { time: number; label: string; color: string; position?: "aboveBar" | "belowBar"; shape?: "arrowUp" | "arrowDown" | "circle" | "square" };

export function TimeChart({ series, height = 260, markers, title, ranges, cursorTime, leftLabel, rightLabel, fit = true }: {
  series: SeriesDef[]; height?: number; markers?: Marker[]; title?: string; ranges?: boolean; cursorTime?: number | null;
  leftLabel?: string; rightLabel?: string; fit?: boolean;
}) {
  const el = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  const refs = useRef<Record<string, ISeriesApi<any>>>({});
  const [range, setRange] = useState<number | null>(null);
  const [hover, setHover] = useState<Record<string, number> | null>(null);

  useEffect(() => {
    if (!el.current) return;
    const c = createChart(el.current, {
      height,
      layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: "#8a929d", fontSize: 10, fontFamily: "var(--font-mono)" },
      grid: { vertLines: { color: "#1a1d22" }, horzLines: { color: "#1a1d22" } },
      rightPriceScale: { borderColor: "#22252b", visible: true },
      leftPriceScale: { borderColor: "#22252b", visible: series.some((s) => s.priceScale === "left") },
      timeScale: { borderColor: "#22252b", timeVisible: true, secondsVisible: true },
      crosshair: { mode: 0 },
      localization: { timeFormatter: (t: number) => new Date(t * 1000).toLocaleTimeString(undefined, { hour12: false }) },
      autoSize: true,
    });
    chart.current = c;
    c.subscribeCrosshairMove((p) => {
      if (!p.time) return setHover(null);
      const h: Record<string, number> = {};
      Object.entries(refs.current).forEach(([name, s]) => {
        const d: any = p.seriesData.get(s);
        if (d && typeof d.value === "number") h[name] = d.value;
      });
      setHover(h);
    });
    return () => { c.remove(); chart.current = null; refs.current = {}; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [height]);

  useEffect(() => {
    const c = chart.current;
    if (!c) return;
    const names = new Set(series.map((s) => s.name));
    Object.keys(refs.current).forEach((n) => { if (!names.has(n)) { c.removeSeries(refs.current[n]); delete refs.current[n]; } });
    series.forEach((s) => {
      let r = refs.current[s.name];
      if (!r) {
        const opts: any = { color: s.color, lineWidth: s.width ?? 2, priceScaleId: s.priceScale || "right", title: "",
          lineStyle: s.dashed ? LineStyle.Dashed : LineStyle.Solid, priceLineVisible: false, lastValueVisible: true };
        r = s.type === "area" ? c.addAreaSeries({ ...opts, lineColor: s.color, topColor: s.color + "33", bottomColor: s.color + "00" })
          : s.type === "histogram" ? c.addHistogramSeries({ color: s.color, priceScaleId: s.priceScale || "right" })
          : c.addLineSeries(opts);
        refs.current[s.name] = r;
      }
      const seen = new Set<number>();
      const pts = s.data
        .filter((d) => typeof d.value === "number" && isFinite(d.value as number))
        .map((d) => ({ time: Math.floor(d.time / 1000) as UTCTimestamp, value: d.value as number }))
        .filter((d) => (seen.has(d.time) ? false : (seen.add(d.time), true)))
        .sort((a, b) => a.time - b.time);
      r.setData(pts);
    });
    const first = series[0] && refs.current[series[0].name];
    if (first && markers) {
      first.setMarkers(markers.map((m) => ({ time: Math.floor(m.time / 1000) as UTCTimestamp, position: m.position || "aboveBar",
        color: m.color, shape: m.shape || "arrowDown", text: m.label })).sort((a, b) => (a.time as number) - (b.time as number)));
    }
    if (range) {
      const all = series.flatMap((s) => s.data.map((d) => d.time));
      const max = Math.max(...all);
      if (isFinite(max)) c.timeScale().setVisibleRange({ from: Math.floor((max - range) / 1000) as UTCTimestamp, to: Math.floor(max / 1000) as UTCTimestamp });
    } else if (fit) c.timeScale().fitContent();
  }, [series, markers, range, fit]);

  useEffect(() => {
    const c = chart.current;
    if (!c || !cursorTime) return;
    const first = series[0] && refs.current[series[0].name];
    if (first) {
      c.setCrosshairPosition(NaN as any, Math.floor(cursorTime / 1000) as UTCTimestamp, first);
    }
  }, [cursorTime, series]);

  const exportPng = () => {
    const cv = chart.current?.takeScreenshot();
    if (!cv) return;
    const a = document.createElement("a");
    a.href = cv.toDataURL("image/png");
    a.download = `${(title || "chart").replace(/\s+/g, "_")}.png`;
    a.click();
  };

  return (
    <div>
      <div className="mb-1 flex flex-wrap items-center justify-between gap-2 text-2xs">
        <div className="flex flex-wrap items-center gap-3">
          {series.map((s) => (
            <span key={s.name} className="mono inline-flex items-center gap-1 text-dim">
              <span className="inline-block h-0.5 w-3" style={{ background: s.color }} />{s.name}
              {hover && hover[s.name] !== undefined && <span className="text-ink">{hover[s.name].toFixed(hover[s.name] > 100 ? 2 : 4)}</span>}
            </span>
          ))}
          {leftLabel && <span className="text-faint">L: {leftLabel}</span>}
          {rightLabel && <span className="text-faint">R: {rightLabel}</span>}
        </div>
        <div className="flex items-center gap-1">
          {ranges && [["1m", 60e3], ["5m", 300e3], ["15m", 900e3], ["1h", 3600e3], ["All", 0]].map(([l, v]) => (
            <button key={l as string} onClick={() => setRange((v as number) || null)}
              className={`rounded px-1.5 py-0.5 ${range === v || (!range && v === 0) ? "bg-panel2 text-ink" : "text-faint hover:text-ink"}`}>{l}</button>
          ))}
          <button title="Export PNG" onClick={exportPng} className="ml-1 text-faint hover:text-ink"><Download size={12} /></button>
        </div>
      </div>
      <div ref={el} style={{ height }} className="w-full" />
    </div>
  );
}

/** Simple SVG bar chart for categorical stats (rates with CI whiskers). */
export function RateBars({ rows, label, height = 180 }: { rows: { x: string; rate: number | null; lo?: number | null; hi?: number | null; n?: number }[]; label?: string; height?: number }) {
  const max = Math.max(0.01, ...rows.map((r) => r.hi ?? r.rate ?? 0));
  const w = Math.max(320, rows.length * 44);
  const H = height, pad = 24;
  return (
    <div className="overflow-x-auto">
      <svg width={w} height={H + 30} className="text-2xs">
        {rows.map((r, i) => {
          const x = 30 + i * 44;
          const y = (v: number) => pad + (H - pad) * (1 - v / max);
          const val = r.rate ?? 0;
          return (
            <g key={r.x}>
              <title>{`${r.x}: ${(val * 100).toFixed(2)}% n=${r.n ?? 0}`}</title>
              <rect x={x} y={y(val)} width={26} height={Math.max(0, H - y(val))} fill={(r.n ?? 0) < 30 ? "#5c636d" : "#a3e635"} opacity={0.75} />
              {r.lo != null && r.hi != null && <line x1={x + 13} x2={x + 13} y1={y(r.hi)} y2={y(r.lo)} stroke="#d8dce2" strokeWidth={1} />}
              <text x={x + 13} y={H + 12} textAnchor="middle" fill="#8a929d">{r.x}</text>
              <text x={x + 13} y={H + 24} textAnchor="middle" fill="#5c636d">n={r.n ?? 0}</text>
              <text x={x + 13} y={y(val) - 3} textAnchor="middle" fill="#d8dce2">{(val * 100).toFixed(1)}</text>
            </g>
          );
        })}
        {label && <text x={4} y={12} fill="#8a929d">{label}</text>}
      </svg>
    </div>
  );
}
