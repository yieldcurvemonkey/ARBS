// ABOUTME: Bloomberg-ticker-style daily VWAP for USD swap-spread and
// outright OIS series (design-doc §5.6 + §5.15 + Clarus's "Swapalypse
// Now" / "Swap Spreads into Q4 2024"). Maps SPREADOVER + SOFR-OIS rows
// to canonical tickers (USSFCT2/5/10/30 for swap spreads, USSO5/10/30
// for outrights) so the AnalyticsPanel SwapSpreadVwapCard can render a
// VWAP line + scatter overlay per ticker without a backend join.

import type { UsdSwapTapeRow } from '../types'

export type SwapSpreadTickerSpec = {
  ticker: string
  /** Tenor in years that the ticker references (matched on row.tenor_years). */
  tenorYears: number
  /** Trade-type predicate. */
  packageType: 'SPREADOVER' | 'OUTRIGHT'
  /** Required canonical underlier key (SOFR-OIS for both spreads + OIS). */
  canonicalKey: string
  /** Display label. */
  label: string
}

export const SWAP_SPREAD_TICKERS: readonly SwapSpreadTickerSpec[] = [
  {
    ticker: 'USSFCT2',
    tenorYears: 2,
    packageType: 'SPREADOVER',
    canonicalKey: 'USD/SOFR-OIS/COMPOUND',
    label: 'USD swap spread 2Y',
  },
  {
    ticker: 'USSFCT5',
    tenorYears: 5,
    packageType: 'SPREADOVER',
    canonicalKey: 'USD/SOFR-OIS/COMPOUND',
    label: 'USD swap spread 5Y',
  },
  {
    ticker: 'USSFCT10',
    tenorYears: 10,
    packageType: 'SPREADOVER',
    canonicalKey: 'USD/SOFR-OIS/COMPOUND',
    label: 'USD swap spread 10Y',
  },
  {
    ticker: 'USSFCT30',
    tenorYears: 30,
    packageType: 'SPREADOVER',
    canonicalKey: 'USD/SOFR-OIS/COMPOUND',
    label: 'USD swap spread 30Y',
  },
] as const

export const USD_OIS_TICKERS: readonly SwapSpreadTickerSpec[] = [
  {
    ticker: 'USSO5',
    tenorYears: 5,
    packageType: 'OUTRIGHT',
    canonicalKey: 'USD/SOFR-OIS/COMPOUND',
    label: 'USD SOFR OIS 5Y',
  },
  {
    ticker: 'USSO10',
    tenorYears: 10,
    packageType: 'OUTRIGHT',
    canonicalKey: 'USD/SOFR-OIS/COMPOUND',
    label: 'USD SOFR OIS 10Y',
  },
  {
    ticker: 'USSO30',
    tenorYears: 30,
    packageType: 'OUTRIGHT',
    canonicalKey: 'USD/SOFR-OIS/COMPOUND',
    label: 'USD SOFR OIS 30Y',
  },
] as const

export const ALL_TICKERS: readonly SwapSpreadTickerSpec[] = [
  ...SWAP_SPREAD_TICKERS,
  ...USD_OIS_TICKERS,
]

const TENOR_TOLERANCE = 0.5

function rowCanonicalKey(row: UsdSwapTapeRow): string | null {
  if (typeof row.canonical_underlier_key === 'string' && row.canonical_underlier_key) {
    return row.canonical_underlier_key
  }
  return row.legs_json?.[0]?.canonical_underlier_key ?? null
}

function rowTenorYears(row: UsdSwapTapeRow): number | null {
  const fromLeg = row.legs_json?.[0]?.tenor_years
  if (typeof fromLeg === 'number' && Number.isFinite(fromLeg)) return fromLeg
  return null
}

function rowFixedRate(row: UsdSwapTapeRow): number | null {
  if (typeof row.weighted_fixed_rate === 'number') return row.weighted_fixed_rate
  const leg = row.legs_json?.[0]
  if (leg && typeof leg.fixed_rate === 'number') return leg.fixed_rate
  return null
}

function rowAbsRisk(row: UsdSwapTapeRow): number {
  const v = Number(row.total_risk ?? row.legs_json?.[0]?.risk ?? 0)
  return Number.isFinite(v) ? Math.abs(v) : 0
}

function rowAbsNotional(row: UsdSwapTapeRow): number {
  const v = Number(row.total_notional ?? 0)
  return Number.isFinite(v) ? Math.abs(v) : 0
}

export function resolveSwapSpreadTicker(row: UsdSwapTapeRow): string | null {
  const tenor = rowTenorYears(row)
  if (tenor == null) return null
  const canonical = rowCanonicalKey(row)
  if (!canonical) return null
  const packageType = String(row.package_type ?? '').toUpperCase()
  for (const spec of ALL_TICKERS) {
    if (spec.canonicalKey !== canonical) continue
    if (spec.packageType !== packageType) continue
    if (Math.abs(spec.tenorYears - tenor) > TENOR_TOLERANCE) continue
    return spec.ticker
  }
  return null
}

export type DailyVwapPoint = {
  /** ISO date "YYYY-MM-DD". */
  day: string
  /** Volume-weighted average rate, expressed in bps. */
  vwapBps: number
  /** Total |risk| across prints in the day. */
  totalRisk: number
  /** Total |notional| across prints in the day. */
  totalNotional: number
  /** Number of contributing prints. */
  tradeCount: number
}

function dayBucket(timestamp: string | null | undefined): string | null {
  if (!timestamp) return null
  const ms = Date.parse(timestamp)
  if (!Number.isFinite(ms)) return null
  return new Date(ms).toISOString().slice(0, 10)
}

export function computeDailyVwap(
  rows: readonly UsdSwapTapeRow[],
  ticker: string,
): DailyVwapPoint[] {
  const map = new Map<
    string,
    {
      weightedRateSum: number
      weightSum: number
      // Fallback even-weighted accumulators when no risk is reported
      // (e.g. early Phase 4 rows where the materialiser hasn't filled
      // legs_json[0].risk yet). Tracked separately so a single missing
      // risk doesn't poison the whole day's VWAP.
      evenRateSum: number
      evenCount: number
      totalRisk: number
      totalNotional: number
    }
  >()
  for (const row of rows) {
    if (resolveSwapSpreadTicker(row) !== ticker) continue
    const fixedRate = rowFixedRate(row)
    if (fixedRate == null || !Number.isFinite(fixedRate)) continue
    const day = dayBucket(row.execution_start)
    if (!day) continue
    const risk = rowAbsRisk(row)
    const notional = rowAbsNotional(row)
    const cur = map.get(day) ?? {
      weightedRateSum: 0,
      weightSum: 0,
      evenRateSum: 0,
      evenCount: 0,
      totalRisk: 0,
      totalNotional: 0,
    }
    cur.evenRateSum += fixedRate
    cur.evenCount += 1
    if (risk > 0) {
      cur.weightedRateSum += fixedRate * risk
      cur.weightSum += risk
    }
    cur.totalRisk += risk
    cur.totalNotional += notional
    map.set(day, cur)
  }
  const out: DailyVwapPoint[] = []
  for (const [day, agg] of map.entries()) {
    const vwap =
      agg.weightSum > 0
        ? agg.weightedRateSum / agg.weightSum
        : agg.evenCount > 0
          ? agg.evenRateSum / agg.evenCount
          : Number.NaN
    if (!Number.isFinite(vwap)) continue
    out.push({
      day,
      // Rates persist as decimals (0.035 = 3.5% = 350 bps); the
      // analytics dock surfaces them in bps to match Clarus convention.
      vwapBps: vwap * 10_000,
      totalRisk: agg.totalRisk,
      totalNotional: agg.totalNotional,
      tradeCount: agg.evenCount,
    })
  }
  out.sort((a, b) => a.day.localeCompare(b.day))
  return out
}
