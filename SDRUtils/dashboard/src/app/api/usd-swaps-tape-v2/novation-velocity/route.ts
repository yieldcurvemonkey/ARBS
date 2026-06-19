import { NextResponse } from 'next/server'
import { query } from '@/lib/db'

const PACKAGES_TABLE = 'arbs_usd_swap_tape_packages_v2'

export async function GET(req: Request) {
  const url = new URL(req.url)
  const days = parseInt(url.searchParams.get('days') ?? '30', 10)

  const sql = `
    SELECT
      as_of_date AS day,
      COUNT(*) AS novation_count,
      SUM(ABS(total_risk::float)) AS total_dv01
    FROM ${PACKAGES_TABLE}
    WHERE is_novation_any = TRUE
      AND as_of_date >= (CURRENT_DATE - INTERVAL '${Math.min(days, 90)} days')
    GROUP BY 1
    ORDER BY 1 ASC
  `

  try {
    const { rows } = await query(sql)
    return NextResponse.json(
      { rows, days },
      { headers: { 'Cache-Control': 'private, max-age=120, stale-while-revalidate=300' } },
    )
  } catch (error: any) {
    return NextResponse.json({ error: error?.message ?? 'failed' }, { status: 500 })
  }
}
