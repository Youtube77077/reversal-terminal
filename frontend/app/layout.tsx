import type { Metadata, Viewport } from "next";
import Chrome from "@/components/Chrome";
import { LiveProvider } from "@/lib/live";
import { ThemeProvider } from "@/lib/theme";
import { WalletProvider } from "@/lib/wallet";
import "./globals.css";

export const metadata: Metadata = {
  title: "Reversal",
  description: "Crypto 5-minute prediction-market reversal bot",
  appleWebApp: { capable: true, statusBarStyle: "black-translucent", title: "Reversal" },
  icons: { icon: "/icon.svg", apple: "/apple-touch-icon.png" },
  manifest: "/manifest.webmanifest",
};

export const viewport: Viewport = {
  width: "device-width", initialScale: 1, maximumScale: 1, userScalable: false, viewportFit: "cover",
  themeColor: "#000000",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html:
          "try{var t=localStorage.getItem('rt_theme')||(matchMedia('(prefers-color-scheme: light)').matches?'light':'dark');document.documentElement.className=t}catch(e){}" }} />
      </head>
      <body className="min-h-screen bg-bg antialiased">
        <ThemeProvider>
          <LiveProvider>
            <WalletProvider><Chrome>{children}</Chrome></WalletProvider>
          </LiveProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
