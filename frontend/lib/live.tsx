"use client";
import { createContext, useContext, useEffect, useRef, useState } from "react";
import { api } from "./api";

export type LiveTick = {
  type: "tick";
  ts: number;
  assets: Record<string, any>;
  asset_status: Record<string, { status: string; detail?: string | null }>;
  opportunities: any[];
  collector: { last_tick_ts: number | null; observations: number; clob_ws: boolean; rtds: boolean; binance: boolean };
  engine_paused: boolean | null;
};

type Ctx = { tick: LiveTick | null; connected: boolean; events: any[]; lastMessage: number | null };
const LiveCtx = createContext<Ctx>({ tick: null, connected: false, events: [], lastMessage: null });

function wsUrl() {
  if (process.env.NEXT_PUBLIC_WS_URL) return process.env.NEXT_PUBLIC_WS_URL;
  if (typeof window === "undefined") return "ws://127.0.0.1:8000/ws/live";
  const { protocol, hostname, host, port } = window.location;
  if (port === "3000") return `ws://${hostname}:8000/ws/live`;
  return `${protocol === "https:" ? "wss" : "ws"}://${host}/ws/live`;
}

export function LiveProvider({ children }: { children: React.ReactNode }) {
  const [tick, setTick] = useState<LiveTick | null>(null);
  const [connected, setConnected] = useState(false);
  const [events, setEvents] = useState<any[]>([]);
  const [lastMessage, setLast] = useState<number | null>(null);
  const settingsRef = useRef<any>(null);

  useEffect(() => {
    const load = () => api("/api/settings").then((s) => (settingsRef.current = s)).catch(() => {});
    load();
    const t = setInterval(load, 30000);
    return () => clearInterval(t);
  }, []);

  useEffect(() => {
    let ws: WebSocket | null = null;
    let attempt = 0;
    let closed = false;
    let timer: any;
    const connect = () => {
      ws = new WebSocket(wsUrl());
      ws.onopen = () => {
        attempt = 0;
        setConnected(true);
      };
      ws.onmessage = (m) => {
        setLast(Date.now());
        try {
          const d = JSON.parse(m.data);
          if (d.type === "tick") setTick(d);
          else if (d.type === "event") {
            setEvents((e) => [d, ...e].slice(0, 200));
            notify(d, settingsRef.current);
          }
        } catch {}
      };
      ws.onclose = () => {
        setConnected(false);
        if (closed) return;
        attempt++;
        timer = setTimeout(connect, Math.min(15000, 500 * 2 ** attempt));
      };
      ws.onerror = () => ws?.close();
    };
    connect();
    return () => {
      closed = true;
      clearTimeout(timer);
      ws?.close();
    };
  }, []);

  return <LiveCtx.Provider value={{ tick, connected, events, lastMessage }}>{children}</LiveCtx.Provider>;
}

export const useLive = () => useContext(LiveCtx);

function notify(ev: any, settings: any) {
  if (!ev.notify || typeof window === "undefined" || !("Notification" in window)) return;
  if (!settings?.notifications_enabled) return;
  if (settings?.notifications && settings.notifications[ev.category] === false) return;
  if (Notification.permission !== "granted") return;
  try {
    new Notification(`REVERSAL TERMINAL · ${ev.category.replace(/_/g, " ")}`, { body: ev.message, tag: ev.category });
  } catch {}
}
