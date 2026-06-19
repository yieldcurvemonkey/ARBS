import { NextResponse } from 'next/server'
import { query } from '@/lib/db'

const LEGS_TABLE = 'arbs_usd_swap_tape_legs_v2'
const PACKAGES_TABLE = 'arbs_usd_swap_tape_packages_v2'

export async function GET(req: Request) {
  const url = new URL(req.url)
  const date = url.searchParams.get('date') ?? new Date().toISOString().slice(0, 10)

  const shareSql = `
    SELECT
      COALESCE(UPPER(ccp), 'UNKNOWN') AS ccp,
      tenor_label,
      SUM(ABS(risk::float)) AS dv01,
      COUNT(*) AS trade_count
    FROM ${LEGS_TABLE}
    WHERE contributes_to_flow = TRUE
      AND as_of_date = $1::date
      AND tenor_label IS NOT NULL
    GROUP BY 1, 2
    ORDER BY 2, 1
  `

  const switchSql = `
    SELECT
      as_of_date,
      COALESCE(ccp_switch_from, 'UNKNOWN') AS switch_from,
      COALESCE(ccp_switch_to, 'UNKNOWN') AS switch_to,
      COUNT(*) AS switch_count,
      SUM(ABS(total_risk::float)) AS switch_dv01
    FROM ${PACKAGES_TABLE}
    WHERE is_ccp_switch = TRUE
      AND as_of_date >= ($1::date - INTERVAL '30 days')
      AND as_of_date <= $1::date
    GROUP BY 1, 2, 3
    ORDER BY 1 ASC
  `

  const dailySql = `
    SELECT
      as_of_date AS day,
      COALESCE(UPPER(ccp), 'UNKNOWN') AS ccp,
      SUM(ABS(risk::float)) AS dv01
    FROM ${LEGS_TABLE}
    WHERE contributes_to_flow = TRUE
      AND as_of_date >= ($1::date - INTERVAL '30 days')
      AND as_of_date <= $1::date
    GROUP BY 1, 2
    ORDER BY 1 ASC, 2
  `

  try {
    const [shareRes, switchRes, dailyRes] = await Promise.all([
      query(shareSql, [date]),
      query(switchSql, [date]),
      query(dailySql, [date]),
    ])
    return NextResponse.json(
      { share: shareRes.rows, switches: switchRes.rows, daily: dailyRes.rows, date },
      { headers: { 'Cache-Control': 'private, max-age=120, stale-while-revalidate=300' } },
    )
  } catch (error: any) {
    return NextResponse.json({ error: error?.message ?? 'failed' }, { status: 500 })
  }
}
