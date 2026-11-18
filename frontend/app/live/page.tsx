"use client";
import clsx from "clsx";
import { AlertTriangle, Check, ChevronDown, ExternalLink, KeyRound, ShieldCheck, X } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { Button, ErrorNote, Field, inputCls, Panel, Select } from "@/components/ui";
import { post, put, usePoll } from "@/lib/api";
import WalletBar from "@/components/WalletBar";
import { useWallet } from "@/lib/wallet";
import { signedUsd, usd } from "@/lib/format";

function Row({ ok, label, detail }: { ok: boolean; label: string; detail?: string }) {
  return (
    <div className="flex items-start gap-3 py-2.5">
      <span className={clsx("mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full transition", ok ? "bg-up text-black" : "bg-down/20 text-down")}>
        {ok ? <Check size={14} strokeWidth={3} /> : <X size={14} strokeWidth={3} />}</span>
      <div className="min-w-0"><div className="text-[15px] font-semibold">{label}</div>{detail && <div className="break-words text-[13px] text-dim">{detail}</div>}</div>
    </div>
  );
}

function Step({ n, title, children }: { n: number; title: string; children: React.ReactNode }) {
  const [open, setOpen] = useState(n === 1);
  return (
    <div className="rounded-2xl bg-panel2/60">
      <button onClick={() => setOpen(!open)} className="flex w-full items-center gap-3 px-4 py-3.5 text-left">
        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-cash text-[13px] font-black text-oncash">{n}</span>
        <span className="flex-1 text-[15px] font-semibold">{title}</span>
        <ChevronDown size={18} className={clsx("text-faint transition", open && "rotate-180")} />
      </button>
      {open && <div className="space-y-2 px-4 pb-4 pl-14 text-[13.5px] leading-relaxed text-dim animate-fade">{children}</div>}
    </div>
  );
}

const A = ({ href, children }: { href: string; children: React.ReactNode }) => (
  <a href={href} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 font-semibold text-accent hover:underline">{children}<ExternalLink size={12} /></a>
);

export default function LivePage() {
  const { data: st, error, reload } = usePoll<any>("/api/live/status", 8000);
  const { wallet, reload: reloadW } = useWallet();
  const cred = wallet?.keys;
  const reloadCred = reloadW;
  const { data: strategies } = usePoll<any[]>("/api/strategies", 0);
  const [f, setF] = useState({ private_key: "", wallet_address: "", relayer_key: "", relayer_address: "", builder_key: "", builder_secret: "", builder_passphrase: "" });
  const [pw, setPw] = useState("");
  const [ack, setAck] = useState(false);
  const [strat, setStrat] = useState("K");
  const [adv, setAdv] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const ex = st?.executor || {};
  const geo = st?.geoblock || {};
  const acct = st?.accounts?.[0];
  const switchOn = !(st?.reasons || []).some((r: string) => r.startsWith("Live trading switch"));
  const run = async (fn: () => Promise<any>, ok: string) => {
    setErr(null); setMsg(null); setBusy(true);
    try { await fn(); setMsg(ok); reload(); reloadCred(); } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  };
  const set = (k: string) => (e: any) => setF((x) => ({ ...x, [k]: e.target.value.trim() }));

  return (
    <div className="page max-w-[1100px] space-y-4">
      <ErrorNote error={error} />
      <div className={clsx("relative overflow-hidden rounded-4xl px-6 py-7 text-white animate-pop",
        st?.armed ? "bg-[linear-gradient(135deg,#ff3b30,#c2185b)]" : st?.eligible ? "bg-[linear-gradient(135deg,#00b86b,#1659c7)]" : "bg-[linear-gradient(135deg,#3a3a3c,#1c1c1e)]")}>
        <div className="card-shine" />
        <div className="relative">
          <div className="text-[14px] font-semibold opacity-85">Live trading · real money</div>
          <div className="mt-1 flex items-center gap-3 text-[44px] font-bold leading-none tracking-tight">
            {st?.armed && <span className="h-4 w-4 rounded-full bg-white live-pulse" />}
            {st?.armed ? "ON" : st?.eligible ? "Ready to arm" : "Off"}
          </div>
          <div className="mt-2 text-[14px] opacity-85">{st?.armed ? "Bots with a running live session place real orders." : "Paper trading keeps working either way."}</div>
        </div>
      </div>

      {(st?.warnings || []).map((w: string, i: number) => (
        <div key={i} className="flex gap-3 rounded-3xl bg-warn/10 px-5 py-4 text-[13.5px] text-warn"><AlertTriangle size={18} className="mt-0.5 shrink-0" />{w}</div>
      ))}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Panel title="Checklist">
          <Row ok={!!cred?.configured || ex.source === "environment"} label="1. Polymarket API keys added"
            detail={cred?.configured ? `key ${cred.private_key}${cred.wallet_address ? ` · wallet ${cred.wallet_address.slice(0, 8)}…` : ""}` : ex.source === "environment" ? "from server environment" : "add them below"} />
          <Row ok={!!ex.ok} label="2. Connected to Polymarket" detail={ex.ok ? `wallet ${ex.wallet} · ${ex.gasless ? "auto-redeem on" : "auto-redeem off (add Relayer key)"}` : ex.error} />
          <Row ok={switchOn} label="3. Live switch ON" detail={switchOn ? "on" : "turn it on below"} />
          <Row ok={!!geo.reachable && !(st?.reasons || []).some((r: string) => r.startsWith("Server location"))} label="4. Server location accepted"
            detail={geo.country ? `${geo.country}${geo.region ? "-" + geo.region : ""} (API not restricted for NL)` : geo.error} />
          <Row ok={!!acct} label="5. Live account created" detail={acct ? `${acct.name} · strategy ${acct.strategy_key}` : "create below"} />
          <Row ok={!!st?.armed} label="6. Armed with your password" />
          <Row ok={!!acct?.session?.active} label="7. Bot started on the $ tab" detail={acct?.session?.active ? `budget ${usd(acct.session.risk_budget)} · SL ${acct.session.stop_loss_pct}%` : "pick the live account, set risk, Start bot"} />
          <div className="mt-2 text-[12px] text-faint">Safety caps: {usd(st?.limits?.max_order_usd)} per order · {usd(st?.limits?.max_session_budget_usd)} per session.</div>
        </Panel>

        <Panel title="Where to find what you need" right={<KeyRound size={18} className="text-dim" />}
          sub="You do NOT log in to Polymarket here. The bot only needs these values.">
          <div className="space-y-2">
            <Step n={1} title="Your private key (required)">
              <p><b className="text-ink">Signed up with email/Google:</b> while logged in to Polymarket, open <A href="https://reveal.magic.link/polymarket">reveal.magic.link/polymarket</A>, sign in, tap <b className="text-ink">Export Private Key</b>, copy it, then log out of Magic.</p>
              <p><b className="text-ink">Signed up with MetaMask / a wallet:</b> in your wallet app → Account details → Show private key.</p>
              <p>It looks like <span className="mono text-ink">0x</span> + 64 letters/numbers. Polymarket's guide: <A href="https://help.polymarket.com/en/articles/13364258-how-do-i-export-my-key">How do I export my key?</A></p>
            </Step>
            <Step n={2} title="Your Polymarket wallet address (recommended)">
              <p>On polymarket.com, click your <b className="text-ink">profile picture</b> (top right). The address under your name (<span className="mono">0x…</span>, 42 characters) is your trading wallet. Copy it.</p>
              <p>If you leave it empty, the bot uses the default deposit wallet for your key (this is how Polybot worked).</p>
            </Step>
            <Step n={3} title="Relayer API key (optional — for auto-redeem)">
              <p>polymarket.com → <b className="text-ink">Settings → API Keys → Relayer API Keys</b> → create one. Copy the key and the address shown with it.</p>
              <p>Needed only for one-time trading approvals and to collect winnings automatically. Without it, trades still work; you redeem winnings on polymarket.com.</p>
              <p className="text-faint">Alternative (what Polybot used): <b>Settings → Builders</b> (<A href="https://polymarket.com/settings?tab=builder">polymarket.com/settings?tab=builder</A>) → create API key → copy Key, Secret and Passphrase.</p>
            </Step>
            <Step n={4} title="Money in your Polymarket wallet">
              <p>Deposit on polymarket.com (<b className="text-ink">Deposit</b> button). Trades use <b className="text-ink">pUSD</b> (Polymarket's USDC). Polymarket recommends at least <b className="text-ink">$10</b>; each order here is at least <b className="text-ink">$1</b> (5 shares minimum).</p>
            </Step>
          </div>
        </Panel>
      </div>

      <WalletBar />
      <Panel title={`API keys · ${wallet?.name ?? ""}`} right={<ShieldCheck size={18} className="text-up" />}
        sub="Encrypted on your server, never shown again, never sent to the browser or GitHub.">
        {cred?.configured && (
          <div className="mb-4 flex flex-wrap items-center gap-3 rounded-2xl bg-up/10 px-4 py-3 text-[13.5px]">
            <Check size={16} className="text-up" /><span>Saved: key <b className="mono">{cred.private_key}</b>{cred.wallet_address && <> · wallet <b className="mono">{cred.wallet_address.slice(0, 10)}…</b></>} · {cred.gasless ? "auto-redeem key added" : "no relayer key"}</span>
          </div>
        )}
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          <Field label="Private key *"><input type="password" autoComplete="off" spellCheck={false} className={inputCls + " py-3"} placeholder="0x…" value={f.private_key} onChange={set("private_key")} /></Field>
          <Field label="Polymarket wallet address"><input autoComplete="off" spellCheck={false} className={inputCls + " py-3"} placeholder="0x… (from your profile menu)" value={f.wallet_address} onChange={set("wallet_address")} /></Field>
          <Field label="Relayer API key (optional)"><input type="password" autoComplete="off" className={inputCls + " py-3"} value={f.relayer_key} onChange={set("relayer_key")} /></Field>
          <Field label="Relayer key address (optional)"><input autoComplete="off" className={inputCls + " py-3"} placeholder="0x…" value={f.relayer_address} onChange={set("relayer_address")} /></Field>
        </div>
        <button onClick={() => setAdv(!adv)} className="mt-3 text-[13px] font-semibold text-dim hover:text-ink">{adv ? "Hide" : "Use"} Builder keys instead (Polybot style)</button>
        {adv && (
          <div className="mt-2 grid grid-cols-1 gap-3 md:grid-cols-3 animate-fade">
            <Field label="Builder key"><input type="password" autoComplete="off" className={inputCls + " py-3"} value={f.builder_key} onChange={set("builder_key")} /></Field>
            <Field label="Builder secret"><input type="password" autoComplete="off" className={inputCls + " py-3"} value={f.builder_secret} onChange={set("builder_secret")} /></Field>
            <Field label="Builder passphrase"><input type="password" autoComplete="off" className={inputCls + " py-3"} value={f.builder_passphrase} onChange={set("builder_passphrase")} /></Field>
          </div>
        )}
        <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-[1fr_auto_auto]">
          <Field label="PIN (to confirm)"><input type="password" className={inputCls + " py-3"} value={pw} onChange={(e) => setPw(e.target.value)} /></Field>
          <div className="flex items-end"><Button tone="primary" size="lg" disabled={busy || !f.private_key}
            onClick={() => run(() => put(`/api/wallets/${wallet?.id}/credentials`, { ...f, password: pw, confirm: "CONFIRM" }).then(() => setF({ private_key: "", wallet_address: "", relayer_key: "", relayer_address: "", builder_key: "", builder_secret: "", builder_passphrase: "" })), "Keys saved and sent to the executor")}>
            {busy ? "Saving…" : "Save keys"}</Button></div>
          {cred?.configured && <div className="flex items-end"><Button tone="danger" size="lg" onClick={() => confirm("Delete the saved keys? Live trading will stop.") && run(() => post(`/api/wallets/${wallet?.id}/credentials/delete`, { password: pw, confirm: "CONFIRM" }), "Keys deleted")}>Delete keys</Button></div>}
        </div>
      </Panel>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Panel title="Live switch" sub="Master on/off for real-money trading.">
          <button onClick={() => run(() => post("/api/live/switch", { password: pw, confirm: "CONFIRM", enabled: !switchOn }), switchOn ? "Live switch off" : "Live switch on")}
            className={clsx("flex w-full items-center justify-between rounded-3xl px-5 py-4 transition active:scale-[.99]", switchOn ? "bg-down/15" : "bg-panel2")}>
            <span className="text-[16px] font-semibold">{switchOn ? "Live trading enabled" : "Live trading disabled"}</span>
            <span className={clsx("h-8 w-14 rounded-full p-1 transition", switchOn ? "bg-down" : "bg-line2")}>
              <span className={clsx("block h-6 w-6 rounded-full bg-white shadow transition", switchOn && "translate-x-6")} /></span>
          </button>
          <p className="mt-2 text-[12px] text-faint">Uses the PIN entered above.</p>
        </Panel>

        <Panel title={acct ? acct.name : "Live account"}>
          {acct ? (
            <div className="space-y-3">
              <div className="text-[40px] font-bold leading-none tracking-tight">{usd(acct.summary.equity)}</div>
              <div className="text-[13px] text-dim">Synced from your wallet when a session starts · realised {signedUsd(acct.summary.realized_pnl)}</div>
              <Link href={`/bot/?acct=${acct.id}`} className="pill w-full py-3.5">Open on the $ tab</Link>
            </div>
          ) : (
            <div className="space-y-3">
              <Field label="Strategy"><Select value={strat} onChange={setStrat} className="w-full" options={(strategies || []).map((s) => ({ value: s.key, label: `${s.key} · ${s.name}` }))} /></Field>
              <Button tone="primary" size="lg" className="w-full" onClick={() => run(() => post("/api/live/account", { strategy_key: strat }), "Live account created")}>Create live account</Button>
            </div>
          )}
        </Panel>
      </div>

      <Panel title={st?.armed ? "Disarm" : "Arm live trading"} sub="Final step. Arming survives server restarts until you disarm.">
        {st?.armed ? (
          <Button tone="solid" size="lg" className="w-full" onClick={() => run(() => post("/api/live/disarm"), "Disarmed")}>Disarm live trading</Button>
        ) : (
          <div className="space-y-3">
            <label className="flex items-start gap-2 text-[13.5px] text-dim">
              <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} className="mt-1" />
              I understand this places REAL orders with my Polymarket wallet and losses are real.
            </label>
            <Button tone="danger" size="lg" className="w-full" disabled={!ack || !st?.eligible}
              onClick={() => run(() => post("/api/live/arm", { password: pw, confirm: true }), "Live trading armed")}>Arm live trading</Button>
            {!st?.eligible && <div className="text-[13px] text-down">{(st?.reasons || []).join(" · ")}</div>}
          </div>
        )}
      </Panel>
      <ErrorNote error={err} />
      {msg && <div className="rounded-2xl bg-up/10 px-4 py-3 text-[13px] text-up animate-fade">{msg}</div>}
    </div>
  );
}
