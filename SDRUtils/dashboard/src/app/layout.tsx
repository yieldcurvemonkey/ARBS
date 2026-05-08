// ABOUTME: Root layout configuring app-wide fonts and metadata for the dashboard.
import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";
import { SwrProvider } from "./SwrProvider";

export const metadata: Metadata = {
  title: "yieldcurvemonkey's jungle",
  description: "USD rates analytics dashboards",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className="antialiased">
        <SwrProvider>
        <div className="min-h-screen bg-slate-950 text-slate-100">
          <header className="border-b border-slate-800 bg-slate-900/70 backdrop-blur">
            <div className="mx-auto flex max-w-[120rem] flex-wrap items-center justify-between gap-x-4 gap-y-1 px-4 py-3 sm:py-4">
              <Link href="/" className="hidden text-lg font-semibold tracking-tight min-[400px]:inline">
                yieldcurvemonkey&apos;s jungle
              </Link>
              <Link href="/" className="text-lg font-semibold tracking-tight min-[400px]:hidden">
                ycm
              </Link>
              <nav className="flex items-center gap-3 text-xs text-slate-300 sm:gap-6 sm:text-sm">
                <Link href="/usd-swaps" className="hover:text-white">
                  Swaps
                  <span className="hidden sm:inline"> Tape</span>
                </Link>
                <Link
                  href="/usd-rates-vol-analytics/vol-tape"
                  className="hover:text-white"
                >
                  Vol
                  <span className="hidden sm:inline"> Tape</span>
                </Link>
              </nav>
            </div>
          </header>
          <main className="mx-auto max-w-[120rem] px-4 py-6">
            {children}
          </main>
        </div>
        </SwrProvider>
      </body>
    </html>
  );
}
