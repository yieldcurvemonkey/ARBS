import { NextResponse } from 'next/server'
import { query } from '@/lib/db'
import { TAPE_LEGS } from '@/lib/tape-tables'

const LEGS_TABLE = TAPE_LEGS

export async function GET(req: Request) {
  const url = new URL(req.url)
  const date = url.searchParams.get('date') ?? new Date().toISOString().slice(0, 10)

  const sql = `
    SELECT
      effective_date,
      date_trunc('month', effective_date) AS month,
      is_fomc_dated,
      fomc_meeting_label,
      tenor_label,
      SUM(ABS(risk::float)) AS total_dv01,
      COUNT(*) AS trade_count,
      SUM(ABS(notional::float)) AS total_notional
    FROM ${LEGS_TABLE}
    WHERE contributes_to_flow = TRUE
      AND as_of_date >= ($1::date - INTERVAL '30 days')
      AND as_of_date <= $1::date
      AND effective_date IS NOT NULL
      AND COALESCE(forward_start_years, 0) > 0.05
    GROUP BY 1, 2, 3, 4, 5
    ORDER BY effective_date ASC
  `

  try {
    const { rows } = await query(sql, [date])
    return NextResponse.json(
      { rows, date },
      { headers: { 'Cache-Control': 'private, max-age=120, stale-while-revalidate=300' } },
    )
  } catch (error: any) {
    return NextResponse.json({ error: error?.message ?? 'failed' }, { status: 500 })
  }
}
