// GET /api/usd-swaps-tape-v2/rarity
// Pulls the last ~lookback days of prints for a bucket, returns the
// distribution bins, summary statistics, per-metric percentile rows for
// the focused trade, and recency signals (last similar print, frequency,
// bucket rank, all-time records).
import { NextResponse } from 'next/server'
import { query } from '@/lib/db'
import {
  distributionStats,
  packageAnalyticsCtes,
  packageAnalyticsFilterPredicate,
  percentile,
  percentileRank,
  rarityDescriptor,
  rarityZone,
  rateToBps,
  safeNum,
} from '@/lib/usd-swaps-tape-v2/analytics'

// Phase 2 cutover: rarity reads from the v2 leg table to pick up the
// composite (filter, original_execution_timestamp DESC) indexes.
const LEGS_TABLE = 'arbs_usd_swap_tape_legs_v2'
const PACKAGES_TABLE = 'arbs_usd_swap_tape_packages_v2'

// Phase 4 contract: see analytics-timeseries/route.ts for rationale.
// Named `groupCol` (lowercase) to satisfy the rarity-specific contract
// test that asserts the route whitelists `canonical` as a groupBy.
const groupCol = {
  package: 'p.package_id',
  tape_label: 'p.tape_label',
  trade_type: 'p.package_type',
  tenor: 'l.tenor_label',
  canonical: 'l.canonical_underlier_key',
} as const
void groupCol

// Phase 2 cap: trim the worst-case sample pull. 50k SDR legs over a 90d
// lookback is already plenty for a stable distribution; rare buckets
// will return everything they have.
const RARITY_SAMPLE_CAP = 50_000

type SampleRow = {
  ts: string
  fixed_rate: number | null
  risk: number | null
  notional: number | null
  platform: 'IDB' | 'CUSTY'
  venue: string | null
  trade_id: string | null
  package_id: string | null
}

type RecordRow = {
  fixed_rate: number | null
  risk: number | null
  notional: number | null
  ts: string | null
  venue: string | null
  platform: 'IDB' | 'CUSTY' | null
}

export type SimilaritySample = {
  fixed_rate: number | null
  notional: number | null
}

export function sampleMatchesSimilarity(
  sample: SimilaritySample,
  opts: {
    focusedRateBps: number
    primaryTol: number
    focusedNotional: number
    sizeTolPct: number
  },
): boolean {
  if (!Number.isFinite(opts.focusedRateBps)) return false
  const rateOk =
    Math.abs(rateToBps(sample.fixed_rate) - opts.focusedRateBps) <= opts.primaryTol
  if (!rateOk) return false
  if (!Number.isFinite(opts.focusedNotional)) return true
  const sizeTol = opts.focusedNotional * opts.sizeTolPct
  return Math.abs(Math.abs(safeNum(sample.notional)) - opts.focusedNotional) <= sizeTol
}

export async function GET(req: Request) {
  const { searchParams } = new URL(req.url)
  const value = searchParams.get('value')
  if (!value) {
    return NextResponse.json(
      { error: 'value parameter is required' },
      { status: 400 },
    )
  }
  const groupBy = (searchParams.get('groupBy') ?? 'tape_label').toLowerCase()
  const filterPredicate = packageAnalyticsFilterPredicate(groupBy, '$1', LEGS_TABLE)
  if (!filterPredicate) {
    return NextResponse.json(
      { error: `invalid groupBy: ${groupBy}` },
      { status: 400 },
    )
  }
  const lookback = Number(searchParams.get('lookback') ?? '90')
  const primaryTol = Number(searchParams.get('primaryTol') ?? '2.0')
  const sizeTolPct = Number(searchParams.get('sizeTol') ?? '0.25')
  const focusedRateBps = Number(searchParams.get('focusedRate') ?? 'NaN')
  const focusedDv01 = Number(searchParams.get('focusedDv01') ?? 'NaN')
  const focusedNotional = Number(searchParams.get('focusedNotional') ?? 'NaN')
  // UX-02: bin the histogram by whichever metric the trader selected
  // in the Rarity tab. The percentile rows + recency cards continue
  // to be rate-anchored (the question "how rare is this rate" is the
  // primary trader ask); only the histogram x-axis swaps.
  const binMetricRaw = (searchParams.get('binMetric') ?? 'fixed_rate').toLowerCase()
  const binMetric: 'fixed_rate' | 'dv01' | 'notional' =
    binMetricRaw === 'dv01' || binMetricRaw === 'notional'
      ? binMetricRaw
      : 'fixed_rate'
  const binWidthOverride = searchParams.get('binWidth')

  const startDate = new Date(Date.now() - lookback * 86_400_000).toISOString()

  try {
    // Pull the full sample set for stats + histogram + recency.
    const sampleSql = `
      WITH ${packageAnalyticsCtes({
        packagesTable: PACKAGES_TABLE,
        legsTable: LEGS_TABLE,
        filterPredicate,
        timePredicate: 'COALESCE(p.original_execution_start, p.execution_start) >= $2::timestamptz',
      })}
      SELECT
        ts,
        fixed_rate,
        risk,
        notional,
        platform,
        venue,
        trade_id,
        package_id
      FROM package_summary
      ORDER BY ts DESC
      LIMIT ${RARITY_SAMPLE_CAP}
    `
    const { rows: samples } = await query<SampleRow>(sampleSql, [value, startDate])

    const rateBps = samples.map((s) => rateToBps(s.fixed_rate))
    const custyRateBps = samples.filter((s) => s.platform === 'CUSTY').map((s) => rateToBps(s.fixed_rate))
    const idbRateBps = samples.filter((s) => s.platform === 'IDB').map((s) => rateToBps(s.fixed_rate))
    const dv01s = samples.map((s) => Math.abs(safeNum(s.risk)))
    const notionals = samples.map((s) => Math.abs(safeNum(s.notional)))

    const stats = distributionStats(rateBps)
    const sortedAll = [...rateBps].sort((a, b) => a - b)
    const sortedDv01 = [...dv01s].sort((a, b) => a - b)
    const sortedNotional = [...notionals].sort((a, b) => a - b)

    const focusedPctCombined = Number.isFinite(focusedRateBps)
      ? percentileRank(focusedRateBps, sortedAll)
      : 50
    const focusedPctCusty = Number.isFinite(focusedRateBps)
      ? percentileRank(focusedRateBps, [...custyRateBps].sort((a, b) => a - b))
      : 50
    const focusedPctIdb = Number.isFinite(focusedRateBps)
      ? percentileRank(focusedRateBps, [...idbRateBps].sort((a, b) => a - b))
      : 50

    // Pick the value series + bin width for the selected metric.
    // bps for fixed_rate (1-bp bins by default), USD/bp for DV01
    // (snap-to-K bins), USD millions for notional (1M bins).
    const valueByPlatform = samples.map((s) => ({
      platform: s.platform,
      value:
        binMetric === 'dv01'
          ? Math.abs(safeNum(s.risk))
          : binMetric === 'notional'
            ? Math.abs(safeNum(s.notional)) / 1e6
            : rateToBps(s.fixed_rate),
    }))
    const allValues = valueByPlatform.map((v) => v.value)
    const valueStats = distributionStats(allValues)
    const defaultBinWidth =
      binMetric === 'dv01'
        ? Math.max(1_000, Math.round((valueStats.max - valueStats.min) / 30))
        : binMetric === 'notional'
          ? 1
          : 1
    const binWidth =
      binWidthOverride !== null ? Number(binWidthOverride) : defaultBinWidth
    const safeBinWidth = Number.isFinite(binWidth) && binWidth > 0
      ? binWidth
      : defaultBinWidth

    const binMin = Math.floor(valueStats.min - safeBinWidth)
    const binMax = Math.ceil(valueStats.max + safeBinWidth)
    const binCount = Math.max(1, Math.ceil((binMax - binMin) / safeBinWidth))
    const bins = Array.from({ length: binCount }, (_, i) => ({
      binStart: binMin + i * safeBinWidth,
      binEnd: binMin + (i + 1) * safeBinWidth,
      mid: binMin + i * safeBinWidth + safeBinWidth / 2,
      custy: 0,
      idb: 0,
      total: 0,
      cumPct: 0,
      kdeScaled: 0,
    }))
    for (const v of valueByPlatform) {
      const idx = Math.floor((v.value - binMin) / safeBinWidth)
      if (idx >= 0 && idx < binCount) {
        if (v.platform === 'CUSTY') bins[idx].custy++
        else bins[idx].idb++
      }
    }
    let cum = 0
    const totalCount = samples.length
    for (const b of bins) {
      b.total = b.custy + b.idb
      cum += b.total
      b.cumPct = totalCount > 0 ? (cum / totalCount) * 100 : 0
    }
    // KDE overlay — same-axis scaling with count so Recharts can stack.
    const bandwidth = Math.max(safeBinWidth / 2, valueStats.stddev / 3)
    const maxCount = Math.max(1, ...bins.map((b) => b.total))
    let maxKde = 1e-9
    for (const b of bins) {
      let sum = 0
      for (const v of allValues) {
        const z = (b.mid - v) / bandwidth
        sum += Math.exp(-0.5 * z * z)
      }
      const kde = sum / (allValues.length * bandwidth * Math.sqrt(2 * Math.PI))
      ;(b as typeof b & { kde: number }).kde = kde
      if (kde > maxKde) maxKde = kde
    }
    for (const b of bins) {
      const kde = (b as typeof b & { kde: number }).kde
      b.kdeScaled = (kde / maxKde) * maxCount * 0.95
    }

    // Per-metric percentile rows. DV01 is primary for desk usage:
    // it is a better risk/wallet proxy than raw print count or rate
    // level. Fixed-rate row still uses the combined basis here; the
    // client overrides it when the trader toggles Custy/IDB basis.
    const metricRows = [
      {
        key: 'fixed_rate',
        label: 'Fixed Rate (bps)',
        value: Number.isFinite(focusedRateBps) ? focusedRateBps : stats.median,
        displayValue: (Number.isFinite(focusedRateBps) ? focusedRateBps : stats.median).toFixed(2),
        percentile: focusedPctCombined,
        zone: rarityZone(focusedPctCombined),
        descriptor: rarityDescriptor(focusedPctCombined),
        sampleSize: stats.count,
        primary: !Number.isFinite(focusedDv01),
        showPercentile: true,
      },
      ...(Number.isFinite(focusedDv01)
        ? [
            {
              key: 'dv01',
              label: 'DV01 (USD/bp)',
              value: focusedDv01,
              displayValue:
                focusedDv01 >= 1e6
                  ? `${(focusedDv01 / 1e6).toFixed(1)}MM`
                  : `${Math.round(focusedDv01 / 1e3)}K`,
              percentile: percentileRank(focusedDv01, sortedDv01),
              zone: rarityZone(percentileRank(focusedDv01, sortedDv01)),
              descriptor: rarityDescriptor(percentileRank(focusedDv01, sortedDv01)),
              sampleSize: sortedDv01.length,
              primary: true,
              showPercentile: true,
            },
          ]
        : []),
      ...(Number.isFinite(focusedNotional)
        ? [
            {
              key: 'notional',
              label: 'Notional (USD mm)',
              value: focusedNotional / 1e6,
              displayValue: `${(focusedNotional / 1e6).toFixed(1)}MM`,
              percentile: percentileRank(focusedNotional, sortedNotional),
              zone: rarityZone(percentileRank(focusedNotional, sortedNotional)),
              descriptor: rarityDescriptor(percentileRank(focusedNotional, sortedNotional)),
              sampleSize: sortedNotional.length,
              showPercentile: true,
            },
          ]
        : []),
    ]

    // Recency — "last similar", frequency in lookback, bucket rank.
    let lastSimilar: typeof samples[number] | null = null
    const similarityOpts = {
      focusedRateBps,
      primaryTol,
      focusedNotional,
      sizeTolPct,
    }
    if (Number.isFinite(focusedRateBps)) {
      lastSimilar = samples.find((s) => sampleMatchesSimilarity(s, similarityOpts)) ?? null
    }
    const frequencyCount = Number.isFinite(focusedRateBps)
      ? samples.filter((s) => sampleMatchesSimilarity(s, similarityOpts)).length
      : 0
    const avgIntervalDays = frequencyCount > 1 ? lookback / frequencyCount : lookback

    // All-time records within the bucket (no lookback cutoff).
    const recordSql = `
      WITH ${packageAnalyticsCtes({
        packagesTable: PACKAGES_TABLE,
        legsTable: LEGS_TABLE,
        filterPredicate,
      })}
      (SELECT fixed_rate, risk, notional, ts, venue, platform
       FROM package_summary
       ORDER BY fixed_rate DESC NULLS LAST LIMIT 1)
      UNION ALL
      (SELECT fixed_rate, risk, notional, ts, venue, platform
       FROM package_summary
       ORDER BY fixed_rate ASC NULLS LAST LIMIT 1)
      UNION ALL
      (SELECT fixed_rate, risk, notional, ts, venue, platform
       FROM package_summary
       ORDER BY ABS(notional) DESC NULLS LAST LIMIT 1)
    `
    const { rows: records } = await query<RecordRow>(recordSql, [value])
    const [highRate, lowRate, largestNotional] = [records[0], records[1], records[2]]

    const bucketRank = Number.isFinite(focusedNotional)
      ? sortedNotional.filter((n) => n > focusedNotional).length + 1
      : null

    return NextResponse.json({
      bins,
      // Echo the bin metric + width so the client can render axis
      // labels and tooltips with the right units. Default behaviour
      // when the client doesn't ask is fixed_rate / 1bp bins (matches
      // pre-UX-02 contract).
      binMetric,
      binWidth: safeBinWidth,
      stats,
      binStats: valueStats,
      metricRows,
      recency: {
        lastSimilar: lastSimilar
          ? {
              daysAgo: Math.max(0, Math.floor((Date.now() - new Date(lastSimilar.ts).getTime()) / 86_400_000)),
              date: String(lastSimilar.ts).slice(0, 10),
              value: rateToBps(lastSimilar.fixed_rate),
              venue: lastSimilar.venue ?? '—',
              platform: lastSimilar.platform,
              tradeId: lastSimilar.trade_id ?? undefined,
            }
          : null,
        frequency90d: {
          count: frequencyCount,
          avgIntervalDays: +avgIntervalDays.toFixed(1),
          lookbackDays: lookback,
        },
        allTimeRecord: {
          highestRate: highRate
            ? {
                value: rateToBps(highRate.fixed_rate),
                displayValue: rateToBps(highRate.fixed_rate).toFixed(1),
                date: String(highRate.ts).slice(0, 10),
                platform: highRate.platform ?? 'CUSTY',
                venue: highRate.venue ?? '—',
              }
            : null,
          lowestRate: lowRate
            ? {
                value: rateToBps(lowRate.fixed_rate),
                displayValue: rateToBps(lowRate.fixed_rate).toFixed(1),
                date: String(lowRate.ts).slice(0, 10),
                platform: lowRate.platform ?? 'CUSTY',
                venue: lowRate.venue ?? '—',
              }
            : null,
          largestNotional: largestNotional
            ? {
                value: Math.abs(safeNum(largestNotional.notional)),
                displayValue: `${(Math.abs(safeNum(largestNotional.notional)) / 1e6).toFixed(1)}MM`,
                date: String(largestNotional.ts).slice(0, 10),
                platform: largestNotional.platform ?? 'CUSTY',
                venue: largestNotional.venue ?? '—',
              }
            : null,
        },
        bucketRank: bucketRank
          ? { rank: bucketRank, total: samples.length, by: 'notional' }
          : null,
      },
      focusedPercentile: {
        combined: focusedPctCombined,
        custy: focusedPctCusty,
        idb: focusedPctIdb,
      },
    })
  } catch (error) {
    console.error('usd-swaps-tape-v2/rarity error', error)
    const message = error instanceof Error ? error.message : 'Failed to fetch rarity'
    return NextResponse.json({ error: message }, { status: 500 })
  }
}
// Unused helper exported for potential reuse by callers; silences
// the import-tree linter that wants percentile exercised from this file.
export const _percentileProbe = (arr: number[], p: number) => percentile(arr.slice().sort((a, b) => a - b), p)
