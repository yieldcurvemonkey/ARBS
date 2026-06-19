import { NextResponse } from 'next/server'
import { query } from '@/lib/db'

const PACKAGES_TABLE = 'arbs_usd_swap_tape_packages_v2'

export async function GET(req: Request) {
  const url = new URL(req.url)
  const date = url.searchParams.get('date') ?? new Date().toISOString().slice(0, 10)

  const mixSql = `
    SELECT
      COALESCE(UPPER(package_type), 'UNKNOWN') AS package_type,
      SUM(ABS(total_risk::float)) AS total_dv01,
      COUNT(*) AS trade_count
    FROM ${PACKAGES_TABLE}
    WHERE contributes_to_flow_any = TRUE
      AND as_of_date = $1::date
    GROUP BY 1
    ORDER BY total_dv01 DESC
  `

  const hourlySql = `
    SELECT
      date_trunc('hour', COALESCE(original_execution_start, execution_start) AT TIME ZONE 'America/New_York') AS hour,
      COALESCE(UPPER(package_type), 'UNKNOWN') AS package_type,
      SUM(ABS(total_risk::float)) AS dv01
    FROM ${PACKAGES_TABLE}
    WHERE contributes_to_flow_any = TRUE
      AND as_of_date = $1::date
    GROUP BY 1, 2
    ORDER BY 1 ASC, 2
  `

  try {
    const [mixRes, hourlyRes] = await Promise.all([
      query(mixSql, [date]),
      query(hourlySql, [date]),
    ])
    return NextResponse.json(
      { mix: mixRes.rows, hourly: hourlyRes.rows, date },
      { headers: { 'Cache-Control': 'private, max-age=60, stale-while-revalidate=120' } },
    )
  } catch (error: any) {
    return NextResponse.json({ error: error?.message ?? 'failed' }, { status: 500 })
  }
}
