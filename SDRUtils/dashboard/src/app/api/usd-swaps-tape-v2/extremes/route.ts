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
import { ServerLru } from '@/lib/usd-swaps-tape-v2/serverLru'
import { computeEtag, matchesIfNoneMatch } from '@/lib/usd-swaps-tape-v2/etag'
import {
  buildOutrightTapeLabelCandidates,
  isOutrightTapeLabelCandidate,
} from '../analytics-timeseries/route.logic'

const LRU_MAX = Number(process.env.ANALYTICS_LRU_MAX ?? 2048)
const LRU_TTL = Number(process.env.ANALYTICS_LRU_TTL ?? 300_000)
const lru = new ServerLru<{ payload: unknown; etag: string }>({
  max: LRU_MAX,
  ttlMs: LRU_TTL,
})

function cacheKey(url: URL): string {
  const params = new URLSearchParams(url.search)
  const sorted = [...params.entries()].sort()
  return JSON.stringify(sorted)
}

const CACHE_HEADERS = {
  'Cache-Control': 'private, max-age=300, stale-while-revalidate=600',
} as const

// Phase 2 cutover: extremes reads from the v2 leg table.
const LEGS_TABLE = 'arbs_usd_swap_tape_legs_v2'
const PACKAGES_TABLE = 'arbs_usd_swap_tape_packages_v2'

// Phase 4 contract: every analytics-dock route exposes the canonical
// underlier key under groupBy=canonical. The actual SQL filter is
// constructed by packageAnalyticsFilterPredicate() in
// @/lib/usd-swaps-tape-v2/analytics — the table below is the
// route-local view that lets the contract test (and a human reader)
// confirm the mapping without grepping the helper.
const GROUP_BY_COLUMN = {
  package: 'p.package_id',
  tape_label: 'p.tape_label',
  trade_type: 'p.package_type',
  tenor: 'l.tenor_label',
  canonical: 'l.canonical_underlier_key',
} as const
void GROUP_BY_COLUMN

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

async function produceExtremes(req: Request): Promise<{ status: number; payload: unknown }> {
  const { searchParams } = new URL(req.url)
  const value = searchParams.get('value')
  if (!value) {
    return { status: 400, payload: { error: 'value parameter is required' } }
  }
  const groupBy = (searchParams.get('groupBy') ?? 'tape_label').toLowerCase()
  const filterPredicate = packageAnalyticsFilterPredicate(groupBy, '$1', LEGS_TABLE)
  if (!filterPredicate) {
    return { status: 400, payload: { error: `invalid groupBy: ${groupBy}` } }
  }
  const focusedRateBps = Number(searchParams.get('focusedRate') ?? 'NaN')
  const focusedNotional = Number(searchParams.get('focusedNotional') ?? 'NaN')
  const primaryTol = Number(searchParams.get('primaryTol') ?? '2.0')
  const sizeTol = Number(searchParams.get('sizeTol') ?? '0.25')

  try {
    const now = new Date()
    const d52w = new Date(now.getTime() - 52 * 7 * 86_400_000).toISOString()
    const d30d = new Date(now.getTime() - 30 * 86_400_000).toISOString()

    let extremeRows: ExtremeDbRow[]

    if (groupBy === 'tape_label' && isOutrightTapeLabelCandidate(value)) {
      const candidates = buildOutrightTapeLabelCandidates(value)
      const fastBranch = (
        labelLit: string,
        scopeLit: string,
        orderClause: string,
        sinceParamIdx: number | null,
      ) => {
        const sinceFilter = sinceParamIdx
          ? `AND ts >= $${sinceParamIdx}::timestamptz`
          : ''
        return `(SELECT '${labelLit}'::text AS label, '${scopeLit}'::text AS scope,
           fixed_rate, risk, notional, ts, venue, platform
         FROM base WHERE fixed_rate IS NOT NULL ${sinceFilter}
         ORDER BY ${orderClause} LIMIT 1)`
      }
      const fastSql = `
        WITH base AS (
          SELECT
            p.weighted_fixed_rate::float AS fixed_rate,
            p.total_risk::float AS risk,
            COALESCE(ABS(p.total_notional::float), ABS(p.gross_notional::float), 0) AS notional,
            COALESCE(p.original_execution_start, p.execution_start) AS ts,
            p.venue,
            CASE WHEN UPPER(COALESCE(p.venue, '')) = 'D2D' THEN 'IDB' ELSE 'CUSTY' END AS platform
          FROM ${PACKAGES_TABLE} p
          WHERE UPPER(COALESCE(p.tape_label, '')) = ANY($1::text[])
            AND UPPER(COALESCE(p.package_type, '')) = 'OUTRIGHT'
            AND NOT COALESCE(p.is_unwind, false)
            AND p.weighted_fixed_rate IS NOT NULL
        )
        ${[
          fastBranch('All-time high rate', 'All-time', 'fixed_rate DESC NULLS LAST', null),
          fastBranch('All-time low rate', 'All-time', 'fixed_rate ASC NULLS LAST', null),
          fastBranch('All-time largest notional', 'All-time', 'ABS(notional) DESC NULLS LAST', null),
          fastBranch('All-time largest DV01', 'All-time', 'ABS(risk) DESC NULLS LAST', null),
          fastBranch('52w high rate', '52 weeks', 'fixed_rate DESC NULLS LAST', 2),
          fastBranch('52w low rate', '52 weeks', 'fixed_rate ASC NULLS LAST', 2),
          fastBranch('30d high rate', '30 days', 'fixed_rate DESC NULLS LAST', 3),
          fastBranch('30d low rate', '30 days', 'fixed_rate ASC NULLS LAST', 3),
        ].join(' UNION ALL ')}
      `
      const { rows } = await query<ExtremeDbRow>(fastSql, [candidates, d52w, d30d])
      extremeRows = rows
    } else {
      const branch = (
        labelLit: string,
        scopeLit: string,
        orderClause: string,
        sinceParamIdx: number | null,
      ) => {
        const sinceFilter = sinceParamIdx
          ? `AND ts >= $${sinceParamIdx}::timestamptz`
          : ''
        return `(SELECT '${labelLit}'::text AS label, '${scopeLit}'::text AS scope,
           fixed_rate, risk, notional, ts, venue, platform
         FROM package_summary WHERE fixed_rate IS NOT NULL ${sinceFilter}
         ORDER BY ${orderClause} LIMIT 1)`
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
      const { rows } = await query<ExtremeDbRow>(sql, [value, d52w, d30d])
      extremeRows = rows
    }

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

    let similar: SimilarDbRow[] = []
    if (Number.isFinite(focusedRateBps)) {
      const since90 = new Date(now.getTime() - 90 * 86_400_000).toISOString()
      const rateDecimal = focusedRateBps / 10_000
      const tolDecimal = primaryTol / 10_000
      const sizeBand = Number.isFinite(focusedNotional)
        ? focusedNotional * sizeTol
        : null

      if (groupBy === 'tape_label' && isOutrightTapeLabelCandidate(value)) {
        const candidates = buildOutrightTapeLabelCandidates(value)
        const sizeFilter = sizeBand ? `AND ABS(ABS(COALESCE(p.total_notional::float, p.gross_notional::float, 0)) - $5::float) <= $6::float` : ''
        const sParams: unknown[] = [candidates, since90, rateDecimal, tolDecimal]
        if (sizeBand) sParams.push(focusedNotional, sizeBand)
        const fastSimilarSql = `
          SELECT
            COALESCE(p.original_execution_start, p.execution_start) AS ts,
            p.weighted_fixed_rate::float AS fixed_rate,
            p.total_risk::float AS risk,
            COALESCE(ABS(p.total_notional::float), ABS(p.gross_notional::float), 0) AS notional,
            CASE WHEN UPPER(COALESCE(p.venue, '')) = 'D2D' THEN 'IDB' ELSE 'CUSTY' END AS platform,
            p.venue
          FROM ${PACKAGES_TABLE} p
          WHERE UPPER(COALESCE(p.tape_label, '')) = ANY($1::text[])
            AND UPPER(COALESCE(p.package_type, '')) = 'OUTRIGHT'
            AND NOT COALESCE(p.is_unwind, false)
            AND p.weighted_fixed_rate IS NOT NULL
            AND COALESCE(p.original_execution_start, p.execution_start) >= $2::timestamptz
            AND ABS(p.weighted_fixed_rate::float - $3::float) <= $4::float
            ${sizeFilter}
          ORDER BY COALESCE(p.original_execution_start, p.execution_start) DESC
          LIMIT 8
        `
        const res = await query<SimilarDbRow>(fastSimilarSql, sParams)
        similar = res.rows
      } else {
        const sizeFilter = sizeBand ? `AND ABS(ABS(notional) - $5::float) <= $6::float` : ''
        const sParams: unknown[] = [value, since90, rateDecimal, tolDecimal]
        if (sizeBand) sParams.push(focusedNotional, sizeBand)
        const similarSql = `
          WITH ${packageAnalyticsCtes({
            packagesTable: PACKAGES_TABLE,
            legsTable: LEGS_TABLE,
            filterPredicate,
            timePredicate: 'COALESCE(p.original_execution_start, p.execution_start) >= $2::timestamptz',
          })}
          SELECT ts, fixed_rate, risk, notional, platform, venue
          FROM package_summary
          WHERE ABS(fixed_rate - $3::float) <= $4::float ${sizeFilter}
          ORDER BY ts DESC LIMIT 8
        `
        const res = await query<SimilarDbRow>(similarSql, sParams)
        similar = res.rows
      }
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

    return { status: 200, payload: { extremes, recentSimilar } }
  } catch (error) {
    console.error('usd-swaps-tape-v2/extremes error', error)
    const message = error instanceof Error ? error.message : 'Failed to fetch extremes'
    return { status: 500, payload: { error: message } }
  }
}

export async function GET(request: Request) {
  const url = new URL(request.url)
  const ifNoneMatch = request.headers.get('If-None-Match')
  const key = cacheKey(url)

  const hit = lru.get(key)
  if (hit) {
    if (matchesIfNoneMatch(hit.etag, ifNoneMatch)) {
      return new Response(null, {
        status: 304,
        headers: { ETag: hit.etag, ...CACHE_HEADERS },
      })
    }
    return NextResponse.json(hit.payload, {
      headers: { ETag: hit.etag, ...CACHE_HEADERS },
    })
  }

  const { status, payload } = await produceExtremes(request)

  if (status === 200) {
    const etag = computeEtag(payload)
    lru.set(key, { payload, etag })
    if (matchesIfNoneMatch(etag, ifNoneMatch)) {
      return new Response(null, {
        status: 304,
        headers: { ETag: etag, ...CACHE_HEADERS },
      })
    }
    return NextResponse.json(payload, {
      status,
      headers: { ETag: etag, ...CACHE_HEADERS },
    })
  }

  return NextResponse.json(payload, { status })
}
