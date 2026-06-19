import { NextResponse } from 'next/server'
import { query } from '@/lib/db'

const LEGS_TABLE = 'arbs_usd_swap_tape_legs_v2'

export async function GET(req: Request) {
  const url = new URL(req.url)
  const days = parseInt(url.searchParams.get('days') ?? '30', 10)

  const dailySql = `
    WITH ranked_global AS (
      SELECT
        COALESCE(platform_identifier, 'UNKNOWN') AS platform,
        SUM(ABS(risk::float)) AS total_dv01,
        ROW_NUMBER() OVER (ORDER BY SUM(ABS(risk::float)) DESC) AS rn
      FROM ${LEGS_TABLE}
      WHERE contributes_to_flow = TRUE
        AND as_of_date >= (CURRENT_DATE - INTERVAL '${Math.min(days, 90)} days')
      GROUP BY 1
    ),
    top_platforms AS (
      SELECT platform FROM ranked_global WHERE rn <= 5
    )
    SELECT
      l.as_of_date AS day,
      CASE WHEN tp.platform IS NOT NULL THEN COALESCE(l.platform_identifier, 'UNKNOWN') ELSE 'OTHER' END AS platform,
      SUM(ABS(l.risk::float)) AS dv01
    FROM ${LEGS_TABLE} l
    LEFT JOIN top_platforms tp ON COALESCE(l.platform_identifier, 'UNKNOWN') = tp.platform
    WHERE l.contributes_to_flow = TRUE
      AND l.as_of_date >= (CURRENT_DATE - INTERVAL '${Math.min(days, 90)} days')
    GROUP BY 1, 2
    ORDER BY 1 ASC, 2
  `

  try {
    const { rows } = await query(dailySql)
    return NextResponse.json(
      { daily: rows, days },
      { headers: { 'Cache-Control': 'private, max-age=120, stale-while-revalidate=300' } },
    )
  } catch (error: any) {
    return NextResponse.json({ error: error?.message ?? 'failed' }, { status: 500 })
  }
}
