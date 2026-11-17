"use client";
import clsx from "clsx";
import { ArrowRight, Lock } from "lucide-react";
import { useState } from "react";

export default function Login() {
  const [pw, setPw] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [shake, setShake] = useState(false);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true); setErr(null);
    try {
      const r = await fetch("/api/auth/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ password: pw }) });
      const j = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(j.detail || "Login failed");
      location.href = "/";
    } catch (e: any) {
      setErr(e.message); setShake(true); setTimeout(() => setShake(false), 450);
    } finally { setBusy(false); }
  };
  return (
    <div className="safe-top flex min-h-screen flex-col items-center justify-center bg-bg px-6">
      <form onSubmit={submit} className="w-full max-w-[380px] animate-rise">
        <div className="mx-auto mb-6 flex h-20 w-20 items-center justify-center rounded-[26px] bg-cash text-[44px] font-black text-oncash shadow-[0_10px_40px_rgba(0,214,75,.35)]">$</div>
        <h1 className="text-center text-[34px] font-bold tracking-tight">Reversal</h1>
        <p className="mb-8 mt-1 text-center text-[15px] text-dim">Enter your password to continue</p>
        <div className={clsx("flex items-center gap-3 rounded-full bg-panel px-5 py-4 transition", shake && "animate-[pop_.4s]", err && "ring-2 ring-down/50")}>
          <Lock size={18} className="text-faint" />
          <input type="password" autoFocus value={pw} onChange={(e) => setPw(e.target.value)} placeholder="Password" autoComplete="current-password"
            className="min-w-0 flex-1 bg-transparent text-[17px] outline-none placeholder:text-faint" />
        </div>
        {err && <div className="mt-3 text-center text-[14px] text-down">{err}</div>}
        <button disabled={busy || !pw} className="mt-5 flex w-full items-center justify-center gap-2 rounded-full bg-cash py-4 text-[17px] font-bold text-oncash transition active:scale-[.98] disabled:opacity-50">
          {busy ? "Checking…" : <>Log in <ArrowRight size={18} /></>}
        </button>
      </form>
    </div>
  );
}
