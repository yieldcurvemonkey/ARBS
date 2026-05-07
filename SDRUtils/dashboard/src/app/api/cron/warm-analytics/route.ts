import { NextResponse } from 'next/server'

const TOP_LABELS = [
  'USD-SOFR-COMPOUND 1D Constant Spot 10Y Outright PHYS',
  'USD-SOFR-COMPOUND 1D Constant Spot 5Y Outright PHYS',
  'USD-SOFR-OIS Compound 1D Constant Spot 10Y Spreadover PHYS',
  'USD-SOFR-OIS Compound 1D Constant Spot 5Y Spreadover PHYS',
  'USD-SOFR-COMPOUND 1D Constant Spot 2Y Outright PHYS',
  'USD-SOFR-COMPOUND 1D Constant Spot 30Y Outright PHYS',
  'USD-SOFR-COMPOUND 1D Constant Spot 1Y Outright PHYS',
  'USD-SOFR-COMPOUND 1D Constant Spot 3Y Outright PHYS',
  'USD-SOFR-OIS Compound 1D Constant Spot 10Y Outright PHYS',
  'USD-SOFR-OIS Compound 1D Constant Spot 30Y Spreadover PHYS',
  'USD-SOFR-COMPOUND 1D Constant Spot 7Y Outright PHYS',
  'USD-SOFR-COMPOUND 1D Constant Spot 4Y Outright PHYS',
  'USD-SOFR-OIS Compound 1D Constant Spot 5Y Outright PHYS',
  'USD-SOFR-OIS Compound 1D Constant Spot 10Y/30Y CURVE PHYS',
  'USD-SOFR-COMPOUND 1D Constant Spot 20Y Outright PHYS',
  'USD-SOFR-OIS Compound 1D Constant Spot 5Y/10Y CURVE PHYS',
  'USD-SOFR-COMPOUND 1D Constant Spot 6Y Outright PHYS',
  'USD-SOFR-COMPOUND 1D Constant Spot 6M Outright PHYS',
]

const ROUTES = ['analytics-timeseries', 'rarity', 'extremes'] as const

export const maxDuration = 300

export async function GET(request: Request) {
  const authHeader = request.headers.get('authorization')
  const cronSecret = process.env.CRON_SECRET
  if (cronSecret && authHeader !== `Bearer ${cronSecret}`) {
    return NextResponse.json({ error: 'unauthorized' }, { status: 401 })
  }

  const baseUrl = new URL(request.url).origin
  const results: Array<{ label: string; route: string; status: number; ms: number }> = []
  const errors: string[] = []

  for (const label of TOP_LABELS) {
    for (const route of ROUTES) {
      const params = new URLSearchParams({
        value: label,
        groupBy: 'tape_label',
        range: '1Y',
        ...(route === 'analytics-timeseries' ? { view: 'DAILY_CLOSE' } : {}),
        ...(route === 'rarity' ? { lookback: '90', binMetric: 'fixed_rate' } : {}),
      })
      const url = `${baseUrl}/api/usd-swaps-tape-v2/${route}?${params}`
      const start = performance.now()
      try {
        const res = await fetch(url)
        results.push({
          label: label.slice(-30),
          route,
          status: res.status,
          ms: Math.round(performance.now() - start),
        })
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e)
        errors.push(`${route}/${label.slice(-30)}: ${msg}`)
        results.push({
          label: label.slice(-30),
          route,
          status: 0,
          ms: Math.round(performance.now() - start),
        })
      }
    }
  }

  return NextResponse.json({
    warmed: results.filter((r) => r.status === 200).length,
    total: results.length,
    errors,
    results,
  })
}
