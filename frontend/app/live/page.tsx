"use client";
import clsx from "clsx";
import { AlertTriangle, Check, KeyRound, X } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { Button, ErrorNote, Field, inputCls, Panel, Select } from "@/components/ui";
import { api, post, usePoll } from "@/lib/api";
import { signedUsd, usd } from "@/lib/format";

function Check2({ ok, label, detail }: { ok: boolean; label: string; detail?: string }) {
  return (
    <div className="flex items-start gap-3 py-2.5">
      <span className={clsx("mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full", ok ? "bg-up text-black" : "bg-down/20 text-down")}>
        {ok ? <Check size={14} strokeWidth={3} /> : <X size={14} strokeWidth={3} />}</span>
      <div className="min-w-0"><div className="text-[15px] font-semibold">{label}</div>{detail && <div className="break-words text-[13px] text-dim">{detail}</div>}</div>
    </div>
  );
}

export default function LivePage() {
  const { data: st, error, reload } = usePoll<any>("/api/live/status", 10000);
  const { data: strategies } = usePoll<any[]>("/api/strategies", 0);
  const [pw, setPw] = useState("");
  const [ack, setAck] = useState(false);
  const [strat, setStrat] = useState("B");
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const ex = st?.executor || {};
  const geo = st?.geoblock || {};
  const acct = st?.accounts?.[0];
  const run = async (fn: () => Promise<any>, ok: string) => {
    setErr(null); setMsg(null);
    try { await fn(); setMsg(ok); reload(); } catch (e: any) { setErr(e.message); }
  };
  return (
    <div className="page max-w-[1000px] space-y-4">
      <ErrorNote error={error} />
      <div className={clsx("rounded-4xl px-6 py-7", st?.armed ? "bg-down text-white" : "bg-panel")}>
        <div className="text-[15px] font-semibold opacity-80">Live trading</div>
        <div className="money mt-1 text-[44px]">{st?.armed ? "Armed" : st?.eligible ? "Ready" : "Unavailable"}</div>
        <div className="mt-1 text-[14px] opacity-80">{st?.armed ? "Real orders will be placed by bots with a running live session." : "Paper trading keeps working regardless."}</div>
      </div>

      {(st?.warnings || []).map((w: string, i: number) => (
        <div key={i} className="flex gap-3 rounded-3xl bg-warn/10 px-5 py-4 text-[13.5px] text-warn"><AlertTriangle size={18} className="mt-0.5 shrink-0" />{w}</div>
      ))}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Panel title="Checklist">
          <Check2 ok={!st?.reasons?.some((r: string) => r.startsWith("LIVE_TRADING_ENABLED"))} label="LIVE_TRADING_ENABLED=true on the server" />
          <Check2 ok={!!ex.ok} label="Executor connected with your Polymarket keys" detail={ex.ok ? `deposit wallet ${ex.wallet}` : ex.error} />
          <Check2 ok={!!geo.reachable && !st?.reasons?.some((r: string) => r.startsWith("Server location"))} label="Server location accepted by Polymarket API"
            detail={geo.country ? `${geo.country}${geo.region ? "-" + geo.region : ""} · geoblock blocked=${String(geo.blocked)} (frontend-only restriction for NL)` : geo.error} />
          <Check2 ok={!!acct} label="Live account created" detail={acct ? `${acct.name} · strategy ${acct.strategy_key}` : "create one below"} />
          <Check2 ok={!!acct?.session?.active} label="Bot session with risk budget & stop loss" detail={acct?.session?.active ? `budget ${usd(acct.session.risk_budget)} · SL ${acct.session.stop_loss_pct}%` : "set on the $ tab"} />
          <div className="mt-2 text-[12px] text-faint">Hard caps: {usd(st?.limits?.max_order_usd)} per order · {usd(st?.limits?.max_session_budget_usd)} per session budget (server env).</div>
        </Panel>

        <Panel title={acct ? acct.name : "Live account"}>
          {acct ? (
            <div className="space-y-3">
              <div className="money text-[40px]">{usd(acct.summary.equity)}</div>
              <div className="text-[13px] text-dim">Synced from your wallet when a session starts · realised {signedUsd(acct.summary.realized_pnl)}</div>
              <Link href={`/bot/?acct=${acct.id}`} className="pill w-full py-3.5">Open on $ tab</Link>
            </div>
          ) : (
            <div className="space-y-3">
              <Field label="Strategy"><Select value={strat} onChange={setStrat} className="w-full" options={(strategies || []).map((s) => ({ value: s.key, label: `${s.key} · ${s.name}` }))} /></Field>
              <Button tone="primary" size="lg" className="w-full" onClick={() => run(() => post("/api/live/account", { strategy_key: strat }), "Live account created")}>Create live account</Button>
            </div>
          )}
        </Panel>
      </div>

      <Panel title={st?.armed ? "Disarm" : "Arm live trading"} sub="Requires your app password. Arming persists across server restarts until you disarm.">
        {st?.armed ? (
          <Button tone="solid" size="lg" className="w-full" onClick={() => run(() => post("/api/live/disarm"), "Disarmed")}>Disarm live trading</Button>
        ) : (
          <div className="space-y-3">
            <Field label="App password"><input type="password" className={inputCls + " py-3"} value={pw} onChange={(e) => setPw(e.target.value)} autoComplete="current-password" /></Field>
            <label className="flex items-start gap-2 text-[13.5px] text-dim">
              <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} className="mt-1" />
              I understand this places REAL orders with my Polymarket wallet, losses are real, and Polymarket's Terms of Use list the Netherlands as restricted.
            </label>
            <Button tone="danger" size="lg" className="w-full" disabled={!ack || !st?.eligible}
              onClick={() => run(() => post("/api/live/arm", { password: pw, confirm: true }), "Live trading armed")}>Arm live trading</Button>
            {!st?.eligible && <div className="text-[13px] text-down">{(st?.reasons || []).join(" · ")}</div>}
          </div>
        )}
        <ErrorNote error={err} />
        {msg && <div className="mt-2 text-[13px] text-up">{msg}</div>}
        <Button size="sm" tone="ghost" className="mt-2" onClick={async () => { await api("/api/live-mode?force=true"); reload(); }}>Re-check</Button>
      </Panel>

      <Panel title="Where to put your API keys" right={<KeyRound size={18} className="text-dim" />}>
        <div className="space-y-3 text-[13.5px] leading-relaxed text-dim">
          <p>Keys go <b className="text-ink">only in the server environment</b>: never in this website, the iPhone app, chat or Git. The executor is the only process that reads them.</p>
          <pre className="mono overflow-x-auto rounded-2xl bg-bg/60 p-4 text-[12px] text-ink">{`LIVE_TRADING_ENABLED=true
POLYMARKET_PRIVATE_KEY=0x...        # wallet key that owns your Polymarket deposit wallet
POLYMARKET_BUILDER_KEY=...          # Polymarket → Settings → Builder API keys
POLYMARKET_BUILDER_SECRET=...
POLYMARKET_BUILDER_PASSPHRASE=...
EXECUTOR_TOKEN=<random string>      # shared secret between backend and executor
LIVE_MAX_ORDER_USD=5
LIVE_MAX_SESSION_BUDGET_USD=100`}</pre>
          <p><b className="text-ink">On your PC:</b> put them in the <span className="mono">.env</span> file in the project folder.
            <b className="text-ink"> On the cloud server:</b> add them as environment variables/secrets in your host's dashboard (see DEPLOY.md). <b className="text-ink">GitHub:</b> repository → Settings → Secrets and variables → Actions (used only by the deploy workflow).</p>
        </div>
      </Panel>
    </div>
  );
}
