"use client";
import { createContext, useContext, useEffect, useState } from "react";

type Theme = "dark" | "light";
const Ctx = createContext<{ theme: Theme; toggle: () => void; set: (t: Theme) => void }>({
  theme: "dark", toggle: () => {}, set: () => {},
});

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [theme, setTheme] = useState<Theme>("dark");
  useEffect(() => {
    let t: Theme = "dark";
    try {
      const saved = localStorage.getItem("rt_theme") as Theme | null;
      t = saved || (window.matchMedia?.("(prefers-color-scheme: light)").matches ? "light" : "dark");
    } catch {}
    setTheme(t);
  }, []);
  useEffect(() => {
    const el = document.documentElement;
    el.classList.remove("dark", "light");
    el.classList.add(theme);
    document.querySelector('meta[name="theme-color"]')?.setAttribute("content", theme === "dark" ? "#000000" : "#ffffff");
    try { localStorage.setItem("rt_theme", theme); } catch {}
  }, [theme]);
  return <Ctx.Provider value={{ theme, toggle: () => setTheme((t) => (t === "dark" ? "light" : "dark")), set: setTheme }}>{children}</Ctx.Provider>;
}

export const useTheme = () => useContext(Ctx);

/** True when running inside the REVERSAL iPhone app (WKWebView adds this to the UA). */
export function isNativeApp(): boolean {
  return typeof navigator !== "undefined" && /ReversalTerminalApp/.test(navigator.userAgent);
}
