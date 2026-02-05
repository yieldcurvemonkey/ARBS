// ABOUTME: Market-wide summary statistics aggregated across all (expiry,tenor) buckets.
// Provides volume heatmap data: trade count, total notional, total premium, gross vega by bucket.
import { NextResponse } from 'next/server'
import { query } from '@/lib/db'
import { resolveDisplayView } from '@/lib/swaptions-tape'

const IDB_MIC_CODES = ['BGCD', 'ISWV', 'TPSE']

export type MarketSummaryBucket = {
  forward_label: string
  tenor_label: string
  package_type: string
  platform_class: 'CUSTY' | 'IDB'
  trade_count: number
  total_notional: number | null
  total_premium: number | null
  avg_notional: number | null
  avg_premium: number | null
  first_trade: string | null
  last_trade: string | null
}

export type MarketSummaryResponse = {
  buckets: MarketSummaryBucket[]
  generated_at: string
  days_back: number
}

function parseDaysBack(raw: string | null): number {
  const parsed = Number(raw ?? 365)
  if (Number.isNaN(parsed) || parsed < 1) return 365
  return Math.min(parsed, 3650)
}

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url)
  const daysBack = parseDaysBack(searchParams.get('days'))
  const packageTypeParam = searchParams.get('packageType')

  try {
    const { view } = await resolveDisplayView()

    const conditions: string[] = []
    const params: unknown[] = []

    // Only NEWT-TRAD actions
    conditions.push("plat.event_action = 'NEWT-TRAD'")

    // Time filter
    params.push(daysBack)
    conditions.push(
      `d.execution_start >= NOW() - ($${params.length} || ' days')::interval`
    )

    // Must have tenor and forward labels
    conditions.push('d.tenor_label IS NOT NULL')
    conditions.push('d.forward_label IS NOT NULL')

    // Optional package type filter
    if (packageTypeParam) {
      params.push(packageTypeParam)
      conditions.push(
        `UPPER(REPLACE(d.package_type, '-', '_')) = $${params.length}`
      )
    }

    const whereClause = conditions.length
      ? `WHERE ${conditions.join(' AND ')}`
      : ''

    // Build IDB MIC check expression
    const idbMicList = IDB_MIC_CODES.map((code) => `'${code}'`).join(', ')

    const sql = `
      WITH classified AS (
        SELECT
          d.forward_label,
          d.tenor_label,
          UPPER(REPLACE(d.package_type, '-', '_')) AS package_type,
          CASE
            WHEN UPPER(plat.platform_identifier) IN (${idbMicList}) THEN 'IDB'
            ELSE 'CUSTY'
          END AS platform_class,
          d.total_notional,
          d.total_premium,
          d.execution_start
        FROM ${view} d
        LEFT JOIN LATERAL (
          SELECT mode() WITHIN GROUP (ORDER BY platform_identifier) AS platform_identifier
                , mode() WITHIN GROUP (ORDER BY event_action) AS event_action
          FROM arbs_swaption_legs_v1 l
          WHERE l.package_id = d.package_id
        ) plat ON TRUE
        ${whereClause}
      )
      SELECT
        forward_label,
        tenor_label,
        package_type,
        platform_class,
        COUNT(*)::int AS trade_count,
        SUM(ABS(total_notional)) AS total_notional,
        SUM(ABS(total_premium)) AS total_premium,
        AVG(ABS(total_notional)) AS avg_notional,
        AVG(ABS(total_premium)) AS avg_premium,
        MIN(execution_start) AS first_trade,
        MAX(execution_start) AS last_trade
      FROM classified
      GROUP BY forward_label, tenor_label, package_type, platform_class
      ORDER BY
        forward_label,
        tenor_label,
        package_type,
        platform_class
    `

    const result = await query(sql, params)

    const buckets: MarketSummaryBucket[] = result.rows.map((row: any) => ({
      forward_label: row.forward_label,
      tenor_label: row.tenor_label,
      package_type: row.package_type,
      platform_class: row.platform_class,
      trade_count: Number(row.trade_count),
      total_notional: row.total_notional ? Number(row.total_notional) : null,
      total_premium: row.total_premium ? Number(row.total_premium) : null,
      avg_notional: row.avg_notional ? Number(row.avg_notional) : null,
      avg_premium: row.avg_premium ? Number(row.avg_premium) : null,
      first_trade: row.first_trade || null,
      last_trade: row.last_trade || null,
    }))

    return NextResponse.json({
      buckets,
      generated_at: new Date().toISOString(),
      days_back: daysBack,
    } satisfies MarketSummaryResponse)
  } catch (error: any) {
    console.error('swaptions-tape/market-summary GET error', error)
    return NextResponse.json(
      { error: error?.message || 'Failed to fetch market summary' },
      { status: 500 }
    )
  }
}
