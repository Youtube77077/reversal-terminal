"use client";
import { useEffect, useState } from "react";
import { api, qs } from "@/lib/api";
import { pct, price, ts } from "@/lib/format";
import { DataTable, Drawer } from "./ui";

/** Drill-down: shows the raw resolved observations behind a statistic. */
export default function Drill({ filter, onClose }: { filter: Record<string, any> | null; onClose: () => void }) {
  const [rows, setRows] = useState<any[] | null>(null);
  useEffect(() => {
    if (!filter) return;
    setRows(null);
    api(`/api/analytics/checkpoints${qs({ ...filter, limit: 1000 })}`).then(setRows).catch(() => setRows([]));
  }, [filter]);
  const title = filter ? Object.entries(filter).filter(([, v]) => v !== undefined && v !== "").map(([k, v]) => `${k}=${v}`).join(" · ") : "";
  return (
    <Drawer open={!!filter} onClose={onClose} title={`Underlying observations — ${title}`} wide>
      {rows === null ? <div className="text-faint">Loading…</div> : (
        <DataTable exportName="observations_drilldown" rows={rows} maxHeight={760} cols={[
          { key: "server_ts", label: "Time", render: (r) => ts(r.server_ts) },
          { key: "asset", label: "Asset" },
          { key: "slug", label: "Market", align: "left", render: (r) => <a className="mono text-dim hover:text-ink" href={`/replay?id=${r.market_id}`}>{r.slug}</a> },
          { key: "t_minus", label: "T-" },
          { key: "actual_secs_remaining", label: "secs", render: (r) => r.actual_secs_remaining?.toFixed(3) },
          { key: "favourite", label: "Fav", align: "center" },
          { key: "fav_prob", label: "Fav prob", render: (r) => pct(r.fav_prob) },
          { key: "dog_ask", label: "Dog ask", render: (r) => price(r.dog_ask) },
          { key: "dog_ask_liq", label: "Liq $", render: (r) => r.dog_ask_liq?.toFixed(2) },
          { key: "dist_bps", label: "Dist bp", render: (r) => r.dist_bps?.toFixed(2) },
          { key: "winner", label: "Winner", align: "center" },
          { key: "favourite_lost", label: "Reversal", align: "center", render: (r) => r.favourite_lost ? <span className="text-warn">YES</span> : "no" },
        ]} />
      )}
    </Drawer>
  );
}
