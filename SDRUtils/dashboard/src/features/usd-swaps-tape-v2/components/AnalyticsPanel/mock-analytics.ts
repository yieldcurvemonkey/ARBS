// Deterministic mock analytics data keyed by a focused trade. Stands in
// for the not-yet-built /api/usd-swaps-tape-v2/rarity and /extremes routes
// so the dock is a functional preview — the shape it emits is the shape
// the real hooks will hand back once wired. Swap this file out for fetch
// calls without touching the UI components.
import type {
  DistributionStats,
  ExtremeRow,
  FocusedTrade,
  HistogramBin,
  MetricRow,
  RecencyBucket,
  RecentSimilarRow,
  TimeseriesPointAug,
} from './analytics-types'

// ── deterministic RNG ──────────────────────────────────────────────────
function mulberry32(seed: number) {
  return function rand() {
    let t = (seed += 0x6d2b79f5)
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

function seedFromFocused(f: FocusedTrade | null): number {
  if (!f) return 42
  let h = 0
  for (const ch of f.id) h = (h * 31 + ch.charCodeAt(0)) | 0
  return Math.abs(h) || 42
}

function gauss(rng: () => number, mu: number, sigma: number): number {
  const u = 1 - rng()
  const v = rng()
  return mu + sigma * Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v)
}

function percentile(sorted: number[], p: number): number {
  const idx = (sorted.length - 1) * (p / 100)
  const lo = Math.floor(idx), hi = Math.ceil(idx)
  if (lo === hi) return sorted[lo]
  return sorted[lo] * (hi - idx) + sorted[hi] * (idx - lo)
}

// Level mean for the timeseries / distribution generators — anchored to
// the focused trade's rate so the chart's focused reference line sits
// inside a believable distribution rather than drifting off-screen.
function anchorRate(f: FocusedTrade | null): number {
  return f ? f.fixed_rate_bps : 372
}

// ── timeseries generators ──────────────────────────────────────────────
export function generateDailyClose(
  focused: FocusedTrade | null,
  opts: { days?: number } = {},
): TimeseriesPointAug[] {
  const rng = mulberry32(seedFromFocused(focused))
  const days = opts.days ?? 365
  const out: TimeseriesPointAug[] = []
  const today = new Date()
  const anchor = anchorRate(focused)
  let level = anchor - 6
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date(today.getTime() - i * 86_400_000)
    const dow = d.getDay()
    if (dow === 0 || dow === 6) continue
    const target = anchor - 2 + Math.sin(i / 42) * 12 + (days - i) * 0.02
    level = level + (target - level) * 0.18 + gauss(rng, 0, 1.6)
    const idbClose = level + gauss(rng, 0, 0.8)
    const custyClose = level + gauss(rng, 0, 2.3)
    const close = +(idbClose).toFixed(2)
    out.push({
      ts: d.toISOString(),
      idbClose: +idbClose.toFixed(2),
      custyClose: +custyClose.toFixed(2),
      idbDv01: Math.round(8_000_000 + Math.abs(gauss(rng, 0, 2_500_000))),
      custyDv01: Math.round(4_500_000 + Math.abs(gauss(rng, 0, 2_000_000))),
      idbPrints: 120 + Math.floor(rng() * 80),
      custyPrints: 40 + Math.floor(rng() * 60),
      open: close - 0.4,
      high: close + Math.abs(gauss(rng, 0.9, 0.5)),
      low:  close - Math.abs(gauss(rng, 0.9, 0.5)),
      close,
    })
  }
  if (focused && out.length > 0) {
    // Anchor today's close onto the focused trade so the reference line /
    // pulsing dot land on the last point instead of drifting from noise.
    const last = out[out.length - 1]
    last.idbClose = +focused.fixed_rate_bps.toFixed(2)
    last.custyClose = +(focused.fixed_rate_bps + 0.9).toFixed(2)
    last.close = last.idbClose
  }
  return out
}

export function generateIntraday(focused: FocusedTrade | null): TimeseriesPointAug[] {
  const rng = mulberry32(seedFromFocused(focused) + 13)
  const out: TimeseriesPointAug[] = []
  const today = new Date()
  const anchor = anchorRate(focused)
  for (let day = 1; day >= 0; day--) {
    const base = new Date(today)
    base.setDate(base.getDate() - day)
    base.setHours(7, 0, 0, 0)
    for (let m = 0; m < 9.5 * 60; m += 3) {
      if (rng() > 0.7) continue
      const ts = new Date(base.getTime() + m * 60_000)
      const r = anchor + gauss(rng, 0, 0.9) + Math.sin(m / 60) * 0.6
      out.push({
        ts: ts.toISOString(),
        idbClose: +(r + gauss(rng, 0, 0.3)).toFixed(2),
        custyClose: +(r + gauss(rng, 0, 1.1)).toFixed(2),
      })
    }
  }
  return out
}

// ── rarity generators ─────────────────────────────────────────────────
export function generateDistribution(focused: FocusedTrade | null): {
  bins: HistogramBin[]
  stats: DistributionStats
  metricRows: MetricRow[]
} {
  const rng = mulberry32(seedFromFocused(focused) + 7)
  const anchor = anchorRate(focused)
  const custySamples: number[] = []
  const idbSamples: number[] = []
  for (let i = 0; i < 620; i++) custySamples.push(+gauss(rng, anchor - 12, 9.2).toFixed(2))
  for (let i = 0; i < 1180; i++) idbSamples.push(+gauss(rng, anchor - 12.5, 6.1).toFixed(2))
  // Outliers on the custy side to justify the "exclude comically large" toggle.
  custySamples.push(anchor + 34, anchor + 37, anchor + 33.5, anchor - 27, anchor - 30)

  const BIN_W = 1
  const BIN_MIN = Math.floor(anchor - 44)
  const BIN_MAX = Math.ceil(anchor + 26)
  const binCount = Math.round((BIN_MAX - BIN_MIN) / BIN_W)
  const rawBins: HistogramBin[] = []
  for (let i = 0; i < binCount; i++) {
    rawBins.push({
      binStart: BIN_MIN + i * BIN_W,
      binEnd: BIN_MIN + (i + 1) * BIN_W,
      mid: BIN_MIN + i * BIN_W + BIN_W / 2,
      custy: 0, idb: 0, total: 0, cumPct: 0, kdeScaled: 0,
    })
  }
  const bump = (arr: number[], key: 'custy' | 'idb') => {
    for (const v of arr) {
      const idx = Math.floor((v - BIN_MIN) / BIN_W)
      if (idx >= 0 && idx < binCount) rawBins[idx][key]++
    }
  }
  bump(custySamples, 'custy')
  bump(idbSamples, 'idb')
  const totalCount = rawBins.reduce((s, b) => s + b.custy + b.idb, 0)
  let cum = 0
  rawBins.forEach((b) => {
    b.total = b.custy + b.idb
    cum += b.total
    b.cumPct = (cum / totalCount) * 100
  })
  const all = [...custySamples, ...idbSamples]
  const bandwidth = 2.2
  rawBins.forEach((b) => {
    let sum = 0
    for (const x of all) {
      const z = (b.mid - x) / bandwidth
      sum += Math.exp(-0.5 * z * z)
    }
    const kde = sum / (all.length * bandwidth * Math.sqrt(2 * Math.PI))
    ;(b as HistogramBin & { kde: number }).kde = kde
  })
  const maxCount = Math.max(...rawBins.map((b) => b.total))
  const maxKde = Math.max(
    ...rawBins.map((b) => (b as HistogramBin & { kde: number }).kde),
  )
  rawBins.forEach((b) => {
    const kde = (b as HistogramBin & { kde: number }).kde
    b.kdeScaled = (kde / maxKde) * maxCount * 0.95
  })

  const sorted = [...all].sort((a, b) => a - b)
  const mean = sorted.reduce((a, b) => a + b, 0) / sorted.length
  const variance = sorted.reduce((s, x) => s + (x - mean) ** 2, 0) / sorted.length
  const stddev = Math.sqrt(variance)
  const stats: DistributionStats = {
    count: sorted.length,
    mean,
    stddev,
    median: percentile(sorted, 50),
    p5: percentile(sorted, 5),
    p25: percentile(sorted, 25),
    p75: percentile(sorted, 75),
    p95: percentile(sorted, 95),
    iqr: percentile(sorted, 75) - percentile(sorted, 25),
    min: sorted[0],
    max: sorted[sorted.length - 1],
  }

  // Focused trade percentile rank
  const focusedRate = focused?.fixed_rate_bps ?? mean
  const below = sorted.filter((x) => x < focusedRate).length
  const pct = (below / sorted.length) * 100
  const zone = (p: number): MetricRow['zone'] => {
    const d = Math.abs(p - 50)
    if (d <= 25) return 'typical'
    if (d <= 40) return 'notable'
    if (d <= 47) return 'rare'
    return 'extreme'
  }
  const descriptor = (p: number): string => {
    const d = Math.abs(p - 50)
    if (d <= 25) return 'in the middle band'
    if (d <= 40) return p > 50 ? 'above typical range' : 'below typical range'
    if (d <= 47) return p > 50 ? 'rarely seen this high' : 'rarely seen this low'
    return p > 50 ? 'extreme high print' : 'extreme low print'
  }

  const notional = focused?.notional_usd ?? 100_000_000
  const dv01 = focused?.dv01_usd_per_bp ?? 50_000
  const tenor = focused?.tenor_years ?? 10

  const metricRows: MetricRow[] = [
    {
      key: 'fixed_rate',
      label: 'Fixed Rate (bps)',
      value: focusedRate,
      displayValue: focusedRate.toFixed(2),
      percentile: pct,
      zone: zone(pct),
      descriptor: descriptor(pct),
      sampleSize: stats.count,
      primary: true,
      showPercentile: true,
    },
    {
      key: 'dv01',
      label: 'DV01 (USD/bp)',
      value: dv01,
      displayValue: dv01 >= 1e6 ? `${(dv01 / 1e6).toFixed(1)}MM` : `${Math.round(dv01 / 1e3)}K`,
      percentile: 88,
      zone: 'notable',
      descriptor: 'larger than most',
      sampleSize: stats.count,
      showPercentile: true,
    },
    {
      key: 'notional',
      label: 'Notional (USD mm)',
      value: notional / 1e6,
      displayValue: `${(notional / 1e6).toFixed(1)}MM`,
      percentile: 92,
      zone: 'rare',
      descriptor: 'in top decile',
      sampleSize: stats.count,
      showPercentile: true,
    },
    {
      key: 'spread_to_mid',
      label: 'Spread to Mid (bps)',
      value: -0.9,
      displayValue: '−0.9',
      percentile: 34,
      zone: 'typical',
      descriptor: 'inside IQR',
      sampleSize: 1480,
      showPercentile: true,
    },
    {
      key: 'tenor_years',
      label: 'Tenor (years)',
      value: tenor,
      displayValue: tenor.toFixed(1),
      percentile: null,
      zone: null,
      descriptor: 'bucket pin',
      sampleSize: stats.count,
      showPercentile: false,
    },
  ]

  return { bins: rawBins, stats, metricRows }
}

// ── recency + extremes ─────────────────────────────────────────────────
export function generateRecency(focused: FocusedTrade | null): RecencyBucket {
  const rate = focused?.fixed_rate_bps ?? 384.2
  return {
    lastSimilar: {
      daysAgo: 2,
      date: '2026-04-22',
      value: +(rate - 0.3).toFixed(2),
      tradeId: 'USDS-10Y-4H8M2X',
      venue: 'TRADEWEB',
      platform: 'IDB',
    },
    frequency90d: { count: 47, avgIntervalDays: 1.8, lookbackDays: 90 },
    allTimeRecord: {
      largestNotional: { value: 812_500_000, displayValue: '812.5MM', date: '2026-03-17', platform: 'CUSTY', venue: 'BLOOMBERG' },
      highestRate: { value: +(rate + 34).toFixed(1), displayValue: (rate + 34).toFixed(1), date: '2025-11-19', platform: 'IDB', venue: 'TRADEWEB' },
      lowestRate:  { value: +(rate - 46).toFixed(1), displayValue: (rate - 46).toFixed(1), date: '2025-07-24', platform: 'IDB', venue: 'TULLETT' },
    },
    bucketRank: { rank: 12, total: 1847, by: 'notional' },
  }
}

export function generateExtremes(focused: FocusedTrade | null): ExtremeRow[] {
  const rate = focused?.fixed_rate_bps ?? 384.2
  return [
    { label: 'All-time high rate',        scope: 'All-time', rate: +(rate + 34).toFixed(1), dv01: 42_500,    notional: 50_000_000,  ts: '2025-11-19T09:42:18-05:00', venue: 'TRADEWEB',  platform: 'IDB' },
    { label: 'All-time low rate',         scope: 'All-time', rate: +(rate - 46).toFixed(1), dv01: 28_000,    notional: 32_500_000,  ts: '2025-07-24T11:08:52-04:00', venue: 'TULLETT',   platform: 'IDB' },
    { label: 'All-time largest notional', scope: 'All-time', rate: +(rate - 11).toFixed(1), dv01: 702_000,   notional: 812_500_000, ts: '2026-03-17T14:12:03-04:00', venue: 'BLOOMBERG', platform: 'CUSTY' },
    { label: 'All-time largest DV01',     scope: 'All-time', rate: +(rate - 7.5).toFixed(1),dv01: 1_120_000, notional: 1_294_000_000, ts: '2026-02-28T10:55:41-05:00', venue: 'TRADITION', platform: 'IDB' },
    { label: '52w high rate',             scope: '52 weeks', rate: +(rate + 34).toFixed(1), dv01: 42_500,    notional: 50_000_000,  ts: '2025-11-19T09:42:18-05:00', venue: 'TRADEWEB',  platform: 'IDB' },
    { label: '52w low rate',              scope: '52 weeks', rate: +(rate - 46).toFixed(1), dv01: 28_000,    notional: 32_500_000,  ts: '2025-07-24T11:08:52-04:00', venue: 'TULLETT',   platform: 'IDB' },
    { label: '30d high rate',             scope: '30 days',  rate: +(rate + 7.5).toFixed(1),dv01: 85_000,    notional: 98_200_000,  ts: '2026-04-08T13:24:11-04:00', venue: 'TRADEWEB',  platform: 'IDB' },
    { label: '30d low rate',              scope: '30 days',  rate: +(rate - 17).toFixed(1), dv01: 65_000,    notional: 75_100_000,  ts: '2026-04-15T10:47:33-04:00', venue: 'TULLETT',   platform: 'IDB' },
  ]
}

export function generateRecentSimilar(focused: FocusedTrade | null): RecentSimilarRow[] {
  const rate = focused?.fixed_rate_bps ?? 384.2
  return [
    { daysAgo: 2,  date: '2026-04-22', rate: +(rate - 0.3).toFixed(2), dv01: 125_000, notional: 145_000_000, platform: 'IDB',   venue: 'TRADEWEB' },
    { daysAgo: 4,  date: '2026-04-20', rate: +(rate + 0.9).toFixed(2), dv01: 98_000,  notional: 114_000_000, platform: 'CUSTY', venue: 'BLOOMBERG' },
    { daysAgo: 6,  date: '2026-04-18', rate: +(rate + 0.6).toFixed(2), dv01: 175_000, notional: 203_500_000, platform: 'IDB',   venue: 'TRADITION' },
    { daysAgo: 9,  date: '2026-04-15', rate: +(rate - 1.6).toFixed(2), dv01: 88_000,  notional: 102_000_000, platform: 'IDB',   venue: 'TRADEWEB' },
    { daysAgo: 11, date: '2026-04-13', rate: +(rate + 1.2).toFixed(2), dv01: 210_000, notional: 244_000_000, platform: 'CUSTY', venue: 'BLOOMBERG' },
  ]
}
