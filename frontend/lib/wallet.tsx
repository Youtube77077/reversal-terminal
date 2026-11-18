"use client";
import { createContext, useContext, useEffect, useState } from "react";
import { usePoll } from "./api";

type Ctx = { wallets: any[]; wallet: any | null; select: (id: number) => void; reload: () => void };
const C = createContext<Ctx>({ wallets: [], wallet: null, select: () => {}, reload: () => {} });

export function WalletProvider({ children }: { children: React.ReactNode }) {
  const { data, reload } = usePoll<any[]>("/api/wallets", 5000);
  const [sel, setSel] = useState<number | null>(null);
  useEffect(() => { try { const v = localStorage.getItem("rt_wallet"); if (v) setSel(Number(v)); } catch {} }, []);
  const wallets = data || [];
  const wallet = wallets.find((w) => w.id === sel) || wallets.find((w) => w.is_main) || wallets[0] || null;
  const select = (id: number) => { setSel(id); try { localStorage.setItem("rt_wallet", String(id)); } catch {} };
  return <C.Provider value={{ wallets, wallet, select, reload }}>{children}</C.Provider>;
}

export const useWallet = () => useContext(C);
export const walletBalance = (w: any) => (w?.paper ? w.paper.cash + w.paper.reserved : 0);
