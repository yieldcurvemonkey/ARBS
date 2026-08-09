import { NextResponse } from 'next/server'
import { query } from '@/lib/db'
import { TAPE_LEGS } from '@/lib/tape-tables'

const LEGS_TABLE = TAPE_LEGS

export async function GET(req: Request) {
  const url = new URL(req.url)
  const days = parseInt(url.searchParams.get('days') ?? '30', 10)

  const sql = `
    SELECT
      as_of_date AS day,
      tenor_label,
      SUM(ABS(risk::float)) AS dv01,
      COUNT(*) AS trade_count
    FROM ${LEGS_TABLE}
    WHERE contributes_to_flow = TRUE
      AND as_of_date >= (CURRENT_DATE - INTERVAL '${Math.min(days, 90)} days')
      AND tenor_label IS NOT NULL
      AND risk IS NOT NULL
    GROUP BY 1, 2
    ORDER BY 1 ASC, 2
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
