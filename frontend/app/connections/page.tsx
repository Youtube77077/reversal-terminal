"use client";
import { useState } from "react";
import { Button, DataTable, ErrorNote, KV, Panel, Pill, statusKind } from "@/components/ui";
import { post, usePoll } from "@/lib/api";
import { ago, int } from "@/lib/format";

export default function Connections() {
  const { data, error, reload } = usePoll<any[]>("/api/connections", 5000);
  const [tests, setTests] = useState<Record<string, any>>({});
  const test = async (k: string) => {
    setTests((t) => ({ ...t, [k]: { pending: true } }));
    try { const r = await post(`/api/connections/${k}/test`); setTests((t) => ({ ...t, [k]: r })); reload(); }
    catch (e: any) { setTests((t) => ({ ...t, [k]: { ok: false, detail: e.message } })); }
  };
  return (
    <div className="page space-y-3">
      <ErrorNote error={error} />
      <Panel title="Data source registry" sub="Every field shown in the app comes from one of these providers. All market data is free and public — no API keys are needed for research or paper trading.">
        <DataTable rows={data || []} cols={[
          { key: "provider", label: "Provider", align: "left", render: (r) => <span className="font-medium">{r.provider}</span> },
          { key: "status", label: "Status", align: "center", render: (r) => <Pill kind={statusKind(r.status)} /> },
          { key: "base_url", label: "Base URL", align: "left", render: (r) => <span className="mono text-2xs text-dim">{r.base_url}</span> },
          { key: "auth", label: "Auth", align: "left", render: (r) => <span className="text-2xs">{r.auth}</span> },
          { key: "api_key_required", label: "Key?", align: "center", render: (r) => r.api_key_required ? <span className="text-warn">yes</span> : "no" },
          { key: "websocket", label: "WS", align: "center", render: (r) => r.websocket ? "yes" : "no" },
          { key: "last_success_ts", label: "Last success", render: (r) => ago(r.last_success_ts) },
          { key: "messages", label: "Msgs", render: (r) => int(r.messages) },
          { key: "failures", label: "Fails", render: (r) => <span className={r.failures ? "text-warn" : ""}>{int(r.failures)}</span> },
          { key: "reconnects", label: "Reconn.", render: (r) => int(r.reconnects) },
          { key: "test", label: "", align: "center", render: (r) => <Button size="sm" onClick={() => test(r.key)}>{tests[r.key]?.pending ? "…" : "Test"}</Button> },
        ]} />
      </Panel>
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        {(data || []).map((r) => (
          <Panel key={r.key} title={r.provider} right={<Pill kind={statusKind(r.status)} />}>
            <KV rows={[["Purpose", r.purpose], ["Fields supplied", r.fields_supplied], ["Rate limit", r.rate_limit],
              ["Last error", r.last_error ? `${r.last_error} (${ago(r.last_error_ts)})` : "none"],
              ["Test result", tests[r.key] ? (tests[r.key].pending ? "testing…" : `${tests[r.key].ok ? "OK" : "FAILED"} ${JSON.stringify(tests[r.key].detail)}`) : "not run"]]} />
          </Panel>
        ))}
      </div>
      <Panel title="Credentials">
        <div className="space-y-2 text-xs leading-relaxed text-dim">
          <p><b className="text-ink">No credentials are required.</b> Gamma, CLOB market data, the CLOB market websocket, Polymarket RTDS (Chainlink), the crypto-price endpoint and Binance public streams are all unauthenticated.</p>
          <p>Optional settings live in the local <span className="mono">.env</span> file (never committed; see <span className="mono">.env.example</span> and SETUP_GUIDE.md). <span className="mono">OPTIONAL_DATA_API_KEY</span> / <span className="mono">_SECRET</span> are placeholders for a future paid data vendor and are unused today.</p>
          <p className="text-warn">Polymarket trading credentials (wallet private key, L2 API key/secret/passphrase) are deliberately NOT supported: live order placement is prohibited from the Netherlands. Never paste wallet keys into chat, the browser or plain text files.</p>
        </div>
      </Panel>
    </div>
  );
}
