"use client";
import clsx from "clsx";
import { Delete } from "lucide-react";
import { useEffect, useState } from "react";

const PIN_LEN = 4;

export default function Login() {
  const [pin, setPin] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [shake, setShake] = useState(false);

  const submit = async (code: string) => {
    setBusy(true); setErr(null);
    try {
      const r = await fetch("/api/auth/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ password: code }) });
      const j = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(j.detail || "Wrong PIN");
      location.href = "/";
    } catch (e: any) {
      setErr(e.message); setShake(true); setPin("");
      setTimeout(() => setShake(false), 450);
      (window as any).ReversalNative?.haptic("heavy");
    } finally { setBusy(false); }
  };

  const press = (k: string) => {
    if (busy) return;
    setErr(null);
    if (k === "<") return setPin((p) => p.slice(0, -1));
    setPin((p) => {
      const n = (p + k).slice(0, 12);
      if (n.length === PIN_LEN) setTimeout(() => submit(n), 120);
      return n;
    });
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (/^[0-9]$/.test(e.key)) press(e.key);
      else if (e.key === "Backspace") press("<");
      else if (e.key === "Enter" && pin.length) submit(pin);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  return (
    <div className="safe-top flex min-h-screen flex-col items-center justify-center bg-bg px-6">
      <div className="w-full max-w-[340px] animate-rise">
        <div className="mx-auto mb-5 flex h-16 w-16 items-center justify-center rounded-[22px] bg-cash text-[36px] font-black text-oncash shadow-[0_10px_40px_rgba(0,214,75,.35)]">$</div>
        <h1 className="text-center text-[28px] font-bold tracking-tight">Enter PIN</h1>
        <p className="mt-1 text-center text-[14px] text-dim">Reversal</p>
        <div className={clsx("mx-auto mt-8 flex justify-center gap-4", shake && "animate-[pop_.4s]")}>
          {Array.from({ length: Math.max(PIN_LEN, pin.length) }).map((_, i) => (
            <span key={i} className={clsx("h-4 w-4 rounded-full transition-all duration-150",
              i < pin.length ? "scale-110 bg-ink" : "bg-panel2", err && "bg-down")} />
          ))}
        </div>
        <div className="mt-3 h-5 text-center text-[13px] text-down">{err}</div>
        <div className="mt-4 grid grid-cols-3 gap-4">
          {["1", "2", "3", "4", "5", "6", "7", "8", "9", "", "0", "<"].map((k, i) => k === "" ? <span key={i} /> : (
            <button key={i} onClick={() => press(k)} disabled={busy}
              className={clsx("mx-auto flex h-[74px] w-[74px] items-center justify-center rounded-full text-[30px] font-semibold transition active:scale-90",
                k === "<" ? "text-dim" : "bg-panel active:bg-panel2")}>
              {k === "<" ? <Delete size={26} /> : k}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
