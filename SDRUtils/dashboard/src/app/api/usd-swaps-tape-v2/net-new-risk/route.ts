import { NextResponse } from 'next/server'
import { query } from '@/lib/db'

const LEGS_TABLE = 'arbs_usd_swap_tape_legs_v2'

export async function GET(req: Request) {
  const url = new URL(req.url)
  const date = url.searchParams.get('date') ?? new Date().toISOString().slice(0, 10)

  const sql = `
    SELECT
      date_trunc('hour', execution_timestamp AT TIME ZONE 'America/New_York') AS hour,
      tenor_label,
      SUM(risk::float) AS net_risk,
      SUM(ABS(risk::float)) AS gross_risk,
      COUNT(*) AS trade_count
    FROM ${LEGS_TABLE}
    WHERE contributes_to_flow = TRUE
      AND as_of_date = $1::date
      AND tenor_label IS NOT NULL
      AND risk IS NOT NULL
    GROUP BY 1, 2
    ORDER BY 1 ASC, 2 ASC
  `

  try {
    const { rows } = await query(sql, [date])
    return NextResponse.json(
      { rows, date },
      { headers: { 'Cache-Control': 'private, max-age=60, stale-while-revalidate=120' } },
    )
  } catch (error: any) {
    return NextResponse.json({ error: error?.message ?? 'failed' }, { status: 500 })
  }
}
