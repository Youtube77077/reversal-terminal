"use client";
import { usePoll } from "./api";

const TS = [120, 90, 60, 45, 30, 20, 15, 10, 7, 5, 3, 2, 1];

function inBucket(label: string, p: number) {
  const m = label.replace(/%/g, "").split("-").map(Number);
  if (m.length !== 2 || m.some((x) => !isFinite(x))) return false;
  const v = p * 100;
  return v >= m[0] && (m[1] >= 100 ? v <= 100 : v < m[1]);
}

export type RealOdds = { rate: number; n: number; t: number; lo: number; hi: number } | null;

/**
 * History of every recorded market: "when the favourite was X% with Y seconds left,
 * how often did it actually lose (= underdog won)?". Refreshes every minute.
 */
export function useRealOdds() {
  const { data } = usePoll<any>("/api/scanner/matrix?row=prob_bucket", 60000);
  const lookup = (favProb: number | null | undefined, secs: number | null | undefined): RealOdds => {
    if (!data?.cells || favProb == null || secs == null || !isFinite(favProb) || !isFinite(secs)) return null;
    const row = (data.rows as string[]).find((r) => inBucket(r, favProb));
    if (!row) return null;
    // nearest recorded checkpoint to the time left
    const t = TS.reduce((a, b) => (Math.abs(b - secs) < Math.abs(a - secs) ? b : a), TS[0]);
    const c = data.cells.find((x: any) => x.row === row && x.t_minus === t);
    if (!c || !c.n) return null;
    return { rate: c.rate, n: c.n, t, lo: c.ci_low ?? 0, hi: c.ci_high ?? 1 };
  };
  return lookup;
}

/** Plain-English verdict comparing Polymarket's price with what really happens. */
export function verdict(polyChance: number | null | undefined, real: RealOdds) {
  if (polyChance == null || !real) return { text: "Not enough history yet", tone: "dim" as const };
  if (real.n < 10) return { text: `Only ${real.n} similar markets seen — too few to trust`, tone: "dim" as const };
  if (polyChance >= 0.4) return { text: "Close race — either side can still win", tone: "dim" as const };
  if (polyChance >= real.lo && polyChance <= real.hi) return { text: "About fair — the difference could just be luck", tone: "dim" as const };
  return real.rate < polyChance
    ? { text: "Underdog is overpriced — the favourite usually wins", tone: "up" as const }
    : { text: "Underdog is underpriced — flips happen more than the price says", tone: "warn" as const };
}
