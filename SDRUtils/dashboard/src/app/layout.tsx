// ABOUTME: Root layout configuring app-wide fonts and metadata for the Swaption trade tape.
import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "yieldcurvemonkey's jungle",
  description: "USD Swaptions SDR trade tape",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className="antialiased">
        <div className="min-h-screen bg-slate-950 text-slate-100">
          <header className="border-b border-slate-800 bg-slate-900/70 backdrop-blur">
            <div className="mx-auto flex max-w-[120rem] items-center justify-between px-4 py-4">
              <Link href="/" className="text-lg font-semibold tracking-tight">
                yieldcurvemonkey&apos;s jungle
              </Link>
              <nav className="flex items-center gap-4 text-sm text-slate-300">
                <Link href="/" className="hover:text-white">
                  Home
                </Link>
                <Link href="/swaptions-tape" className="hover:text-white">
                  USD Swaption Tape
                </Link>
                <Link href="/usd-swaps" className="hover:text-white">
                  USD Swaps Tape
                </Link>
                <div className="group relative">
                  <Link
                    href="/usd-rates-vol-analytics"
                    className="inline-flex items-center gap-1 hover:text-white"
                  >
                    USD Rates Vol Analytics
                    <span className="text-[10px] text-slate-500 transition group-hover:text-slate-300">
                      v
                    </span>
                  </Link>
                  <div className="pointer-events-none absolute left-0 top-full z-40 pt-2 opacity-0 transition duration-150 group-hover:pointer-events-auto group-hover:opacity-100 group-focus-within:pointer-events-auto group-focus-within:opacity-100">
                    <div className="min-w-[14rem] rounded-xl border border-slate-800 bg-slate-950/95 p-2 shadow-2xl backdrop-blur">
                      <Link
                        href="/usd-rates-vol-analytics"
                        className="block rounded-lg px-3 py-2 text-xs font-semibold uppercase tracking-[0.18em] text-slate-400 transition hover:bg-slate-900 hover:text-white"
                      >
                        Overview
                      </Link>
                      <Link
                        href="/usd-rates-vol-analytics/atmf-vol-grid"
                        className="mt-1 block rounded-lg px-3 py-2 text-sm font-semibold text-slate-200 transition hover:bg-slate-900 hover:text-white"
                      >
                        Live ATMF Vol Grid
                      </Link>
                      <Link
                        href="/usd-rates-vol-analytics/atmf-grid-volatility-surface"
                        className="mt-1 block rounded-lg px-3 py-2 text-sm font-semibold text-slate-200 transition hover:bg-slate-900 hover:text-white"
                      >
                        Vol Plotter
                      </Link>
                    </div>
                  </div>
                </div>
                <Link href="/usts-rv" className="hover:text-white">
                  UST RV
                </Link>
                <span className="text-slate-500">
                  More coming soon
                </span>
              </nav>
            </div>
          </header>
          <main className="mx-auto max-w-[120rem] px-4 py-6">
            {children}
          </main>
        </div>
      </body>
    </html>
  );
}
