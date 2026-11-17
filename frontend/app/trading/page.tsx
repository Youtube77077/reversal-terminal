"use client";
import clsx from "clsx";
import { Lock, Plus, ShieldAlert } from "lucide-react";
import { useEffect, useState } from "react";
import { TimeChart } from "@/components/Chart";
import { Button, DataTable, Drawer, ErrorNote, Field, inputCls, KV, Panel, Pill, Select, Stat, Tabs } from "@/components/ui";
import { api, patch, post, usePoll } from "@/lib/api";
import { dur, num, pct, pnlClass, price, signedUsd, ts, usd } from "@/lib/format";

const PRESETS = [5, 10, 20, 50, 100, 250, 500];

export default function Trading() {
  const [mode, setMode] = useState<"paper" | "live">("paper");
  const { data: accounts, error, reload } = usePoll<any[]>("/api/accounts", 4000);
  const { data: strategies } = usePoll<any[]>("/api/strategies", 0);
  const { data: signals } = usePoll<any[]>("/api/signals?limit=150", 4000);
  const { data: orders } = usePoll<any[]>("/api/orders?limit=150", 4000);
  const { data: status } = usePoll<any>("/api/status", 4000);
  const [sel, setSel] = useState<number | null>(null);
  const [tab, setTab] = useState("signals");
  const [creating, setCreating] = useState(false);
  const selAcct = accounts?.find((a) => a.id === sel);
  const engPaused = status?.engine?.paused;

  return (
    <div className="page space-y-3">
      <div className="panel flex flex-wrap items-center gap-3 px-3 py-2">
        <span className="label">Execution mode</span>
        <div className="flex overflow-hidden rounded border border-line2">
          <button onClick={() => setMode("paper")} className={clsx("px-4 py-1.5 text-xs font-bold tracking-wider", mode === "paper" ? "bg-info/20 text-info" : "text-dim")}>PAPER</button>
          <button onClick={() => setMode("live")} className={clsx("flex items-center gap-1 px-4 py-1.5 text-xs font-bold tracking-wider", mode === "live" ? "bg-down/15 text-down" : "text-dim")}><Lock size={11} />LIVE</button>
        </div>
        <span className="text-2xs text-faint">Mode never switches silently. Paper uses virtual funds against the real order book.</span>
        <div className="ml-auto flex items-center gap-2">
          <span className="text-2xs text-dim">Engine: {engPaused ? <span className="text-warn">PAUSED</span> : status?.experiment?.status === "running" ? <span className="text-up">TRADING</span> : <span className="text-dim">IDLE (no running experiment)</span>}</span>
          <Button tone="danger" size="sm" onClick={async () => { if (confirm("Emergency stop: pause the engine and every account?")) { await post("/api/engine/emergency-stop"); reload(); } }}>
            <ShieldAlert size={12} /> EMERGENCY STOP
          </Button>
        </div>
      </div>

      {mode === "live" ? <LivePanel /> : (
        <>
          <ErrorNote error={error} />
          <Panel title={`Paper accounts (${accounts?.length ?? 0})`} sub="Each account has its own balance, strategy, risk limits, transactions and statistics."
            right={<Button tone="primary" size="sm" onClick={() => setCreating(true)}><Plus size={12} />New account</Button>}>
            <DataTable exportName="accounts" rows={accounts || []} onRow={(r) => setSel(r.id)} cols={[
              { key: "name", label: "Account", align: "left", render: (r) => <span className="font-medium">{r.name}</span> },
              { key: "strategy_key", label: "Strat", align: "center" },
              { key: "status", label: "State", align: "center", sort: (r) => r.halted_reason || r.paused,
                render: (r) => r.halted_reason ? <span className="text-down" title={r.halted_reason}>HALTED</span> : r.paused ? <span className="text-warn">paused</span> : <span className="text-up">active</span> },
              { key: "init", label: "Initial", render: (r) => usd(r.summary.initial_balance) },
              { key: "avail", label: "Available", sort: (r) => r.summary.available, render: (r) => usd(r.summary.available, 4) },
              { key: "res", label: "Reserved", render: (r) => usd(r.summary.reserved, 4) },
              { key: "open", label: "Open cost", render: (r) => usd(r.summary.open_position_cost, 4) },
              { key: "real", label: "Realised P&L", sort: (r) => r.summary.realized_pnl, render: (r) => <span className={pnlClass(r.summary.realized_pnl)}>{signedUsd(r.summary.realized_pnl, 4)}</span> },
              { key: "unreal", label: "Unrealised (est.)", render: (r) => <span className={pnlClass(r.summary.unrealized_pnl)}>{signedUsd(r.summary.unrealized_pnl, 4)}</span> },
              { key: "eq", label: "Equity", sort: (r) => r.summary.equity, render: (r) => usd(r.summary.equity, 4) },
              { key: "pos", label: "Open pos", render: (r) => r.summary.open_positions },
            ]} rowClass={(r) => (r.summary.available <= 0 ? "bg-down/5" : undefined)} />
            {accounts?.some((a) => a.summary.available <= 0) && (
              <div className="mt-2 rounded border border-down/40 bg-down/10 px-3 py-1.5 text-xs text-down">
                Insufficient funds: one or more accounts have a zero virtual balance and will not place new simulated trades.
              </div>
            )}
          </Panel>

          <Panel pad={false}>
            <div className="px-3 pt-2"><Tabs value={tab} onChange={setTab} tabs={[{ key: "signals", label: "Signals" }, { key: "orders", label: "Simulated orders" }]} /></div>
            <div className="p-3">
              {tab === "signals" && <DataTable exportName="signals" rows={signals || []} maxHeight={480} cols={[
                { key: "ts", label: "Time", render: (r) => ts(r.ts) },
                { key: "strategy_key", label: "Strat", align: "center" },
                { key: "account_id", label: "Acct", render: (r) => accounts?.find((a) => a.id === r.account_id)?.name ?? r.account_id },
                { key: "asset", label: "Asset" },
                { key: "side", label: "Side", align: "center" },
                { key: "secs_remaining", label: "T-", render: (r) => `${r.secs_remaining.toFixed(1)}s` },
                { key: "fav_prob", label: "Fav prob", render: (r) => pct(r.fav_prob) },
                { key: "entry_ask", label: "Ask", render: (r) => price(r.entry_ask) },
                { key: "ask_liq", label: "Liq $", render: (r) => num(r.ask_liq, 2) },
                { key: "decision", label: "Decision", align: "center", render: (r) => r.decision === "accepted" ? <span className="text-up">accepted</span> : <span className="text-warn">rejected</span> },
                { key: "reject_reason", label: "Reason", align: "left", render: (r) => <span className="text-dim">{r.reject_reason || ""}</span> },
              ]} />}
              {tab === "orders" && <DataTable exportName="orders" rows={orders || []} maxHeight={480} cols={[
                { key: "decision_ts", label: "Decision", render: (r) => ts(r.decision_ts) },
                { key: "transaction_id", label: "Tx", render: (r) => <a href={`/transactions/view/?id=${r.transaction_id}`} className="text-info hover:underline">{r.transaction_id}</a> },
                { key: "side", label: "Side", align: "center" },
                { key: "order_type", label: "Type", align: "center" },
                { key: "tif", label: "TIF", align: "center" },
                { key: "limit_price", label: "Limit", render: (r) => price(r.limit_price) },
                { key: "requested_shares", label: "Req", render: (r) => num(r.requested_shares, 2) },
                { key: "filled_shares", label: "Filled", render: (r) => num(r.filled_shares, 2) },
                { key: "latency", label: "Latency", render: (r) => r.executed_ts ? `${r.executed_ts - r.decision_ts}ms` : "—" },
                { key: "status", label: "Status", align: "center", render: (r) => <span className={r.status === "filled" ? "text-up" : r.status === "partially_filled" ? "text-info" : r.status === "pending" ? "text-ink" : "text-warn"}>{r.status}</span> },
                { key: "failure_reason", label: "Reason", align: "left", render: (r) => <span className="text-dim">{r.failure_reason || ""}</span> },
              ]} />}
            </div>
          </Panel>
        </>
      )}
      <AccountDrawer acct={selAcct} onClose={() => setSel(null)} reload={reload} strategies={strategies || []} />
      <CreateAccount open={creating} onClose={() => setCreating(false)} strategies={strategies || []} onDone={reload} />
    </div>
  );
}

function LivePanel() {
  return (
    <Panel title="Live mode" sub="Real-money trading has its own screen with the eligibility checklist, API-key setup and the arm switch.">
      <a href="/live" className="pill w-full py-3.5">Open Live trading</a>
    </Panel>
  );
}

function AccountDrawer({ acct, onClose, reload, strategies }: { acct: any; onClose: () => void; reload: () => void; strategies: any[] }) {
  const [ledger, setLedger] = useState<any[]>([]);
  const [hist, setHist] = useState<any[]>([]);
  const [amount, setAmount] = useState("10");
  const [msg, setMsg] = useState<string | null>(null);
  const [params, setParams] = useState("");
  const [riskTxt, setRiskTxt] = useState("");
  useEffect(() => {
    if (!acct) return;
    api(`/api/accounts/${acct.id}/ledger`).then(setLedger);
    api(`/api/accounts/${acct.id}/balance-history`).then(setHist);
    setParams(JSON.stringify(acct.params, null, 1));
    setRiskTxt(JSON.stringify(acct.risk, null, 1));
    setMsg(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [acct?.id]);
  if (!acct) return null;
  const act = async (action: string, body?: any) => {
    try { await post(`/api/accounts/${acct.id}/${action}`, body); setMsg(`${action} ok`); reload(); api(`/api/accounts/${acct.id}/ledger`).then(setLedger); }
    catch (e: any) { setMsg(e.message); }
  };
  const s = acct.summary;
  const strat = strategies.find((x) => x.key === acct.strategy_key);
  return (
    <Drawer open={!!acct} onClose={onClose} title={`${acct.name} — paper account #${acct.id}`} wide>
      <div className="space-y-4">
        <div className="grid-auto">
          <Stat label="Initial balance" value={usd(s.initial_balance)} />
          <Stat label="Deposited (virtual)" value={usd(s.deposited)} />
          <Stat label="Withdrawn (virtual)" value={usd(s.withdrawn)} />
          <Stat label="Realised P&L" value={<span className={pnlClass(s.realized_pnl)}>{signedUsd(s.realized_pnl, 4)}</span>} />
          <Stat label="Unrealised P&L (est.)" value={<span className={pnlClass(s.unrealized_pnl)}>{signedUsd(s.unrealized_pnl, 4)}</span>} />
          <Stat label="Current equity" value={usd(s.equity, 4)} />
          <Stat label="Available funds" value={usd(s.available, 4)} tone={s.available <= 0 ? "down" : undefined} />
          <Stat label="Reserved funds" value={usd(s.reserved, 4)} />
        </div>
        {acct.halted_reason && <div className="rounded border border-down/40 bg-down/10 px-3 py-1.5 text-xs text-down">Halted: {acct.halted_reason}</div>}
        <Panel title="Balance management" sub="Every adjustment is recorded in the account ledger. Historical transactions are never modified.">
          <div className="flex flex-wrap items-end gap-2">
            <Field label="Amount (USD)"><input className={inputCls + " w-28"} value={amount} onChange={(e) => setAmount(e.target.value)} /></Field>
            <Button tone="primary" onClick={() => act("deposit", { amount: Number(amount) })}>Add virtual funds</Button>
            <Button onClick={() => act("withdraw", { amount: Number(amount) })}>Remove virtual funds</Button>
            <span className="mx-2 h-5 w-px bg-line" />
            {PRESETS.map((p) => <Button key={p} size="sm" onClick={() => confirm(`Reset balance to $${p}?`) && act("reset", { balance: p })}>${p}</Button>)}
            <Button size="sm" tone="warn" onClick={() => confirm(`Reset balance to $${amount}?`) && act("reset", { balance: Number(amount) })}>Reset to custom</Button>
            <span className="mx-2 h-5 w-px bg-line" />
            {acct.paused ? <Button size="sm" tone="primary" onClick={() => act("resume")}>Resume account</Button> : <Button size="sm" tone="warn" onClick={() => act("pause")}>Pause account</Button>}
            {acct.halted_reason && <Button size="sm" onClick={() => act("clear-halt")}>Clear halt</Button>}
          </div>
          {msg && <div className="mt-2 text-2xs text-dim">{msg}</div>}
        </Panel>
        <Panel title="Balance history">
          <TimeChart title={`equity_${acct.name}`} height={200} series={[
            { name: "equity", color: "#a3e635", data: hist.map((h) => ({ time: h.ts, value: h.equity })) },
            { name: "available", color: "#38bdf8", width: 1, data: hist.map((h) => ({ time: h.ts, value: h.cash })) },
          ]} />
        </Panel>
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <Panel title={`Strategy ${acct.strategy_key} · ${strat?.name || ""}`} sub={strat?.description}>
            <textarea className={inputCls + " h-48"} value={params} onChange={(e) => setParams(e.target.value)} />
            <Button size="sm" className="mt-2" onClick={async () => { try { await patch(`/api/accounts/${acct.id}`, { params: JSON.parse(params) }); setMsg("strategy params saved"); reload(); } catch (e: any) { setMsg(e.message); } }}>Save parameters</Button>
          </Panel>
          <Panel title="Risk limits (account level — strategies cannot bypass)">
            <textarea className={inputCls + " h-48"} value={riskTxt} onChange={(e) => setRiskTxt(e.target.value)} />
            <Button size="sm" className="mt-2" onClick={async () => { try { await patch(`/api/accounts/${acct.id}`, { risk: JSON.parse(riskTxt) }); setMsg("risk limits saved"); reload(); } catch (e: any) { setMsg(e.message); } }}>Save risk limits</Button>
          </Panel>
        </div>
        <Panel title="Account ledger">
          <DataTable exportName={`ledger_${acct.id}`} rows={ledger} maxHeight={360} cols={[
            { key: "ts", label: "Time", render: (r) => ts(r.ts) },
            { key: "kind", label: "Kind", align: "left", render: (r) => <span className={r.manual ? "text-warn" : ""}>{r.kind}{r.manual ? " (manual)" : ""}</span> },
            { key: "amount", label: "Amount", render: (r) => <span className={["reserve", "release"].includes(r.kind) ? "text-faint" : pnlClass(r.amount)}>{signedUsd(r.amount, 4)}</span> },
            { key: "cash_after", label: "Available after", render: (r) => usd(r.cash_after, 4) },
            { key: "reserved_after", label: "Reserved after", render: (r) => usd(r.reserved_after, 4) },
            { key: "transaction_id", label: "Tx", render: (r) => r.transaction_id ? <a className="text-info" href={`/transactions/view/?id=${r.transaction_id}`}>{r.transaction_id}</a> : "" },
            { key: "note", label: "Note", align: "left", render: (r) => <span className="text-dim">{r.note}</span> },
          ]} />
          <p className="mt-1 text-2xs text-faint">reserve / release are internal transfers between available and reserved funds (shown grey); trade_debit, settlement_credit and manual entries change the balance.</p>
        </Panel>
      </div>
    </Drawer>
  );
}

function CreateAccount({ open, onClose, strategies, onDone }: { open: boolean; onClose: () => void; strategies: any[]; onDone: () => void }) {
  const [name, setName] = useState("");
  const [key, setKey] = useState("A");
  const [bal, setBal] = useState("20");
  const [err, setErr] = useState<string | null>(null);
  return (
    <Drawer open={open} onClose={onClose} title="Create paper account">
      <div className="space-y-3">
        <Field label="Name"><input className={inputCls} value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. A · 3c cap" /></Field>
        <Field label="Strategy"><Select value={key} onChange={setKey} options={strategies.map((s) => ({ value: s.key, label: `${s.key} · ${s.name}` }))} /></Field>
        <Field label="Starting virtual balance (USD)">
          <div className="flex flex-wrap gap-1">{PRESETS.map((p) => <Button key={p} size="sm" tone={String(p) === bal ? "primary" : "default"} onClick={() => setBal(String(p))}>${p}</Button>)}
            <input className={inputCls + " w-24"} value={bal} onChange={(e) => setBal(e.target.value)} /></div>
        </Field>
        <ErrorNote error={err} />
        <Button tone="primary" onClick={async () => {
          try { await post("/api/accounts", { name: name || `${key} · custom`, strategy_key: key, balance: Number(bal) }); onDone(); onClose(); }
          catch (e: any) { setErr(e.message); }
        }}>Create account</Button>
      </div>
    </Drawer>
  );
}
