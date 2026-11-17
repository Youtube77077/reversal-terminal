"use client";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import AssetCard from "@/components/AssetCard";
import { TimeChart } from "@/components/Chart";
import { useLive } from "@/lib/live";
import { DataTable, Drawer, ErrorNote, KV, Panel, Pill, Select } from "@/components/ui";
import { api, qs, usePoll } from "@/lib/api";
import { int, pct, price, spot, ts } from "@/lib/format";

const ASSETS = ["", "BTC", "ETH", "SOL", "XRP", "DOGE", "HYPE", "BNB"];
const STATUSES = ["", "upcoming", "active", "closed", "resolved", "cancelled"];

function MarketsInner() {
  const sp = useSearchParams();
  const [asset, setAsset] = useState("");
  const [status, setStatus] = useState(sp.get("status") || "");
  const [openId, setOpenId] = useState<number | null>(sp.get("id") ? Number(sp.get("id")) : null);
  const { data, error } = usePoll<any>(`/api/markets${qs({ asset, status, limit: 300 })}`, 10000);
  const { data: assets } = usePoll<any[]>("/api/assets", 10000);
  const { tick } = useLive();
  const NAMES: Record<string, string> = { BTC: "Bitcoin", ETH: "Ethereum", SOL: "Solana", XRP: "XRP", DOGE: "Dogecoin", HYPE: "Hyperliquid", BNB: "BNB" };
  return (
    <div className="page space-y-4">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4 2xl:grid-cols-7">
        {Object.keys(NAMES).map((a) => <AssetCard key={a} asset={a} name={NAMES[a]} state={tick?.assets?.[a]} status={tick?.asset_status?.[a]?.status} detail={tick?.asset_status?.[a]?.detail} />)}
      </div>
      <Panel title="Asset availability" sub="Each asset is verified against the live provider. Unavailable markets are shown as unavailable — never substituted or simulated.">
        <div className="grid grid-cols-2 gap-2 md:grid-cols-4 xl:grid-cols-7">
          {(assets || []).map((a) => (
            <div key={a.symbol} className="rounded border border-line bg-panel2/50 px-2 py-1.5">
              <div className="flex items-center justify-between"><span className="mono font-bold">{a.symbol}</span>
                <Pill kind={a.status === "live" ? "LIVE" : a.status === "unavailable" ? "UNAVAILABLE" : a.status === "degraded" ? "DEGRADED" : a.status === "waiting" ? "WAITING" : "OFFLINE"} /></div>
              <div className="text-2xs text-faint">{a.status_detail || (a.paused ? "trading paused" : "5m market verified")}</div>
            </div>
          ))}
        </div>
      </Panel>
      <Panel title={`Markets (${data?.total ?? 0})`} right={<>
        <Select value={asset} onChange={setAsset} options={ASSETS.map((a) => ({ value: a, label: a || "All assets" }))} />
        <Select value={status} onChange={setStatus} options={STATUSES.map((a) => ({ value: a, label: a || "All statuses" }))} />
      </>}>
        <ErrorNote error={error} />
        <DataTable exportName="markets" rows={data?.rows || []} onRow={(r) => setOpenId(r.id)} maxHeight={640} cols={[
          { key: "asset", label: "Asset" },
          { key: "slug", label: "Slug", align: "left", render: (r) => <span className="mono text-dim">{r.slug}</span> },
          { key: "open_ts", label: "Open", render: (r) => ts(r.open_ts) },
          { key: "close_ts", label: "Settles", render: (r) => ts(r.close_ts) },
          { key: "status", label: "Status", align: "center", render: (r) => <span className={r.status === "resolved" ? "text-dim" : r.status === "active" ? "text-up" : "text-warn"}>{r.status}</span> },
          { key: "open_price", label: "Open ref", render: (r) => spot(r.open_price) },
          { key: "close_price", label: "Settle ref", render: (r) => spot(r.close_price) },
          { key: "winner", label: "Winner", align: "center", render: (r) => r.winner ? <span className={r.winner === "UP" ? "text-up" : "text-down"}>{r.winner}</span> : "—" },
          { key: "observation_count", label: "Obs", render: (r) => int(r.observation_count) },
          { key: "fee_rate", label: "Fee", render: (r) => r.fee_verified ? `${r.fee_rate}` : <span className="text-warn">est.</span> },
          { key: "substitution_note", label: "Notes", align: "left", render: (r) => r.substitution_note ? <span className="text-warn" title={r.substitution_note}>⚠ note</span> : "" },
        ]} />
      </Panel>
      <MarketDrawer id={openId} onClose={() => setOpenId(null)} />
    </div>
  );
}

function MarketDrawer({ id, onClose }: { id: number | null; onClose: () => void }) {
  const [d, setD] = useState<any>(null);
  const [obs, setObs] = useState<any[]>([]);
  useEffect(() => {
    if (!id) return;
    setD(null); setObs([]);
    api(`/api/markets/${id}`).then(setD);
    api(`/api/markets/${id}/observations`).then(setObs);
  }, [id]);
  const m = d?.market;
  return (
    <Drawer open={!!id} onClose={onClose} title={m?.slug || "Market"} wide>
      {!m ? <div className="text-faint">Loading…</div> : (
        <div className="space-y-4">
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <Panel title="Identification">
              <KV rows={[["Asset", m.asset], ["Question", m.question], ["Gamma event / market", `${m.gamma_event_id} / ${m.gamma_market_id}`],
                ["Condition id", m.condition_id], ["UP token", m.up_token_id], ["DOWN token", m.down_token_id],
                ["Opens", ts(m.open_ts)], ["Settles", ts(m.close_ts)], ["Status", m.status], ["Restricted flag", String(m.restricted)],
                ["Substitution note", m.substitution_note || "none"]]} />
            </Panel>
            <Panel title="Settlement">
              <KV rows={[["Resolution source", m.resolution_source], ["Methodology", m.settlement_method], ["TWAP lookback", m.twap_lookback_s ? `${m.twap_lookback_s}s` : "—"],
                ["Opening reference", `${spot(m.open_price)} (${m.open_price_source || "pending"})`], ["Final reference", spot(m.close_price)],
                ["Official winner", m.winner || "pending"], ["Resolution status", d.resolution?.status || "pending"],
                ["Sources agree", d.resolution?.sources_agree == null ? "—" : String(d.resolution.sources_agree)],
                ["Fee schedule", `${m.fee_type} rate=${m.fee_rate} exp=${m.fee_exponent} takerOnly=${m.fee_taker_only} ${m.fee_verified ? "(verified)" : "(ESTIMATED)"}`],
                ["Tick / min size", `${m.tick_size} / ${m.min_order_size} shares`]]} />
            </Panel>
          </div>
          <Panel title="Price history (recorded, 1s)">
            <TimeChart title={m.slug} series={[
              { name: "UP mid", color: "#22c55e", data: obs.map((o) => ({ time: o.server_ts, value: o.up_mid })) },
              { name: "DOWN mid", color: "#ef4444", data: obs.map((o) => ({ time: o.server_ts, value: o.down_mid })) },
              { name: "spot", color: "#38bdf8", priceScale: "left", width: 1, data: obs.map((o) => ({ time: o.server_ts, value: o.spot })) },
              { name: "open ref", color: "#f59e0b", priceScale: "left", dashed: true, width: 1, data: obs.map((o) => ({ time: o.server_ts, value: o.open_price })) },
            ]} leftLabel="underlying" rightLabel="outcome price" />
          </Panel>
          <Panel title="Checkpoints (T-minus)">
            <DataTable exportName={`checkpoints_${m.slug}`} rows={d.checkpoints} cols={[
              { key: "t_minus", label: "T-", render: (r) => `T-${r.t_minus}` },
              { key: "favourite", label: "Fav", align: "center" },
              { key: "fav_prob", label: "Fav prob", render: (r) => pct(r.fav_prob, 2) },
              { key: "dog_ask", label: "Dog ask", render: (r) => price(r.dog_ask) },
              { key: "dog_ask_liq", label: "Dog liq $", render: (r) => r.dog_ask_liq?.toFixed(2) ?? "—" },
              { key: "dist_bps", label: "Dist bp", render: (r) => r.dist_bps?.toFixed(2) ?? "—" },
              { key: "valid", label: "Valid", align: "center", render: (r) => r.valid ? "✓" : <span className="text-warn" title={r.invalid_reason}>✗</span> },
              { key: "favourite_lost", label: "Prob. rev.", align: "center", render: (r) => r.favourite_lost == null ? "—" : r.favourite_lost ? <span className="text-warn">YES</span> : "no" },
              { key: "price_crossover_after", label: "Crossover", align: "center", render: (r) => r.price_crossover_after == null ? "—" : r.price_crossover_after ? "yes" : "no" },
              { key: "underlying_reversal", label: "Underl. rev.", align: "center", render: (r) => r.underlying_reversal == null ? "—" : r.underlying_reversal ? "yes" : "no" },
              { key: "settlement_reversal", label: "Settle rev.", align: "center", render: (r) => r.settlement_reversal == null ? "—" : r.settlement_reversal ? "yes" : "no" },
            ]} />
          </Panel>
        </div>
      )}
    </Drawer>
  );
}

export default function MarketsPage() {
  return <Suspense><MarketsInner /></Suspense>;
}
