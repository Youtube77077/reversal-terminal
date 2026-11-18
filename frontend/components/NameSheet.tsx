"use client";
import { useEffect, useState } from "react";
import { Button, Drawer, ErrorNote, inputCls } from "@/components/ui";

/** In-app text input (window.prompt doesn't work inside the iPhone app). */
export default function NameSheet({ open, title, initial, cta, onClose, onSave }: {
  open: boolean; title: string; initial: string; cta: string; onClose: () => void; onSave: (name: string) => Promise<any>;
}) {
  const [v, setV] = useState(initial);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (open) { setV(initial); setErr(null); } }, [open, initial]);
  const save = async () => {
    const n = v.trim();
    if (!n) return setErr("Type a name");
    setBusy(true); setErr(null);
    try { await onSave(n); onClose(); } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  };
  return (
    <Drawer open={open} onClose={onClose} title={title}>
      <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); save(); }}>
        <input autoFocus maxLength={40} className={inputCls + " py-3 text-[18px]"} value={v} onChange={(e) => setV(e.target.value)} placeholder="Wallet name" />
        <ErrorNote error={err} />
        <Button type="submit" tone="primary" size="lg" disabled={busy} className="w-full">{cta}</Button>
      </form>
    </Drawer>
  );
}
