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
      COUNT(*) AS compression_count,
      SUM(ABS(COALESCE(risk::float, 0))) AS total_dv01,
      SUM(ABS(COALESCE(notional::float, 0))) AS total_notional
    FROM ${LEGS_TABLE}
    WHERE (is_compression = TRUE OR lifecycle_type = 'COMPRESSION')
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
