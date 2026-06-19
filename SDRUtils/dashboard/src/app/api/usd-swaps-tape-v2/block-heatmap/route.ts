import { NextResponse } from 'next/server'
import { query } from '@/lib/db'

const LEGS_TABLE = 'arbs_usd_swap_tape_legs_v2'

export async function GET(req: Request) {
  const url = new URL(req.url)
  const days = parseInt(url.searchParams.get('days') ?? '20', 10)

  const sql = `
    SELECT
      EXTRACT(HOUR FROM execution_timestamp AT TIME ZONE 'America/New_York')::int AS hour_et,
      tenor_label,
      SUM(ABS(risk::float)) / NULLIF(COUNT(DISTINCT as_of_date), 0) AS avg_block_dv01,
      COUNT(*)::float / NULLIF(COUNT(DISTINCT as_of_date), 0) AS avg_trade_count,
      COUNT(DISTINCT as_of_date) AS n_days
    FROM ${LEGS_TABLE}
    WHERE is_block = TRUE
      AND as_of_date >= (CURRENT_DATE - INTERVAL '${Math.min(days, 90)} days')
      AND tenor_label IS NOT NULL
    GROUP BY 1, 2
    ORDER BY 1, 2
  `

  try {
    const { rows } = await query(sql)
    return NextResponse.json(
      { rows, days },
      { headers: { 'Cache-Control': 'private, max-age=300, stale-while-revalidate=600' } },
    )
  } catch (error: any) {
    return NextResponse.json({ error: error?.message ?? 'failed' }, { status: 500 })
  }
}
