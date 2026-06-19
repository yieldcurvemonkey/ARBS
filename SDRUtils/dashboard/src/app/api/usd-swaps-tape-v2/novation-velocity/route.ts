import { NextResponse } from 'next/server'
import { query } from '@/lib/db'

const PACKAGES_TABLE = 'arbs_usd_swap_tape_packages_v2'

export async function GET(req: Request) {
  const url = new URL(req.url)
  const date = url.searchParams.get('date') ?? new Date().toISOString().slice(0, 10)

  const todaySql = `
    SELECT
      EXTRACT(HOUR FROM COALESCE(original_execution_start, execution_start) AT TIME ZONE 'America/New_York')::int AS hour_et,
      COUNT(*) AS novation_count,
      SUM(ABS(total_risk::float)) AS total_dv01
    FROM ${PACKAGES_TABLE}
    WHERE is_novation_any = TRUE
      AND as_of_date = $1::date
    GROUP BY 1
    ORDER BY 1
  `

  const histSql = `
    SELECT
      EXTRACT(HOUR FROM COALESCE(original_execution_start, execution_start) AT TIME ZONE 'America/New_York')::int AS hour_et,
      COUNT(*)::float / NULLIF(COUNT(DISTINCT as_of_date), 0) AS avg_count,
      SUM(ABS(total_risk::float)) / NULLIF(COUNT(DISTINCT as_of_date), 0) AS avg_dv01
    FROM ${PACKAGES_TABLE}
    WHERE is_novation_any = TRUE
      AND as_of_date >= ($1::date - INTERVAL '20 days')
      AND as_of_date < $1::date
    GROUP BY 1
    ORDER BY 1
  `

  try {
    const [todayRes, histRes] = await Promise.all([
      query(todaySql, [date]),
      query(histSql, [date]),
    ])
    return NextResponse.json(
      { today: todayRes.rows, historical: histRes.rows, date },
      { headers: { 'Cache-Control': 'private, max-age=30, stale-while-revalidate=60' } },
    )
  } catch (error: any) {
    return NextResponse.json({ error: error?.message ?? 'failed' }, { status: 500 })
  }
}
