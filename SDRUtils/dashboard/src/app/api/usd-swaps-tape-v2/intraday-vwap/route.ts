import { NextResponse } from 'next/server'
import { query } from '@/lib/db'

const LEGS_TABLE = 'arbs_usd_swap_tape_legs_v2'

export async function GET(req: Request) {
  const url = new URL(req.url)
  const date = url.searchParams.get('date') ?? new Date().toISOString().slice(0, 10)
  const tenor = url.searchParams.get('tenor') ?? '10Y'
  const bucketMinutes = parseInt(url.searchParams.get('bucket') ?? '30', 10)
  const validBucket = [15, 30, 60].includes(bucketMinutes) ? bucketMinutes : 30

  const sql = `
    WITH flow_trades AS (
      SELECT
        execution_timestamp,
        fixed_rate::float AS fixed_rate,
        ABS(risk::float) AS abs_risk,
        tenor_label
      FROM ${LEGS_TABLE}
      WHERE contributes_to_flow = TRUE
        AND as_of_date = $1::date
        AND tenor_label = $2
        AND fixed_rate IS NOT NULL
        AND risk IS NOT NULL
        AND fixed_rate <> 0
        AND (
          lifecycle_type IN ('NEW_RISK')
          OR lifecycle_type IS NULL
        )
    ),
    bucketed AS (
      SELECT
        date_trunc('hour', execution_timestamp AT TIME ZONE 'America/New_York')
          + (FLOOR(EXTRACT(MINUTE FROM execution_timestamp AT TIME ZONE 'America/New_York') / ${validBucket}) * INTERVAL '1 minute' * ${validBucket}) AS bucket,
        SUM(fixed_rate * abs_risk) / NULLIF(SUM(abs_risk), 0) AS vwap,
        STDDEV_POP(fixed_rate) AS rate_std,
        COUNT(*) AS trade_count,
        SUM(abs_risk) AS bucket_dv01
      FROM flow_trades
      GROUP BY 1
    ),
    running AS (
      SELECT
        bucket,
        vwap,
        rate_std,
        trade_count,
        bucket_dv01,
        SUM(trade_count) OVER (ORDER BY bucket) AS cum_trades,
        SUM(bucket_dv01 * vwap) OVER (ORDER BY bucket) / NULLIF(SUM(bucket_dv01) OVER (ORDER BY bucket), 0) AS running_vwap,
        STDDEV_POP(vwap) OVER (ORDER BY bucket ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS running_std
      FROM bucketed
    )
    SELECT * FROM running ORDER BY bucket ASC
  `

  const printsSql = `
    SELECT
      execution_timestamp AS ts,
      fixed_rate::float AS fixed_rate,
      ABS(risk::float) AS abs_risk
    FROM ${LEGS_TABLE}
    WHERE contributes_to_flow = TRUE
      AND as_of_date = $1::date
      AND tenor_label = $2
      AND fixed_rate IS NOT NULL AND fixed_rate <> 0
      AND risk IS NOT NULL
      AND (lifecycle_type IN ('NEW_RISK') OR lifecycle_type IS NULL)
    ORDER BY execution_timestamp ASC
  `

  try {
    const [bucketRes, printsRes] = await Promise.all([
      query(sql, [date, tenor]),
      query(printsSql, [date, tenor]),
    ])
    return NextResponse.json(
      { buckets: bucketRes.rows, prints: printsRes.rows, date, tenor },
      { headers: { 'Cache-Control': 'private, max-age=30, stale-while-revalidate=60' } },
    )
  } catch (error: any) {
    return NextResponse.json({ error: error?.message ?? 'failed' }, { status: 500 })
  }
}
