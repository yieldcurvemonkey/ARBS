// GET /api/usd-swaps-tape-v2/rarity
// Pulls the last ~lookback days of prints for a bucket, returns the
// distribution bins, summary statistics, per-metric percentile rows for
// the focused trade, and recency signals (last similar print, frequency,
// bucket rank, all-time records).
import { NextResponse } from 'next/server'
import { query } from '@/lib/db'
import {
  distributionStats,
  percentile,
  percentileRank,
  platformCaseSql,
  rarityDescriptor,
  rarityZone,
  rateToBps,
  safeNum,
} from '@/lib/usd-swaps-tape-v2/analytics'

// Phase 2 cutover: rarity reads from the v2 leg table to pick up the
// composite (filter, original_execution_timestamp DESC) indexes.
const LEGS_TABLE = 'arbs_usd_swap_tape_legs_v2'

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
  const groupCol: Record<string, string> = {
    tape_label: 'l.tape_label',
    package: 'l.package_id',
    trade_type: 'l.trade_type',
    tenor: 'l.tenor_label',
  }
  const filterCol = groupCol[groupBy]
  if (!filterCol) {
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
  const binWidth = Number(searchParams.get('binWidth') ?? '1')

  const platformExpr = platformCaseSql('l')
  const startDate = new Date(Date.now() - lookback * 86_400_000).toISOString()

  try {
    // Pull the full sample set for stats + histogram + recency.
    const sampleSql = `
      SELECT
        COALESCE(l.original_execution_timestamp, l.execution_timestamp) AS ts,
        l.fixed_rate::float AS fixed_rate,
        l.risk::float AS risk,
        l.notional::float AS notional,
        ${platformExpr} AS platform,
        l.venue AS venue,
        l.trade_id AS trade_id,
        l.package_id AS package_id
      FROM ${LEGS_TABLE} l
      WHERE ${filterCol} = $1
        AND COALESCE(l.original_execution_timestamp, l.execution_timestamp) >= $2::timestamptz
        AND l.fixed_rate IS NOT NULL
        AND NOT COALESCE(l.is_unwind, false)
      ORDER BY COALESCE(l.original_execution_timestamp, l.execution_timestamp) DESC
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

    // Histogram with configurable bin width (default 1 bp).
    const binMin = Math.floor(stats.min - 2)
    const binMax = Math.ceil(stats.max + 2)
    const binCount = Math.max(1, Math.ceil((binMax - binMin) / binWidth))
    const bins = Array.from({ length: binCount }, (_, i) => ({
      binStart: binMin + i * binWidth,
      binEnd: binMin + (i + 1) * binWidth,
      mid: binMin + i * binWidth + binWidth / 2,
      custy: 0,
      idb: 0,
      total: 0,
      cumPct: 0,
      kdeScaled: 0,
    }))
    for (const s of samples) {
      const v = rateToBps(s.fixed_rate)
      const idx = Math.floor((v - binMin) / binWidth)
      if (idx >= 0 && idx < binCount) {
        if (s.platform === 'CUSTY') bins[idx].custy++
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
    const bandwidth = Math.max(0.5, stats.stddev / 3)
    const maxCount = Math.max(1, ...bins.map((b) => b.total))
    let maxKde = 1e-9
    for (const b of bins) {
      let sum = 0
      for (const v of rateBps) {
        const z = (b.mid - v) / bandwidth
        sum += Math.exp(-0.5 * z * z)
      }
      const kde = sum / (rateBps.length * bandwidth * Math.sqrt(2 * Math.PI))
      ;(b as typeof b & { kde: number }).kde = kde
      if (kde > maxKde) maxKde = kde
    }
    for (const b of bins) {
      const kde = (b as typeof b & { kde: number }).kde
      b.kdeScaled = (kde / maxKde) * maxCount * 0.95
    }

    // Per-metric percentile rows. Fixed-rate row uses the combined basis
    // here; the client overrides it when the trader toggles Custy/IDB
    // basis (rareity tab re-maps primary percentile on the fly).
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
        primary: true,
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
    if (Number.isFinite(focusedRateBps)) {
      const tolBps = primaryTol
      const sizeTol = Number.isFinite(focusedNotional) ? focusedNotional * sizeTolPct : Infinity
      lastSimilar = samples.find((s) => {
        const rateOk = Math.abs(rateToBps(s.fixed_rate) - focusedRateBps) <= tolBps
        const sizeOk = Math.abs(Math.abs(safeNum(s.notional)) - focusedNotional) <= sizeTol
        return rateOk && sizeOk
      }) ?? null
    }
    const frequencyCount = Number.isFinite(focusedRateBps)
      ? samples.filter(
          (s) => Math.abs(rateToBps(s.fixed_rate) - focusedRateBps) <= primaryTol,
        ).length
      : 0
    const avgIntervalDays = frequencyCount > 1 ? lookback / frequencyCount : lookback

    // All-time records within the bucket (no lookback cutoff).
    const recordSql = `
      (SELECT l.fixed_rate::float AS fixed_rate, l.risk::float AS risk, l.notional::float AS notional,
              COALESCE(l.original_execution_timestamp, l.execution_timestamp) AS ts,
              l.venue AS venue, ${platformExpr} AS platform
       FROM ${LEGS_TABLE} l
       WHERE ${filterCol} = $1 AND l.fixed_rate IS NOT NULL AND NOT COALESCE(l.is_unwind, false)
       ORDER BY l.fixed_rate DESC NULLS LAST LIMIT 1)
      UNION ALL
      (SELECT l.fixed_rate::float, l.risk::float, l.notional::float,
              COALESCE(l.original_execution_timestamp, l.execution_timestamp),
              l.venue, ${platformExpr}
       FROM ${LEGS_TABLE} l
       WHERE ${filterCol} = $1 AND l.fixed_rate IS NOT NULL AND NOT COALESCE(l.is_unwind, false)
       ORDER BY l.fixed_rate ASC NULLS LAST LIMIT 1)
      UNION ALL
      (SELECT l.fixed_rate::float, l.risk::float, l.notional::float,
              COALESCE(l.original_execution_timestamp, l.execution_timestamp),
              l.venue, ${platformExpr}
       FROM ${LEGS_TABLE} l
       WHERE ${filterCol} = $1 AND l.notional IS NOT NULL AND NOT COALESCE(l.is_unwind, false)
       ORDER BY ABS(l.notional) DESC NULLS LAST LIMIT 1)
    `
    const { rows: records } = await query<RecordRow>(recordSql, [value])
    const [highRate, lowRate, largestNotional] = [records[0], records[1], records[2]]

    const bucketRank = Number.isFinite(focusedNotional)
      ? sortedNotional.filter((n) => n > focusedNotional).length + 1
      : null

    return NextResponse.json({
      bins,
      stats,
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
