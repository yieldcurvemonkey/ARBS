import { NextResponse } from 'next/server'
import { query } from '@/lib/db'

const LEGS_TABLE = 'arbs_usd_swap_tape_legs_v2'

export async function GET(req: Request) {
  const url = new URL(req.url)
  const date = url.searchParams.get('date') ?? new Date().toISOString().slice(0, 10)

  const todaySql = `
    SELECT
      EXTRACT(HOUR FROM execution_timestamp AT TIME ZONE 'America/New_York')::int AS hour_et,
      tenor_label,
      SUM(ABS(risk::float)) AS block_dv01,
      COUNT(*) AS trade_count
    FROM ${LEGS_TABLE}
    WHERE is_block = TRUE
      AND as_of_date = $1::date
      AND tenor_label IS NOT NULL
    GROUP BY 1, 2
    ORDER BY 1, 2
  `

  const histSql = `
    SELECT
      EXTRACT(HOUR FROM execution_timestamp AT TIME ZONE 'America/New_York')::int AS hour_et,
      tenor_label,
      SUM(ABS(risk::float)) / COUNT(DISTINCT as_of_date) AS avg_block_dv01,
      COUNT(*) / COUNT(DISTINCT as_of_date)::float AS avg_trade_count
    FROM ${LEGS_TABLE}
    WHERE is_block = TRUE
      AND as_of_date >= ($1::date - INTERVAL '20 days')
      AND as_of_date < $1::date
      AND tenor_label IS NOT NULL
    GROUP BY 1, 2
    ORDER BY 1, 2
  `

  try {
    const [todayRes, histRes] = await Promise.all([
      query(todaySql, [date]),
      query(histSql, [date]),
    ])
    return NextResponse.json(
      { today: todayRes.rows, historical: histRes.rows, date },
      { headers: { 'Cache-Control': 'private, max-age=60, stale-while-revalidate=120' } },
    )
  } catch (error: any) {
    return NextResponse.json({ error: error?.message ?? 'failed' }, { status: 500 })
  }
}
