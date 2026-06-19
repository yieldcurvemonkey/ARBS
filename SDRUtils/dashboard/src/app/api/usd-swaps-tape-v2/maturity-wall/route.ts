import { NextResponse } from 'next/server'
import { query } from '@/lib/db'

const LEGS_TABLE = 'arbs_usd_swap_tape_legs_v2'

export async function GET(req: Request) {
  const url = new URL(req.url)
  const metric = url.searchParams.get('metric') ?? 'notional'
  const bin = url.searchParams.get('bin') ?? 'quarter'

  const dateTrunc = bin === 'month' ? 'month' : 'quarter'
  // Cap per-leg notional at 500B — the P43 notional cap schedule tops
  // out ~250B; anything beyond that is a data quality artifact (corrupt
  // SDR feed values like 1e17 that blow up the chart Y-axis).
  const valueExpr = metric === 'dv01'
    ? 'SUM(ABS(risk::float))'
    : 'SUM(LEAST(ABS(notional::float), 5e11))'

  const sql = `
    WITH latest AS (
      SELECT MAX(as_of_date) AS max_date FROM ${LEGS_TABLE}
    )
    SELECT
      date_trunc('${dateTrunc}', l.expiration_date) AS period,
      CASE
        WHEN l.tenor_years < 2.5 THEN '1-2Y'
        WHEN l.tenor_years < 4.5 THEN '3-4Y'
        WHEN l.tenor_years < 7.5 THEN '5-7Y'
        WHEN l.tenor_years < 12.5 THEN '8-12Y'
        WHEN l.tenor_years < 22.5 THEN '13-22Y'
        ELSE '23Y+'
      END AS tenor_bucket,
      ${valueExpr} AS value,
      COUNT(*) AS trade_count
    FROM ${LEGS_TABLE} l
    CROSS JOIN latest
    WHERE l.contributes_to_flow = TRUE
      AND l.expiration_date IS NOT NULL
      AND l.expiration_date >= latest.max_date
      AND l.expiration_date < (latest.max_date + INTERVAL '5 years')
      AND l.as_of_date >= (latest.max_date - INTERVAL '90 days')
      AND l.as_of_date <= latest.max_date
      AND l.tenor_years IS NOT NULL
    GROUP BY 1, 2
    ORDER BY 1 ASC, 2
  `

  const yearSql = `
    WITH latest AS (
      SELECT MAX(as_of_date) AS max_date FROM ${LEGS_TABLE}
    )
    SELECT
      EXTRACT(YEAR FROM l.expiration_date)::int AS yr,
      ${valueExpr} AS value,
      COUNT(*) AS trade_count
    FROM ${LEGS_TABLE} l
    CROSS JOIN latest
    WHERE l.contributes_to_flow = TRUE
      AND l.expiration_date IS NOT NULL
      AND l.expiration_date >= latest.max_date
      AND l.expiration_date < (latest.max_date + INTERVAL '5 years')
      AND l.as_of_date >= (latest.max_date - INTERVAL '90 days')
      AND l.as_of_date <= latest.max_date
    GROUP BY 1
    ORDER BY 1
  `

  try {
    const [mainRes, yearRes] = await Promise.all([
      query(sql),
      query(yearSql),
    ])
    return NextResponse.json(
      { rows: mainRes.rows, byYear: yearRes.rows, metric, bin },
      { headers: { 'Cache-Control': 'private, max-age=600, stale-while-revalidate=1200' } },
    )
  } catch (error: any) {
    return NextResponse.json({ error: error?.message ?? 'failed' }, { status: 500 })
  }
}
