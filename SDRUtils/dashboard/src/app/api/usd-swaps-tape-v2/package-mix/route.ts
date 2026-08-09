import { NextResponse } from 'next/server'
import { query } from '@/lib/db'
import { TAPE_PACKAGES } from '@/lib/tape-tables'

const PACKAGES_TABLE = TAPE_PACKAGES

export async function GET(req: Request) {
  const url = new URL(req.url)
  const days = parseInt(url.searchParams.get('days') ?? '30', 10)

  const dailySql = `
    SELECT
      as_of_date AS day,
      COALESCE(UPPER(package_type), 'UNKNOWN') AS package_type,
      SUM(ABS(total_risk::float)) AS dv01,
      COUNT(*) AS trade_count
    FROM ${PACKAGES_TABLE}
    WHERE contributes_to_flow_any = TRUE
      AND as_of_date >= (CURRENT_DATE - INTERVAL '${Math.min(days, 90)} days')
    GROUP BY 1, 2
    ORDER BY 1 ASC, 2
  `

  try {
    const { rows } = await query(dailySql)
    return NextResponse.json(
      { rows, days },
      { headers: { 'Cache-Control': 'private, max-age=120, stale-while-revalidate=300' } },
    )
  } catch (error: any) {
    return NextResponse.json({ error: error?.message ?? 'failed' }, { status: 500 })
  }
}
