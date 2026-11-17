export const isNum = (v: any): v is number => typeof v === "number" && isFinite(v);

export function num(v: any, d = 2): string {
  return isNum(v) ? v.toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d }) : "—";
}
export function usd(v: any, d = 2): string {
  if (!isNum(v)) return "—";
  const s = Math.abs(v).toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });
  return `${v < 0 ? "-" : ""}$${s}`;
}
export function signedUsd(v: any, d = 2): string {
  if (!isNum(v)) return "—";
  return `${v > 0 ? "+" : ""}${usd(v, d)}`;
}
export function pct(v: any, d = 2): string {
  return isNum(v) ? `${(v * 100).toFixed(d)}%` : "—";
}
export function price(v: any): string {
  if (!isNum(v)) return "—";
  return v < 0.1 ? v.toFixed(3) : v.toFixed(2);
}
export function spot(v: any): string {
  if (!isNum(v)) return "—";
  if (v >= 1000) return v.toLocaleString(undefined, { maximumFractionDigits: 2, minimumFractionDigits: 2 });
  if (v >= 1) return v.toFixed(4);
  return v.toFixed(6);
}
export function int(v: any): string {
  return isNum(v) ? Math.round(v).toLocaleString() : "—";
}
/** Display timestamps in the user's local timezone (stored as UTC ms). */
export function ts(ms: any, withDate = true): string {
  if (!isNum(ms)) return "—";
  const d = new Date(ms);
  return withDate
    ? d.toLocaleString(undefined, { month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false })
    : d.toLocaleTimeString(undefined, { hour12: false });
}
export function dur(secs: any): string {
  if (!isNum(secs)) return "—";
  const s = Math.max(0, Math.floor(secs));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60;
  if (h) return `${h}h ${String(m).padStart(2, "0")}m`;
  if (m) return `${m}m ${String(r).padStart(2, "0")}s`;
  return `${r}s`;
}
export function ago(ms: any): string {
  if (!isNum(ms)) return "never";
  const s = (Date.now() - ms) / 1000;
  if (s < 2) return "now";
  if (s < 60) return `${Math.floor(s)}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  return `${Math.floor(s / 3600)}h ago`;
}
export const pnlClass = (v: any) => (!isNum(v) || v === 0 ? "text-ink" : v > 0 ? "text-up" : "text-down");

export const statusColor = (s: string) =>
  s === "won" ? "text-up" : s === "lost" ? "text-down" : s === "filled" || s === "partially_filled" ? "text-info" : s === "pending" ? "text-ink" : "text-warn";
