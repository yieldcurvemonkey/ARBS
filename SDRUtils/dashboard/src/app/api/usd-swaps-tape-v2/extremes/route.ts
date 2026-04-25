// GET /api/usd-swaps-tape-v2/extremes
// Returns the all-time / 52-week / 30-day high/low rate + largest
// notional + largest DV01 for the focused bucket, plus a short list of
// recent-similar trades used by the Traded Levels tab. Trader-requested
// "what and when" surface.
import { NextResponse } from 'next/server'
import { query } from '@/lib/db'
import {
  platformCaseSql,
  rateToBps,
  safeNum,
} from '@/lib/usd-swaps-tape-v2/analytics'

// Phase 2 cutover: extremes reads from the v2 leg table.
const LEGS_TABLE = 'arbs_usd_swap_tape_legs_v2'

type ExtremeDbRow = {
  label: string
  scope: 'All-time' | '52 weeks' | '30 days'
  fixed_rate: number | null
  risk: number | null
  notional: number | null
  ts: string | null
  venue: string | null
  platform: 'IDB' | 'CUSTY'
}

type SimilarDbRow = {
  ts: string
  fixed_rate: number | null
  risk: number | null
  notional: number | null
  platform: 'IDB' | 'CUSTY'
  venue: string | null
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
    // Phase 4: canonical underlier — see /analytics-timeseries route
    // and SDRUtils/core/underlier_canonical.py for the collapsing rule.
    canonical: 'l.canonical_underlier_key',
  }
  const filterCol = groupCol[groupBy]
  if (!filterCol) {
    return NextResponse.json(
      { error: `invalid groupBy: ${groupBy}` },
      { status: 400 },
    )
  }

  const platformExpr = platformCaseSql('l')
  const focusedRateBps = Number(searchParams.get('focusedRate') ?? 'NaN')
  const focusedNotional = Number(searchParams.get('focusedNotional') ?? 'NaN')
  const primaryTol = Number(searchParams.get('primaryTol') ?? '2.0')
  const sizeTol = Number(searchParams.get('sizeTol') ?? '0.25')

  try {
    // Extremes — one SELECT per (scope, extreme type) stitched with UNION ALL.
    // Each branch picks a single row via ORDER BY + LIMIT 1; the label &
    // scope columns are literals so the UI gets a stable identity key.
    //
    // `since` filter is baked per-branch so 52w/30d narrow the window
    // before the ORDER BY. Keeping branches terse trades duplication for
    // readability — worth it for a ~150-line route.
    const now = new Date()
    const d52w = new Date(now.getTime() - 52 * 7 * 86_400_000).toISOString()
    const d30d = new Date(now.getTime() - 30 * 86_400_000).toISOString()

    // Shared template for one extreme branch.
    const branch = (
      labelLit: string,
      scopeLit: string,
      orderClause: string,
      sinceParamIdx: number | null,
    ) => {
      const sinceFilter = sinceParamIdx
        ? `AND COALESCE(l.original_execution_timestamp, l.execution_timestamp) >= $${sinceParamIdx}::timestamptz`
        : ''
      return `
        (SELECT
           '${labelLit}'::text AS label,
           '${scopeLit}'::text AS scope,
           l.fixed_rate::float AS fixed_rate,
           l.risk::float AS risk,
           l.notional::float AS notional,
           COALESCE(l.original_execution_timestamp, l.execution_timestamp) AS ts,
           l.venue AS venue,
           ${platformExpr} AS platform
         FROM ${LEGS_TABLE} l
         WHERE ${filterCol} = $1
           AND l.fixed_rate IS NOT NULL
           AND NOT COALESCE(l.is_unwind, false)
           ${sinceFilter}
         ORDER BY ${orderClause}
         LIMIT 1)
      `
    }
    const sql = [
      branch('All-time high rate', 'All-time', 'l.fixed_rate DESC NULLS LAST', null),
      branch('All-time low rate', 'All-time', 'l.fixed_rate ASC NULLS LAST', null),
      branch('All-time largest notional', 'All-time', 'ABS(l.notional) DESC NULLS LAST', null),
      branch('All-time largest DV01', 'All-time', 'ABS(l.risk) DESC NULLS LAST', null),
      branch('52w high rate', '52 weeks', 'l.fixed_rate DESC NULLS LAST', 2),
      branch('52w low rate', '52 weeks', 'l.fixed_rate ASC NULLS LAST', 2),
      branch('30d high rate', '30 days', 'l.fixed_rate DESC NULLS LAST', 3),
      branch('30d low rate', '30 days', 'l.fixed_rate ASC NULLS LAST', 3),
    ].join(' UNION ALL ')

    const { rows: extremeRows } = await query<ExtremeDbRow>(sql, [value, d52w, d30d])

    const extremes = extremeRows.map((r) => ({
      label: r.label,
      scope: r.scope,
      rate: rateToBps(r.fixed_rate),
      dv01: Math.abs(safeNum(r.risk)),
      notional: Math.abs(safeNum(r.notional)),
      ts: r.ts ?? '',
      venue: r.venue ?? '—',
      platform: r.platform,
    }))

    // Recent similar prints — up to 8 within tolerance, last 90 days.
    let similar: SimilarDbRow[] = []
    if (Number.isFinite(focusedRateBps)) {
      const since90 = new Date(now.getTime() - 90 * 86_400_000).toISOString()
      const sizeBand = Number.isFinite(focusedNotional)
        ? focusedNotional * sizeTol
        : null
      const sizeFilter = sizeBand
        ? `AND ABS(ABS(l.notional) - $5::float) <= $6::float`
        : ''
      const sParams: unknown[] = [
        value,
        since90,
        focusedRateBps / 10_000, // convert bps back to decimal for SQL comparison
        primaryTol / 10_000,
      ]
      if (sizeBand) sParams.push(focusedNotional, sizeBand)
      const similarSql = `
        SELECT
          COALESCE(l.original_execution_timestamp, l.execution_timestamp) AS ts,
          l.fixed_rate::float AS fixed_rate,
          l.risk::float AS risk,
          l.notional::float AS notional,
          ${platformExpr} AS platform,
          l.venue AS venue
        FROM ${LEGS_TABLE} l
        WHERE ${filterCol} = $1
          AND COALESCE(l.original_execution_timestamp, l.execution_timestamp) >= $2::timestamptz
          AND l.fixed_rate IS NOT NULL
          AND ABS(l.fixed_rate - $3::float) <= $4::float
          ${sizeFilter}
          AND NOT COALESCE(l.is_unwind, false)
        ORDER BY COALESCE(l.original_execution_timestamp, l.execution_timestamp) DESC
        LIMIT 8
      `
      const res = await query<SimilarDbRow>(similarSql, sParams)
      similar = res.rows
    }

    const recentSimilar = similar.map((s) => {
      const daysAgo = Math.max(
        0,
        Math.floor((Date.now() - new Date(s.ts).getTime()) / 86_400_000),
      )
      return {
        daysAgo,
        date: String(s.ts).slice(0, 10),
        rate: rateToBps(s.fixed_rate),
        dv01: Math.abs(safeNum(s.risk)),
        notional: Math.abs(safeNum(s.notional)),
        platform: s.platform,
        venue: s.venue ?? '—',
      }
    })

    return NextResponse.json({ extremes, recentSimilar })
  } catch (error) {
    console.error('usd-swaps-tape-v2/extremes error', error)
    const message = error instanceof Error ? error.message : 'Failed to fetch extremes'
    return NextResponse.json({ error: message }, { status: 500 })
  }
}
