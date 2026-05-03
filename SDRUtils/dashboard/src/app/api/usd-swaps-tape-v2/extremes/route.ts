// GET /api/usd-swaps-tape-v2/extremes
// Returns the all-time / 52-week / 30-day high/low rate + largest
// notional + largest DV01 for the focused bucket, plus a short list of
// recent-similar trades used by the Traded Levels tab. Trader-requested
// "what and when" surface.
import { NextResponse } from 'next/server'
import { query } from '@/lib/db'
import {
  packageAnalyticsCtes,
  packageAnalyticsFilterPredicate,
  rateToBps,
  safeNum,
} from '@/lib/usd-swaps-tape-v2/analytics'

// Phase 2 cutover: extremes reads from the v2 leg table.
const LEGS_TABLE = 'arbs_usd_swap_tape_legs_v2'
const PACKAGES_TABLE = 'arbs_usd_swap_tape_packages_v2'

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
  const filterPredicate = packageAnalyticsFilterPredicate(groupBy, '$1', LEGS_TABLE)
  if (!filterPredicate) {
    return NextResponse.json(
      { error: `invalid groupBy: ${groupBy}` },
      { status: 400 },
    )
  }
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
        ? `AND ts >= $${sinceParamIdx}::timestamptz`
        : ''
      return `
        (SELECT
           '${labelLit}'::text AS label,
           '${scopeLit}'::text AS scope,
           fixed_rate,
           risk,
           notional,
           ts,
           venue,
           platform
         FROM package_summary
         WHERE fixed_rate IS NOT NULL
           ${sinceFilter}
         ORDER BY ${orderClause}
         LIMIT 1)
      `
    }
    const sql = `
      WITH ${packageAnalyticsCtes({
        packagesTable: PACKAGES_TABLE,
        legsTable: LEGS_TABLE,
        filterPredicate,
      })}
      ${[
        branch('All-time high rate', 'All-time', 'fixed_rate DESC NULLS LAST', null),
        branch('All-time low rate', 'All-time', 'fixed_rate ASC NULLS LAST', null),
        branch('All-time largest notional', 'All-time', 'ABS(notional) DESC NULLS LAST', null),
        branch('All-time largest DV01', 'All-time', 'ABS(risk) DESC NULLS LAST', null),
        branch('52w high rate', '52 weeks', 'fixed_rate DESC NULLS LAST', 2),
        branch('52w low rate', '52 weeks', 'fixed_rate ASC NULLS LAST', 2),
        branch('30d high rate', '30 days', 'fixed_rate DESC NULLS LAST', 3),
        branch('30d low rate', '30 days', 'fixed_rate ASC NULLS LAST', 3),
      ].join(' UNION ALL ')}
    `

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
        ? `AND ABS(ABS(notional) - $5::float) <= $6::float`
        : ''
      const sParams: unknown[] = [
        value,
        since90,
        focusedRateBps / 10_000, // convert bps back to decimal for SQL comparison
        primaryTol / 10_000,
      ]
      if (sizeBand) sParams.push(focusedNotional, sizeBand)
      const similarSql = `
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
          venue
        FROM package_summary
        WHERE ABS(fixed_rate - $3::float) <= $4::float
          ${sizeFilter}
        ORDER BY ts DESC
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
