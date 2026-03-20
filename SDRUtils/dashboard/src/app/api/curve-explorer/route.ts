// ABOUTME: API route for the curve explorer — queries Supabase curve tables for inventory overview.
import { NextResponse } from 'next/server'
import { query } from '@/lib/db'

export const runtime = 'nodejs'

interface SnapshotSummary {
  curve_name: string
  trading_date: string
  snapshot_count: number
  earliest_utc: string
  latest_utc: string
  tags: string[]
}

interface IntradayBlockSummary {
  curve_name: string
  trading_date: string
  row_count: number
  data_format: string
  sha256: string
  created_at: string
}

interface AnalyticsBlockSummary {
  curve_name: string
  trading_date: string
  row_count: number
  data_format: string
  sha256: string
  created_at: string
}

interface CurveOverview {
  curve_name: string
  snapshot_days: number
  total_snapshots: number
  intraday_days: number
  analytics_days: number
  date_min: string | null
  date_max: string | null
}

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url)
  const view = searchParams.get('view') || 'overview'
  const curveName = searchParams.get('curve_name') || null
  const limit = Math.min(Number(searchParams.get('limit') || 500), 2000)

  try {
    if (view === 'overview') {
      // Aggregate overview: one row per curve_name with counts and date ranges
      const res = await query<CurveOverview>(`
        WITH snap AS (
          SELECT curve_name,
                 COUNT(DISTINCT trading_date) AS snapshot_days,
                 COUNT(*) AS total_snapshots,
                 MIN(trading_date) AS date_min,
                 MAX(trading_date) AS date_max
          FROM arbs_curve_snapshots_v1
          GROUP BY curve_name
        ),
        intra AS (
          SELECT curve_name, COUNT(*) AS intraday_days
          FROM arbs_curve_intraday_blocks_v1
          GROUP BY curve_name
        ),
        anal AS (
          SELECT curve_name, COUNT(*) AS analytics_days
          FROM arbs_curve_analytics_blocks_v1
          GROUP BY curve_name
        ),
        all_curves AS (
          SELECT curve_name FROM snap
          UNION SELECT curve_name FROM intra
          UNION SELECT curve_name FROM anal
        )
        SELECT
          a.curve_name,
          COALESCE(s.snapshot_days, 0)::int AS snapshot_days,
          COALESCE(s.total_snapshots, 0)::int AS total_snapshots,
          COALESCE(i.intraday_days, 0)::int AS intraday_days,
          COALESCE(an.analytics_days, 0)::int AS analytics_days,
          s.date_min::text,
          s.date_max::text
        FROM all_curves a
        LEFT JOIN snap s USING (curve_name)
        LEFT JOIN intra i USING (curve_name)
        LEFT JOIN anal an USING (curve_name)
        ORDER BY a.curve_name
      `)
      return NextResponse.json({ view: 'overview', rows: res.rows })
    }

    if (view === 'snapshots') {
      // Per-day snapshot summary for a given curve
      const whereClause = curveName ? 'WHERE curve_name = $1' : ''
      const params = curveName ? [curveName] : []
      const res = await query<SnapshotSummary>(`
        SELECT
          curve_name,
          trading_date::text AS trading_date,
          COUNT(*) AS snapshot_count,
          MIN(timestamp_utc)::text AS earliest_utc,
          MAX(timestamp_utc)::text AS latest_utc,
          array_agg(DISTINCT unnested_tag ORDER BY unnested_tag) AS tags
        FROM arbs_curve_snapshots_v1,
             LATERAL unnest(tags) AS unnested_tag
        ${whereClause}
        GROUP BY curve_name, trading_date
        ORDER BY trading_date DESC, curve_name
        LIMIT $${params.length + 1}
      `, [...params, limit])
      return NextResponse.json({ view: 'snapshots', rows: res.rows })
    }

    if (view === 'intraday') {
      const whereClause = curveName ? 'WHERE curve_name = $1' : ''
      const params = curveName ? [curveName] : []
      const res = await query<IntradayBlockSummary>(`
        SELECT
          curve_name,
          trading_date::text AS trading_date,
          row_count,
          data_format,
          sha256,
          created_at::text AS created_at
        FROM arbs_curve_intraday_blocks_v1
        ${whereClause}
        ORDER BY trading_date DESC, curve_name
        LIMIT $${params.length + 1}
      `, [...params, limit])
      return NextResponse.json({ view: 'intraday', rows: res.rows })
    }

    if (view === 'analytics') {
      const whereClause = curveName ? 'WHERE curve_name = $1' : ''
      const params = curveName ? [curveName] : []
      const res = await query<AnalyticsBlockSummary>(`
        SELECT
          curve_name,
          trading_date::text AS trading_date,
          row_count,
          data_format,
          sha256,
          created_at::text AS created_at
        FROM arbs_curve_analytics_blocks_v1
        ${whereClause}
        ORDER BY trading_date DESC, curve_name
        LIMIT $${params.length + 1}
      `, [...params, limit])
      return NextResponse.json({ view: 'analytics', rows: res.rows })
    }

    return NextResponse.json({ error: `Unknown view: ${view}` }, { status: 400 })
  } catch (error: any) {
    console.error('curve-explorer GET error', error)
    return NextResponse.json(
      { error: error?.message || 'Failed to query curve data' },
      { status: 500 }
    )
  }
}
