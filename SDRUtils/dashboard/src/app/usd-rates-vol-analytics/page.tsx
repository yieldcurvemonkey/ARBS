import Link from 'next/link'

const ANALYTICS_PAGES = [
  {
    href: '/usd-rates-vol-analytics/vol-tape',
    title: 'Vol Tape',
    eyebrow: 'SDR Tape',
    description:
      'Browse the USD swaption SDR vol tape with quadrant analytics, trade history, manual links, and export tooling.'
  },
  {
    href: '/usd-rates-vol-analytics/atmf-vol-grid',
    title: 'Live ATMF Vol Grid',
    eyebrow: 'Live Surface',
    description:
      'Monitor the live and closing USD swaption ATMF grid, calibration inputs, propagation metadata, and surface views.'
  },
  {
    href: '/usd-rates-vol-analytics/atmf-grid-volatility-surface',
    title: 'Vol Plotter',
    eyebrow: '3D Surface',
    description:
      'Inspect the ATMF surface on a dedicated page with the surface view, date picker, and calibration controls.'
  },
  {
    href: '/usd-rates-vol-analytics/listed-vs-otc-ustf',
    title: 'Listed vs OTC Vol (USTF)',
    eyebrow: 'USTF vs OTC',
    description:
      'Compare UST futures option ATM normal vol against matched OTC swaption ATMF vol. Timeseries, term structure, and vol smile analytics.'
  }
]

export default function UsdRatesVolAnalyticsPage() {
  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1.25fr)_minmax(20rem,0.75fr)]">
      <section className="rounded-2xl border border-slate-800 bg-slate-950/60 p-5">
        <h2 className="text-lg font-semibold text-white">Available Pages</h2>
        <p className="mt-2 text-sm text-slate-400">
          Select a volatility analytics page below. Additional USD rates vol tools can live in
          this section without adding more top-level routes.
        </p>
        <div className="mt-5 grid gap-4">
          {ANALYTICS_PAGES.map((page) => (
            <Link
              key={page.href}
              href={page.href}
              className="group rounded-2xl border border-slate-800 bg-slate-900/70 p-4 transition hover:border-sky-400/50 hover:bg-slate-900"
            >
              <div className="text-[11px] font-semibold uppercase tracking-[0.22em] text-sky-300/80">
                {page.eyebrow}
              </div>
              <div className="mt-2 text-lg font-semibold text-white group-hover:text-sky-100">
                {page.title}
              </div>
              <p className="mt-2 text-sm text-slate-400">{page.description}</p>
            </Link>
          ))}
        </div>
      </section>

      <section className="rounded-2xl border border-slate-800 bg-slate-950/60 p-5">
        <h2 className="text-lg font-semibold text-white">Route Structure</h2>
        <div className="mt-4 space-y-3 font-mono text-sm text-slate-300">
          <div className="rounded-xl border border-slate-800 bg-slate-900/50 px-3 py-2">
            `/usd-rates-vol-analytics`
          </div>
          <div className="rounded-xl border border-slate-800 bg-slate-900/50 px-3 py-2">
            `/usd-rates-vol-analytics/vol-tape`
          </div>
          <div className="rounded-xl border border-slate-800 bg-slate-900/50 px-3 py-2">
            `/usd-rates-vol-analytics/atmf-vol-grid`
          </div>
          <div className="rounded-xl border border-slate-800 bg-slate-900/50 px-3 py-2">
            `/usd-rates-vol-analytics/atmf-grid-volatility-surface`
          </div>
          <div className="rounded-xl border border-slate-800 bg-slate-900/50 px-3 py-2">
            `/usd-rates-vol-analytics/listed-vs-otc-ustf`
          </div>
        </div>
        <p className="mt-4 text-sm text-slate-500">
          Legacy `/swaptions-tape` and `/vol-grid` traffic is redirected to nested
          USD Rates Vol Analytics pages for backward compatibility.
        </p>
      </section>
    </div>
  )
}
