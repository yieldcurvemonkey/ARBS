// ABOUTME: Root layout configuring app-wide fonts and metadata for the Swaption trade tape.
import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "Swaption Trade Tape",
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
                Swaption Tape
              </Link>
              <nav className="flex items-center gap-4 text-sm text-slate-300">
                <Link href="/" className="hover:text-white">
                  Home
                </Link>
                <Link href="/swaptions-tape" className="hover:text-white">
                  Tape
                </Link>
                <Link href="/vol-grid" className="hover:text-white">
                  Vol Grid
                </Link>
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
