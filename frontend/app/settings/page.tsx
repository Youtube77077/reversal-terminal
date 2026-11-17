"use client";
import { Bell, Database, Download } from "lucide-react";
import { useEffect, useState } from "react";
import ResetCard from "@/components/ResetCard";
import { Button, DataTable, KV, Panel, Pill } from "@/components/ui";
import { post, put, usePoll } from "@/lib/api";
import { ts } from "@/lib/format";

const LABELS: Record<string, string> = {
  market_discovered: "A new market is discovered", opportunity: "A reversal opportunity appears", order_simulated: "An order is simulated",
  trade_settled: "A trade settles", loss_limit: "A strategy reaches a loss limit", connection_failed: "An asset connection fails",
  collector_stopped: "The data collector stops", experiment_completed: "An experiment completes",
};
const ASSETS = ["BTC", "ETH", "SOL", "XRP", "DOGE", "HYPE", "BNB"];

export default function Settings() {
  const { data: s, reload } = usePoll<any>("/api/settings", 0);
  const { data: assets, reload: reloadAssets } = usePoll<any[]>("/api/assets", 5000);
  const { data: health } = usePoll<any>("/api/health", 15000);
  const { data: events } = usePoll<any[]>("/api/events?limit=150", 10000);
  const [perm, setPerm] = useState<string>("default");
  const [msg, setMsg] = useState<string | null>(null);
  useEffect(() => { if (typeof window !== "undefined" && "Notification" in window) setPerm(Notification.permission); }, []);
  const save = async (v: any) => { await put("/api/settings", v); reload(); };
  return (
    <div className="page space-y-3">
      <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
        <Panel title="Notifications" right={<Bell size={14} className="text-dim" />} sub="Browser/desktop notifications, delivered while this dashboard is open. Each type can be disabled.">
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <span className="text-xs text-dim">Browser permission: <span className="mono text-ink">{perm}</span></span>
            {perm !== "granted" && <Button size="sm" tone="primary" onClick={async () => setPerm(await Notification.requestPermission())}>Enable desktop notifications</Button>}
            <label className="ml-auto flex items-center gap-1 text-xs"><input type="checkbox" checked={!!s?.notifications_enabled} onChange={(e) => save({ notifications_enabled: e.target.checked })} />All notifications</label>
          </div>
          <div className="grid grid-cols-1 gap-1 md:grid-cols-2">
            {Object.entries(LABELS).map(([k, label]) => (
              <label key={k} className="flex items-center gap-2 rounded border border-line px-2 py-1 text-xs">
                <input type="checkbox" checked={s?.notifications?.[k] !== false} onChange={(e) => save({ notifications: { ...s.notifications, [k]: e.target.checked } })} />{label}
              </label>
            ))}
          </div>
        </Panel>
        <Panel title="Asset trading controls" sub="Pausing an asset stops new simulated trades on it. Data collection continues.">
          <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
            {ASSETS.map((a) => {
              const row = assets?.find((x) => x.symbol === a);
              return (
                <div key={a} className="flex items-center justify-between rounded border border-line px-2 py-1">
                  <span className="mono font-bold">{a}</span>
                  {row?.paused ? <Button size="sm" tone="primary" onClick={async () => { await post(`/api/assets/${a}/resume`); reloadAssets(); }}>Resume</Button>
                    : <Button size="sm" tone="warn" onClick={async () => { await post(`/api/assets/${a}/pause`); reloadAssets(); }}>Pause</Button>}
                </div>
              );
            })}
          </div>
          <div className="mt-3 flex items-center gap-2 text-xs text-dim">Operating mode: <Pill kind="PAPER" /> <span>(live mode is locked by the eligibility check)</span></div>
        </Panel>
      </div>
      <ResetCard />
      <Panel title="Database" right={<Database size={14} className="text-dim" />}>
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
          <KV rows={[["Path", health?.db?.path], ["Size", `${health?.db?.size_mb ?? "?"} MB (WAL ${health?.db?.wal_mb ?? 0} MB)`], ["Integrity", health?.db?.integrity],
            ...Object.entries(health?.db?.tables || {}).map(([k, v]) => [k, String(v)] as [string, string]),
            ["Recent backups", (health?.db?.backups || []).map((b: any) => b.file).join(", ") || "none yet"]]} />
          <div className="flex flex-wrap content-start gap-2">
            <Button tone="primary" onClick={async () => { const r = await post("/api/db/backup"); setMsg(`Backup written: ${r.path}`); }}>Back up now</Button>
            <a href="/api/db/export?fmt=csv"><Button><Download size={12} />Export (CSV zip)</Button></a>
            <a href="/api/db/export?fmt=json"><Button><Download size={12} />Export (JSON zip)</Button></a>
            <a href="/api/db/export?fmt=csv&observations=true"><Button><Download size={12} />Full export incl. observations</Button></a>
            {msg && <div className="w-full text-2xs text-dim">{msg}</div>}
            <p className="text-2xs text-faint">Automatic backups run every BACKUP_INTERVAL_HOURS (default 6 h) using SQLite's online backup API. All timestamps are stored in UTC and shown in your local timezone ({Intl.DateTimeFormat().resolvedOptions().timeZone}).</p>
          </div>
        </div>
      </Panel>
      <Panel title="Application events">
        <DataTable rows={events || []} maxHeight={420} exportName="events" cols={[
          { key: "ts", label: "Time", render: (r: any) => ts(r.ts) }, { key: "level", label: "Level", align: "center", render: (r: any) => <span className={r.level === "ERROR" ? "text-down" : r.level === "WARNING" ? "text-warn" : "text-dim"}>{r.level}</span> },
          { key: "category", label: "Category" }, { key: "message", label: "Message", align: "left", render: (r: any) => <span className="text-dim">{r.message}</span> }]} />
      </Panel>
    </div>
  );
}
