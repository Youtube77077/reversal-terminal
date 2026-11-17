"use client";
import { usePathname } from "next/navigation";
import Shell from "./Shell";

/** Renders the app shell everywhere except the login screen. */
export default function Chrome({ children }: { children: React.ReactNode }) {
  const p = usePathname() || "";
  if (p.startsWith("/login")) return <>{children}</>;
  return <Shell>{children}</Shell>;
}
