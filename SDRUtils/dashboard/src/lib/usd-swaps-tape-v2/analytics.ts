// Server-side helpers shared by the analytics dock API routes.
// Platform classification (custy vs IDB), distribution stats, and the
// SQL expression that splits leg rows into the two platforms off the
// venue column. Kept close to the DB layer so routes stay declarative.

// Platform classification for the analytics dock (IDB vs CUSTY).
//
// The SDR feed exposes two signals:
//   - `venue`: coarse D2D / D2C tag ("dealer-to-dealer" / "dealer-to-client")
//   - `platform_identifier`: MIC-style code (BGCD/ISWV/TPSE = IDB,
//     BILT/BBSF/TWSF/XOFF/XXXX = custy)
//
// D2D maps cleanly to IDB. Anything else (D2C or null) we call custy.
// The MIC code is kept as a fallback so the logic still works if a
// future feed drops the venue column.
export const IDB_MIC_SET = ['BGCD', 'ISWV', 'TPSE'] as const

export function platformCaseSql(alias: string): string {
  const micLikes = IDB_MIC_SET
    .map((mic) => `UPPER(COALESCE(${alias}.platform_identifier, '')) = '${mic}'`)
    .join(' OR ')
  return `CASE
    WHEN UPPER(COALESCE(${alias}.venue, '')) = 'D2D' THEN 'IDB'
    WHEN ${micLikes} THEN 'IDB'
    ELSE 'CUSTY'
  END`
}

export function rangeToStartDate(range: string | null | undefined): Date {
  const now = new Date()
  const d = new Date(now)
  switch (range) {
    case '1D':
      d.setUTCDate(now.getUTCDate() - 1); return d
    case '1W':
      d.setUTCDate(now.getUTCDate() - 7); return d
    case '1M':
      d.setUTCMonth(now.getUTCMonth() - 1); return d
    case '3M':
      d.setUTCMonth(now.getUTCMonth() - 3); return d
    case '6M':
      d.setUTCMonth(now.getUTCMonth() - 6); return d
    case '1Y':
    case 'CUSTOM':
    default:
      d.setUTCFullYear(now.getUTCFullYear() - 1); return d
  }
}

// JS percentile — linear interpolation.
export function percentile(sorted: number[], p: number): number {
  if (sorted.length === 0) return 0
  if (sorted.length === 1) return sorted[0]
  const idx = (sorted.length - 1) * (p / 100)
  const lo = Math.floor(idx)
  const hi = Math.ceil(idx)
  if (lo === hi) return sorted[lo]
  return sorted[lo] * (hi - idx) + sorted[hi] * (idx - lo)
}

export type DistStats = {
  count: number
  mean: number
  stddev: number
  median: number
  p5: number
  p25: number
  p75: number
  p95: number
  iqr: number
  min: number
  max: number
}

export function distributionStats(values: number[]): DistStats {
  const sorted = [...values].filter((v) => Number.isFinite(v)).sort((a, b) => a - b)
  if (sorted.length === 0) {
    return { count: 0, mean: 0, stddev: 0, median: 0, p5: 0, p25: 0, p75: 0, p95: 0, iqr: 0, min: 0, max: 0 }
  }
  const mean = sorted.reduce((a, b) => a + b, 0) / sorted.length
  const variance = sorted.reduce((s, x) => s + (x - mean) ** 2, 0) / sorted.length
  const stddev = Math.sqrt(variance)
  const p5 = percentile(sorted, 5)
  const p25 = percentile(sorted, 25)
  const p50 = percentile(sorted, 50)
  const p75 = percentile(sorted, 75)
  const p95 = percentile(sorted, 95)
  return {
    count: sorted.length,
    mean, stddev,
    median: p50, p5, p25, p75, p95,
    iqr: p75 - p25,
    min: sorted[0], max: sorted[sorted.length - 1],
  }
}

export function percentileRank(value: number, sorted: number[]): number {
  if (sorted.length === 0) return 50
  if (value <= sorted[0]) return 0
  if (value >= sorted[sorted.length - 1]) return 100
  let lo = 0, hi = sorted.length - 1
  while (lo <= hi) {
    const mid = (lo + hi) >> 1
    if (sorted[mid] < value) lo = mid + 1
    else if (sorted[mid] > value) hi = mid - 1
    else return (mid / (sorted.length - 1)) * 100
  }
  return (lo / (sorted.length - 1)) * 100
}

// Fixed rate lives in the DB as a decimal (0.03842) and renders in the
// analytics surface as basis points (384.2). One source-of-truth shim.
export function rateToBps(decimal: number | null | undefined): number {
  if (decimal == null || Number.isNaN(decimal)) return 0
  return +(Number(decimal) * 10_000).toFixed(2)
}

export function safeNum(n: unknown): number {
  const v = Number(n)
  return Number.isFinite(v) ? v : 0
}

export function rarityZone(p: number): 'typical' | 'notable' | 'rare' | 'extreme' {
  const d = Math.abs(p - 50)
  if (d <= 25) return 'typical'
  if (d <= 40) return 'notable'
  if (d <= 47) return 'rare'
  return 'extreme'
}

export function rarityDescriptor(p: number): string {
  const d = Math.abs(p - 50)
  if (d <= 25) return 'in the middle band'
  if (d <= 40) return p > 50 ? 'above typical range' : 'below typical range'
  if (d <= 47) return p > 50 ? 'rarely seen this high' : 'rarely seen this low'
  return p > 50 ? 'extreme high print' : 'extreme low print'
}
