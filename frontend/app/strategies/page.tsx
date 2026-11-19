"use client";
import clsx from "clsx";
import { Copy, FlaskConical, Link2, Pencil, Play, Plus, Save, Trash2 } from "lucide-react";
import Link from "next/link";
import { Suspense, useEffect, useState } from "react";
import NameSheet from "@/components/NameSheet";
import { api, post, usePoll } from "@/lib/api";
import { strategySummary as summary } from "@/lib/strategy";

const COINS = ["BTC", "ETH", "SOL", "XRP", "DOGE", "HYPE", "BNB"];
type P = Record<string, any>;

const money = (v: number | null | undefined, sign = true) =>
  v == null ? "—" : `${sign && v > 0 ? "+" : v < 0 ? "−" : ""}$${Math.abs(v).toFixed(2)}`;
const tm = (ms: number) => new Date(ms).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });

function Builder() {
  const { data: list, reload } = usePoll<any[]>("/api/custom-strategies", 0);
  const { data: fields } = usePoll<any>("/api/custom-strategies/fields", 0);
  const [edit, setEdit] = useState<{ id?: number; name: string; params: P } | null>(null);
  const [res, setRes] = useState<any>(null);
  const [testing, setTesting] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [renaming, setRenaming] = useState<any>(null);

  // open a shared link: /strategies?code=RTS1-...
  useEffect(() => {
    const c = new URLSearchParams(window.location.search).get("code");
    if (c) importCode(c);
  }, []);

  const flash = (m: string) => { setMsg(m); setTimeout(() => setMsg(null), 2500); };
  async function importCode(c: string) {
    setErr(null);
    try { const d = await post("/api/custom-strategies/decode", { code: c }); setEdit({ name: d.name, params: d.params }); setRes(null); flash("Strategy loaded — test it, then Save."); }
    catch (e: any) { setErr(e.message); }
  }
  async function test(params: P) {
    setTesting(true); setErr(null); setRes(null);
    try { setRes(await post("/api/custom-strategies/test", { params, start_balance: 100 })); }
    catch (e: any) { setErr(e.message); } finally { setTesting(false); }
  }
  async function save(asNew = false) {
    if (!edit) return;
    try {
      if (edit.id && !asNew) await api(`/api/custom-strategies/${edit.id}`, { method: "PATCH", body: JSON.stringify({ name: edit.name, params: edit.params }) });
      else { const r = await post("/api/custom-strategies", { name: asNew ? `${edit.name} (copy)` : edit.name, params: edit.params }); setEdit({ ...edit, id: r.id, name: r.name }); }
      reload(); flash("Saved");
    } catch (e: any) { setErr(e.message); }
  }
  const copy = (t: string, what: string) => { try { navigator.clipboard.writeText(t); flash(`${what} copied`); } catch { setErr("Couldn't copy — select and copy it manually."); } };
  const link = (c: string) => `${window.location.origin}/strategies/?code=${c}`;

  return (
    <div className="page max-w-[1100px] space-y-3">
      {msg && <div className="fixed left-1/2 top-4 z-[70] -translate-x-1/2 rounded-full bg-ink px-4 py-2 text-[13px] font-bold text-bg">{msg}</div>}
      {err && <div className="rounded-2xl bg-down/10 px-4 py-3 text-[13px] text-down">{err}</div>}

      {!edit && <>
        <div className="flex flex-wrap gap-2">
          <button onClick={() => { setEdit({ name: "My strategy", params: { ...(fields?.defaults || {}) } }); setRes(null); }}
            className="flex items-center gap-2 rounded-full bg-cash px-5 py-3 text-[15px] font-bold text-oncash"><Plus size={17} />New strategy</button>
          <div className="flex min-w-[260px] flex-1 items-center gap-2 rounded-full bg-panel2 px-3">
            <input value={code} onChange={(e) => setCode(e.target.value)} placeholder="Paste a strategy code or link (RTS1-…)"
              className="min-w-0 flex-1 bg-transparent py-3 text-[14px] outline-none" />
            <button onClick={() => code && importCode(code)} className="rounded-full bg-ink px-4 py-1.5 text-[13px] font-bold text-bg">Load</button>
          </div>
        </div>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          {(list || []).map((s) => (
            <div key={s.id} className="panel p-4">
              <div className="flex items-start gap-2">
                <div className="min-w-0 flex-1"><div className="truncate text-[17px] font-bold">{s.name}</div>
                  <div className="mt-1 text-[12.5px] text-dim">{summary(s.params)}</div></div>
                <button title="Rename" onClick={() => setRenaming(s)} className="rounded-full bg-panel2 p-2"><Pencil size={15} /></button>
                <button title="Delete" onClick={() => confirm(`Delete "${s.name}"?`) && api(`/api/custom-strategies/${s.id}`, { method: "DELETE" }).then(reload)}
                  className="rounded-full bg-down/15 p-2 text-down"><Trash2 size={15} /></button>
              </div>
              <div className="mt-3 flex flex-wrap gap-2 text-[13px] font-bold">
                <button onClick={() => { setEdit({ id: s.id, name: s.name, params: s.params }); test(s.params); }} className="flex items-center gap-1.5 rounded-full bg-ink px-4 py-2 text-bg"><FlaskConical size={14} />Test</button>
                <button onClick={() => { setEdit({ id: s.id, name: s.name, params: s.params }); setRes(null); }} className="flex items-center gap-1.5 rounded-full bg-panel2 px-4 py-2"><Pencil size={14} />Edit</button>
                <button onClick={() => copy(s.code, "Code")} className="flex items-center gap-1.5 rounded-full bg-panel2 px-4 py-2"><Copy size={14} />Code</button>
                <button onClick={() => copy(link(s.code), "Link")} className="flex items-center gap-1.5 rounded-full bg-panel2 px-4 py-2"><Link2 size={14} />Link</button>
                <Link href={`/bot/?custom=${s.id}`} className="flex items-center gap-1.5 rounded-full bg-cash/20 px-4 py-2 text-accent"><Play size={14} />Use on a wallet</Link>
              </div>
            </div>
          ))}
        </div>
      </>}

      {edit && fields && <Editor edit={edit} setEdit={setEdit} labels={fields.labels} onTest={() => test(edit.params)} testing={testing}
        onSave={() => save(false)} onSaveNew={() => save(true)} onBack={() => { setEdit(null); setRes(null); }} />}
      {testing && <div className="panel p-6 text-center text-[14px] text-dim">Testing on every recorded market… (a few seconds)</div>}
      {res && <Results r={res} />}
      <NameSheet open={!!renaming} title="Rename strategy" cta="Save name" initial={renaming?.name ?? ""} onClose={() => setRenaming(null)}
        onSave={async (name) => { await api(`/api/custom-strategies/${renaming.id}`, { method: "PATCH", body: JSON.stringify({ name }) }); reload(); }} />
    </div>
  );
}

function Editor({ edit, setEdit, labels, onTest, onSave, onSaveNew, onBack, testing }: any) {
  const p = edit.params as P;
  const set = (k: string, v: any) => setEdit({ ...edit, params: { ...p, [k]: v } });
  const num = (k: string, step = "any", pct = false, hint?: string) => (
    <label className="rounded-2xl bg-panel2/60 px-3 py-2">
      <span className="block text-[11px] font-semibold text-dim">{labels[k]}{pct ? " (¢)" : ""}</span>
      <input inputMode="decimal" step={step} value={pct ? Math.round((p[k] ?? 0) * 1000) / 10 : p[k] ?? 0}
        onChange={(e) => { const v = Number(e.target.value.replace(",", ".")); set(k, Number.isFinite(v) ? (pct ? v / 100 : v) : 0); }}
        className="num w-full bg-transparent text-[17px] font-bold outline-none" />
      {hint && <span className="block text-[10.5px] text-faint">{hint}</span>}
    </label>
  );
  const tog = (k: string, hint?: string) => (
    <button onClick={() => set(k, !p[k])} className={clsx("rounded-2xl px-3 py-2 text-left", p[k] ? "bg-cash/20" : "bg-panel2/60")}>
      <span className="block text-[13px] font-bold">{p[k] ? "✓ " : ""}{labels[k]}</span>{hint && <span className="block text-[10.5px] text-faint">{hint}</span>}
    </button>
  );
  const chips = (k: string, opts: [string, string][]) => (
    <div className="flex flex-wrap gap-2">{opts.map(([v, l]) => {
      const arr: string[] = p[k] || []; const on = arr.includes(v);
      return <button key={v} onClick={() => set(k, on ? arr.filter((x) => x !== v) : [...arr, v])}
        className={clsx("rounded-full px-3.5 py-1.5 text-[13px] font-bold", on ? "bg-ink text-bg" : "bg-panel2 text-dim")}>{l}</button>;
    })}</div>
  );
  return (
    <section className="panel p-5">
      <div className="flex flex-wrap items-center gap-2">
        <button onClick={onBack} className="rounded-full bg-panel2 px-4 py-2 text-[13px] font-bold">← All strategies</button>
        <input value={edit.name} onChange={(e) => setEdit({ ...edit, name: e.target.value })} className="min-w-0 flex-1 rounded-xl bg-panel2 px-3 py-2 text-[17px] font-bold outline-none" />
      </div>
      <p className="mt-2 text-[13px] text-dim">{summary(p)}</p>

      <H t="What to buy" />
      <div className="flex flex-wrap gap-2">
        {[["favourite", "Favourite (likely winner)"], ["underdog", "Underdog (cheap side)"], ["up", "Always UP"], ["down", "Always DOWN"]].map(([v, l]) => (
          <button key={v} onClick={() => set("side", v)} className={clsx("rounded-full px-4 py-2 text-[13px] font-bold", p.side === v ? "bg-ink text-bg" : "bg-panel2 text-dim")}>{l}</button>))}
      </div>
      <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-4">
        {num("min_price", "0.1", true, "e.g. 90 = 90¢ → wins 1.11×")}{num("max_price", "0.1", true, "e.g. 97 = 97¢ → wins 1.03×")}
        {num("entry_max_secs", "1", false, "start buying")}{num("entry_min_secs", "1", false, "stop buying")}
      </div>
      <H t="Markets & coins" />
      {chips("windows", [["5m", "5-minute"], ["15m", "15-minute"]])}
      <div className="mt-2">{chips("assets", COINS.map((c) => [c, c]))}<span className="ml-1 text-[11px] text-faint">(none selected = all coins)</span></div>
      <H t="Filters (when to skip)" />
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {num("z_min", "0.5", false, "how far from flipping, 0 = off. 4 tested best")}{num("z_max", "0.5", false, "0 = off")}
        {num("min_model_edge", "0.01", false, "-1 = off")}{num("model_max", "0.05", false, "1 = off")}
        {tog("momentum_filter", "skip when moving fast toward losing")}{num("momentum_mult", "0.5")}
        {tog("blackout", "US data releases")}{tog("use_fast", "Binance/Coinbase/OKX, ~2s ahead")}
      </div>
      <H t="Money & loss protection" />
      <div className="mb-2 flex gap-2">
        {[["percent", "% of balance"], ["fixed", "Fixed $"]].map(([v, l]) => (
          <button key={v} onClick={() => set("stake_mode", v)} className={clsx("rounded-full px-4 py-2 text-[13px] font-bold", p.stake_mode === v ? "bg-ink text-bg" : "bg-panel2 text-dim")}>{l}</button>))}
      </div>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {num("stake_value", "0.5", false, p.stake_mode === "fixed" ? "$ per trade" : "% of balance per trade")}
        {num("max_loss_pct", "0.5", false, "one loss can never cost more than this % of your balance")}
        {num("min_order_usd", "1")}{num("max_order_usd", "1")}
        {num("max_open_positions", "1")}{num("max_trades_per_day", "1")}
        {num("max_losses_per_day", "1")}{num("daily_loss_limit_pct", "1")}{num("daily_profit_cap_pct", "1")}
      </div>
      <H t="Selling early" />
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {num("take_profit_price", "1", true, "0 = hold to the end")}{num("stop_price", "1", true, "0 = off")}{num("z_stop", "0.5", false, "only sell if really at risk")}
        {num("limit_offset_ticks", "1", false, "pay up to this many cents more to get filled")}
      </div>
      <div className="mt-4 flex flex-wrap gap-2">
        <button onClick={onTest} disabled={testing} className="flex items-center gap-2 rounded-full bg-ink px-5 py-3 text-[15px] font-bold text-bg"><FlaskConical size={16} />{testing ? "Testing…" : "Test with $100 on all recorded data"}</button>
        <button onClick={onSave} className="flex items-center gap-2 rounded-full bg-cash px-5 py-3 text-[15px] font-bold text-oncash"><Save size={16} />{edit.id ? "Save" : "Save strategy"}</button>
        {edit.id && <button onClick={onSaveNew} className="rounded-full bg-panel2 px-5 py-3 text-[15px] font-bold">Save as new</button>}
      </div>
    </section>
  );
}

function H({ t }: { t: string }) { return <div className="mb-2 mt-5 text-[13px] font-bold uppercase tracking-wide text-faint">{t}</div>; }

function Results({ r }: { r: any }) {
  if (r.error) return <div className="panel p-5 text-dim">{r.error}</div>;
  const up = (r.pnl ?? 0) >= 0;
  return (
    <section className="panel p-5">
      <h3 className="text-[18px] font-bold">Test result: $100 → <span className={up ? "text-up" : "text-down"}>${r.end_balance?.toFixed(2)}</span></h3>
      <p className="text-[12px] text-faint">{r.markets_tested} recorded markets · {r.first_ts ? `${tm(r.first_ts)} → ${tm(r.last_ts)}` : ""} · {r.hours}h · past results don't guarantee future results</p>
      {r.trades ? <>
        <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
          <T k="Profit / loss" v={money(r.pnl)} tone={up ? "up" : "down"} sub={`${r.return_pct}% · ~${r.per_day_pct}%/day`} />
          <T k="Trades" v={`${r.trades}`} sub={`${r.wins} won · ${r.losses} lost (${(r.win_rate * 100).toFixed(1)}%)`} />
          <T k="Average win / loss" v={`${money(r.avg_win)} / ${money(r.avg_loss)}`} sub={`wins pay ~${r.avg_return_per_win_x}× · avg price ${(r.avg_price * 100).toFixed(1)}¢`} />
          <T k="Biggest loss" v={r.losses ? money(r.biggest_loss) : "none"} tone={r.losses ? "down" : undefined} sub={`worst dip ${money(r.max_drawdown)} · losing streak ${r.longest_losing_streak}`} />
          <T k="Fees paid" v={money(r.fees, false)} />
          <T k="Skipped (no sellers at our price)" v={`${r.skipped?.["no depth at our price"] ?? 0}`} />
          <T k="Skipped (daily limits / max open)" v={`${r.skipped?.guard ?? 0}`} />
          <T k="Skipped (stake too small)" v={`${r.skipped?.["stake too small"] ?? 0}`} />
        </div>
        <Curve pts={r.curve} />
        <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-2">
          <Mini title="By result" rows={r.by_result} k="result" />
          <Mini title="By coin" rows={r.by_coin} k="coin" />
        </div>
        <div className="mt-4 text-[14px] font-bold">Where the money went (every trade, newest first)</div>
        <div className="mt-2 max-h-[520px] overflow-auto">
          <table className="w-full min-w-[760px] text-[12.5px]">
            <thead className="sticky top-0 bg-panel text-left text-[10.5px] uppercase tracking-wide text-faint"><tr>
              {["Time", "Coin", "Side", "Left", "Price", "Shares", "Paid (incl. fee)", "Fee", "Result", "Got back", "P&L", "Balance after"].map((h) => <th key={h} className="py-2 pr-2">{h}</th>)}</tr></thead>
            <tbody>{r.trade_list.map((t: any, i: number) => (
              <tr key={i} className="border-t border-line/60">
                <td className="py-1.5 pr-2">{tm(t.time)}</td><td>{t.coin}{t.window !== "5m" ? ` (${t.window})` : ""}</td><td>{t.side}</td><td>{t.secs_left}s</td>
                <td className="num">{(t.price * 100).toFixed(1)}¢</td><td className="num">{t.shares}</td><td className="num">${t.cost.toFixed(2)}</td><td className="num">${t.fee.toFixed(3)}</td>
                <td className={t.pnl >= 0 ? "text-up" : "text-down"}>{t.result}</td><td className="num">${t.payout.toFixed(2)}</td>
                <td className={clsx("num font-bold", t.pnl >= 0 ? "text-up" : "text-down")}>{money(t.pnl)}</td><td className="num">{t.balance_after != null ? `$${t.balance_after.toFixed(2)}` : "…"}</td>
              </tr>))}</tbody>
          </table>
        </div>
      </> : <p className="mt-3 text-[14px] text-dim">No trades with these settings. Most common reasons it skipped: {Object.entries(r.filter_reasons || {}).map(([k, v]) => `${k} (${v})`).join(", ") || "—"}</p>}
    </section>
  );
}

function T({ k, v, sub, tone }: { k: string; v: string; sub?: string; tone?: "up" | "down" }) {
  return <div className="rounded-2xl bg-panel2/60 px-3 py-2.5"><div className="text-[11px] text-dim">{k}</div>
    <div className={clsx("num text-[17px] font-bold", tone === "up" && "text-up", tone === "down" && "text-down")}>{v}</div>{sub && <div className="text-[11px] text-faint">{sub}</div>}</div>;
}

function Mini({ title, rows, k }: { title: string; rows: any[]; k: string }) {
  return <div className="rounded-2xl bg-panel2/40 p-3"><div className="text-[13px] font-bold">{title}</div>
    {(rows || []).map((x) => <div key={x[k]} className="mt-1 flex justify-between text-[12.5px]"><span className="text-dim">{x[k]} · {x.trades}</span>
      <span className={clsx("num font-bold", x.pnl >= 0 ? "text-up" : "text-down")}>{money(x.pnl)}</span></div>)}</div>;
}

function Curve({ pts }: { pts: { ts: number; balance: number }[] }) {
  if (!pts || pts.length < 2) return null;
  const W = 600, H = 140, vals = pts.map((p) => p.balance);
  const lo = Math.min(...vals, 100), hi = Math.max(...vals, 100), span = hi - lo || 1;
  const t0 = pts[0].ts, t1 = pts[pts.length - 1].ts, ts = t1 - t0 || 1;
  const d = pts.map((p, i) => `${i ? "L" : "M"}${(((p.ts - t0) / ts) * W).toFixed(1)},${(H - ((p.balance - lo) / span) * H).toFixed(1)}`).join(" ");
  const up = vals[vals.length - 1] >= 100;
  return (
    <div className="mt-4"><div className="text-[13px] font-bold">Balance over time</div>
      <svg viewBox={`0 0 ${W} ${H}`} className="mt-1 h-36 w-full" preserveAspectRatio="none">
        <line x1="0" x2={W} y1={H - ((100 - lo) / span) * H} y2={H - ((100 - lo) / span) * H} stroke="currentColor" className="text-line" strokeDasharray="4 4" />
        <path d={d} fill="none" strokeWidth="2.5" stroke="currentColor" className={up ? "text-up" : "text-down"} vectorEffect="non-scaling-stroke" />
      </svg>
      <div className="flex justify-between text-[10px] text-faint"><span>{tm(t0)}</span><span>${lo.toFixed(0)}–${hi.toFixed(0)}</span><span>{tm(t1)}</span></div>
    </div>
  );
}

export default function StrategiesPage() { return <Suspense><Builder /></Suspense>; }
