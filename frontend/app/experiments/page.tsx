"use client";
import { Download, FileText } from "lucide-react";
import { useState } from "react";
import { Button, DataTable, Drawer, ErrorNote, Field, inputCls, KV, Panel, Pill, Stat } from "@/components/ui";
import { api, post, usePoll } from "@/lib/api";
import { ago, dur, int, num, pct, pnlClass, signedUsd, ts, usd } from "@/lib/format";

const DURS = ["1h", "2h", "6h", "12h", "24h", "48h", "unlimited"];
const ASSETS = ["BTC", "ETH", "SOL", "XRP", "DOGE", "HYPE", "BNB"];

export default function Experiments() {
  const { data: exps, error, reload } = usePoll<any[]>("/api/experiments", 5000);
  const { data: accounts } = usePoll<any[]>("/api/accounts", 0);
  const { data: health } = usePoll<any>("/api/health", 5000);
  const [dur_, setDur] = useState("24h");
  const [name, setName] = useState("");
  const [assets, setAssets] = useState<string[]>(ASSETS);
  const [accts, setAccts] = useState<number[]>([]);
  const [bal, setBal] = useState("20");
  const [reset, setReset] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const running = exps?.find((e) => e.status === "running" || e.status === "paused");
  const c = health?.collector;
  const start = async () => {
    setErr(null);
    try {
      await post("/api/experiments", { name: name || undefined, duration: dur_, assets, account_ids: accts, starting_balance: Number(bal), reset_accounts: reset });
      reload();
    } catch (e: any) { setErr(e.message); }
  };
  const act = async (id: string, a: string) => { try { await post(`/api/experiments/${id}/${a}`); reload(); } catch (e: any) { setErr(e.message); } };
  return (
    <div className="page space-y-3">
      <div className="grid grid-cols-1 gap-3 xl:grid-cols-[1fr_1fr]">
        <Panel title="Start experiment" sub="The backend collector runs independently of this browser tab. Experiments persist through restarts; time while the PC is asleep is recorded as a data gap.">
          {running ? (
            <div className="space-y-2">
              <div className="flex items-center gap-2"><Pill kind={running.status === "running" ? "LIVE" : "DEGRADED"}>{running.status.toUpperCase()}</Pill><span className="mono">{running.id}</span></div>
              <div className="grid-auto">
                <Stat label="Elapsed" value={dur(running.elapsed_seconds)} /><Stat label="Remaining" value={running.remaining_seconds != null ? dur(running.remaining_seconds) : "unlimited"} />
                <Stat label="Signals" value={int(running.signal_count)} /><Stat label="Trades" value={int(running.trade_count)} />
                <Stat label="Wins / losses" value={`${running.win_count} / ${running.loss_count}`} />
              </div>
              <div className="flex gap-2">
                {running.status === "running" ? <Button tone="warn" onClick={() => act(running.id, "pause")}>Pause</Button> : <Button tone="primary" onClick={() => act(running.id, "resume")}>Resume</Button>}
                <Button tone="danger" onClick={() => confirm("Stop and generate the final report?") && act(running.id, "stop")}>Stop & report</Button>
              </div>
            </div>
          ) : (
            <div className="space-y-3">
              <Field label="Duration"><div className="flex flex-wrap gap-1">{DURS.map((d) => <Button key={d} size="sm" tone={d === dur_ ? "primary" : "default"} onClick={() => setDur(d)}>{d}</Button>)}</div></Field>
              <Field label="Name"><input className={inputCls} value={name} onChange={(e) => setName(e.target.value)} placeholder={`${dur_} reversal experiment`} /></Field>
              <Field label="Assets"><div className="flex flex-wrap gap-1">{ASSETS.map((a) => (
                <Button key={a} size="sm" tone={assets.includes(a) ? "primary" : "default"} onClick={() => setAssets((x) => x.includes(a) ? x.filter((y) => y !== a) : [...x, a])}>{a}</Button>))}</div></Field>
              <Field label="Strategies / accounts (none selected = all active)">
                <div className="flex max-h-28 flex-wrap gap-1 overflow-y-auto">{(accounts || []).map((a) => (
                  <Button key={a.id} size="sm" tone={accts.includes(a.id) ? "primary" : "default"} onClick={() => setAccts((x) => x.includes(a.id) ? x.filter((y) => y !== a.id) : [...x, a.id])}>{a.name}</Button>))}</div>
              </Field>
              <div className="flex flex-wrap items-end gap-3">
                <Field label="Starting balance per account"><input className={inputCls + " w-24"} value={bal} onChange={(e) => setBal(e.target.value)} /></Field>
                <label className="flex items-center gap-1 text-xs text-dim"><input type="checkbox" checked={reset} onChange={(e) => setReset(e.target.checked)} />reset account balances</label>
                <Button tone="primary" onClick={start}>Start experiment</Button>
              </div>
            </div>
          )}
          <ErrorNote error={err || error} />
        </Panel>
        <Panel title="Collector & data health">
          <div className="grid-auto">
            <Stat label="Collector" value={c?.running ? "running" : "stopped"} tone={c?.running ? "up" : "down"} sub={`since ${ts(c?.started_ts)}`} />
            <Stat label="Last successful update" value={ago(c?.last_tick_ts)} />
            <Stat label="Observations written" value={int(c?.observations_written)} sub="this session" />
            <Stat label="Missing observations" value={int(health?.missing_seconds_total)} tone={(health?.missing_seconds_total || 0) > 0 ? "warn" : undefined} sub="seconds, all time" />
            <Stat label="CLOB websocket" value={c?.clob_ws?.connected ? "connected" : "down"} tone={c?.clob_ws?.connected ? "up" : "down"} sub={`reconnect attempts ${c?.clob_ws?.reconnect_attempts ?? 0}`} />
            <Stat label="Chainlink RTDS" value={c?.rtds?.connected ? "connected" : "down"} tone={c?.rtds?.connected ? "up" : "down"} />
            <Stat label="Binance" value={c?.binance?.connected ? "connected" : "down"} tone={c?.binance?.connected ? "up" : "warn"} />
            <Stat label="Write errors" value={int(c?.write_errors)} tone={c?.write_errors ? "down" : undefined} />
            <Stat label="Database" value={health?.db?.integrity || "—"} tone={health?.db?.integrity === "ok" ? "up" : "warn"} sub={`${health?.db?.size_mb ?? "?"} MB`} />
            <Stat label="Connection failures" value={int(Object.values(health?.connections || {}).reduce((s: number, x: any) => s + (x.failures || 0), 0))} />
          </div>
          <div className="mt-3">
            <div className="label mb-1">Recent data gaps</div>
            <DataTable rows={health?.gaps || []} maxHeight={160} empty="No gaps recorded." cols={[
              { key: "asset", label: "Asset" }, { key: "start_ts", label: "From", render: (r: any) => ts(r.start_ts) }, { key: "end_ts", label: "To", render: (r: any) => ts(r.end_ts) },
              { key: "missing_seconds", label: "Missing s" }, { key: "reason", label: "Reason", align: "left" }]} />
          </div>
        </Panel>
      </div>
      <Panel title="Experiment history">
        <DataTable rows={exps || []} onRow={(r) => setOpen(r.id)} cols={[
          { key: "id", label: "ID", render: (r) => <span className="mono text-info">{r.id}</span> }, { key: "name", label: "Name", align: "left" },
          { key: "status", label: "Status", align: "center" }, { key: "started_ts", label: "Started", render: (r) => ts(r.started_ts) },
          { key: "duration_hours", label: "Duration", render: (r) => (r.duration_hours ? `${r.duration_hours}h` : "∞") },
          { key: "assets", label: "Assets", align: "left", render: (r) => r.assets.join(",") }, { key: "account_ids", label: "Accts", render: (r) => r.account_ids.length },
          { key: "observation_count", label: "Obs", render: (r) => int(r.observation_count) }, { key: "signal_count", label: "Signals" }, { key: "trade_count", label: "Trades" },
          { key: "win_count", label: "W" }, { key: "loss_count", label: "L" },
          { key: "starting_balance", label: "Start $", render: (r) => usd(r.starting_balance) }, { key: "ending_balance", label: "End $", render: (r) => usd(r.ending_balance, 4) },
          { key: "net_profit", label: "Net", render: (r) => <span className={pnlClass(r.net_profit)}>{signedUsd(r.net_profit, 4)}</span> },
          { key: "report_id", label: "Report", render: (r) => r.report_id ? <a onClick={(e) => e.stopPropagation()} href={`/api/reports/${r.report_id}/html`} target="_blank" className="text-info">open</a> : "—" },
        ]} />
      </Panel>
      <ExpDrawer id={open} onClose={() => setOpen(null)} />
    </div>
  );
}

function ExpDrawer({ id, onClose }: { id: string | null; onClose: () => void }) {
  const { data } = usePoll<any>(id ? `/api/experiments/${id}` : null, 10000);
  const [rep, setRep] = useState<any>(null);
  const r = data?.reports?.[0];
  const loadRep = async () => r && setRep((await api(`/api/reports/${r.id}`)).summary);
  return (
    <Drawer open={!!id} onClose={() => { setRep(null); onClose(); }} title={`Experiment ${id}`} wide>
      {!data ? <div className="text-faint">Loading…</div> : (
        <div className="space-y-3">
          <div className="flex flex-wrap gap-2">
            {r && <><a href={`/api/reports/${r.id}/html`} target="_blank"><Button size="sm" tone="primary"><FileText size={12} />HTML report</Button></a>
              <a href={`/api/reports/${r.id}/csv`}><Button size="sm"><Download size={12} />CSV</Button></a>
              <Button size="sm" onClick={loadRep}>Show summary here</Button></>}
            <Button size="sm" onClick={async () => { await post(`/api/experiments/${id}/report`); }}>Regenerate report</Button>
          </div>
          <Panel title="Configuration snapshot"><pre className="mono max-h-64 overflow-auto text-2xs text-dim">{JSON.stringify(data.config, null, 1)}</pre></Panel>
          <Panel title="Performance by strategy (this experiment)">
            <DataTable rows={data.live_performance || []} cols={[{ key: "account", label: "Account", align: "left" }, { key: "trades", label: "Trades" },
              { key: "wins", label: "W" }, { key: "losses", label: "L" }, { key: "win_rate", label: "Win", render: (x: any) => pct(x.win_rate) },
              { key: "net_pnl", label: "Net", render: (x: any) => <span className={pnlClass(x.net_pnl)}>{signedUsd(x.net_pnl, 4)}</span> },
              { key: "max_drawdown", label: "Max DD", render: (x: any) => usd(x.max_drawdown, 4) }]} />
          </Panel>
          {rep && <Panel title="Report conclusion">
            <KV rows={Object.entries(rep.conclusion).filter(([k]) => k !== "notes").map(([k, v]) => [k.replace(/_/g, " "), String(v)] as [string, string])} />
          </Panel>}
        </div>
      )}
    </Drawer>
  );
}
