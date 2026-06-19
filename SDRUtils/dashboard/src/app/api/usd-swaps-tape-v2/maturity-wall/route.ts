import { NextResponse } from 'next/server'
import { query } from '@/lib/db'

const LEGS_TABLE = 'arbs_usd_swap_tape_legs_v2'

export async function GET(req: Request) {
  const url = new URL(req.url)
  const date = url.searchParams.get('date') ?? new Date().toISOString().slice(0, 10)

  const sql = `
    SELECT
      date_trunc('month', expiration_date) AS month,
      tenor_label,
      SUM(ABS(notional::float)) AS total_notional,
      SUM(ABS(risk::float)) AS total_dv01,
      COUNT(*) AS trade_count
    FROM ${LEGS_TABLE}
    WHERE contributes_to_flow = TRUE
      AND expiration_date IS NOT NULL
      AND expiration_date >= $1::date
      AND expiration_date < ($1::date + INTERVAL '5 years')
      AND as_of_date >= ($1::date - INTERVAL '90 days')
      AND as_of_date <= $1::date
    GROUP BY 1, 2
    ORDER BY 1 ASC, 2
  `

  try {
    const { rows } = await query(sql, [date])
    return NextResponse.json(
      { rows, date },
      { headers: { 'Cache-Control': 'private, max-age=600, stale-while-revalidate=1200' } },
    )
  } catch (error: any) {
    return NextResponse.json({ error: error?.message ?? 'failed' }, { status: 500 })
  }
}
