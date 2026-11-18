import type { Config } from "tailwindcss";

const v = (name: string) => `rgb(var(--${name}) / <alpha-value>)`;

const config: Config = {
  darkMode: "class",
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: v("bg"),
        panel: v("panel"),
        panel2: v("panel2"),
        line: v("line"),
        line2: v("line2"),
        ink: v("ink"),
        dim: v("dim"),
        faint: v("faint"),
        up: v("up"),
        down: v("down"),
        warn: v("warn"),
        info: v("info"),
        accent: v("accent"),
        cash: v("cash"),
        oncash: v("oncash"),
      },
      fontFamily: {
        mono: ["var(--font-mono)", "ui-monospace", "Consolas", "monospace"],
        sans: ["var(--font-sans)", "ui-sans-serif", "system-ui", "sans-serif"],
      },
      fontSize: { "2xs": ["11px", "15px"] },
      borderRadius: { "4xl": "2rem" },
      transitionTimingFunction: { apple: "cubic-bezier(.32,.72,0,1)" },
      keyframes: {
        rise: { "0%": { opacity: "0", transform: "translateY(8px)" }, "100%": { opacity: "1", transform: "none" } },
        fade: { "0%": { opacity: "0" }, "100%": { opacity: "1" } },
        sheet: { "0%": { transform: "translateY(100%)" }, "100%": { transform: "none" } },
        pop: { "0%": { transform: "scale(.96)", opacity: "0" }, "100%": { transform: "none", opacity: "1" } },
        page: { "0%": { opacity: "0", transform: "translateY(10px) scale(.995)" }, "100%": { opacity: "1", transform: "none" } },
      },
      animation: {
        rise: "rise .5s cubic-bezier(.32,.72,0,1) both",
        fade: "fade .3s ease both",
        sheet: "sheet .5s cubic-bezier(.32,.72,0,1) both",
        pop: "pop .35s cubic-bezier(.32,.72,0,1) both",
        page: "page .45s cubic-bezier(.32,.72,0,1) both",
      },
    },
  },
  plugins: [],
};
export default config;
