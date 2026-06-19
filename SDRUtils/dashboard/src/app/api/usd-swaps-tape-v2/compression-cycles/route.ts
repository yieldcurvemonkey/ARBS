import { NextResponse } from 'next/server'
import { query } from '@/lib/db'

const LEGS_TABLE = 'arbs_usd_swap_tape_legs_v2'

export async function GET(req: Request) {
  const url = new URL(req.url)
  const date = url.searchParams.get('date') ?? new Date().toISOString().slice(0, 10)

  const sql = `
    WITH compression_trades AS (
      SELECT
        execution_timestamp,
        notional::float AS notional,
        risk::float AS risk,
        tenor_label
      FROM ${LEGS_TABLE}
      WHERE (is_compression = TRUE OR lifecycle_type = 'COMPRESSION')
        AND as_of_date = $1::date
      ORDER BY execution_timestamp ASC
    ),
    with_gap AS (
      SELECT
        *,
        CASE
          WHEN execution_timestamp - LAG(execution_timestamp) OVER (ORDER BY execution_timestamp) > INTERVAL '10 minutes'
          THEN 1 ELSE 0
        END AS is_new_cluster
      FROM compression_trades
    ),
    bucketed AS (
      SELECT
        *,
        SUM(is_new_cluster) OVER (ORDER BY execution_timestamp) AS cluster_id
      FROM with_gap
    )
    SELECT
      cluster_id,
      MIN(execution_timestamp) AS window_start,
      MAX(execution_timestamp) AS window_end,
      COUNT(*) AS trade_count,
      SUM(ABS(COALESCE(notional, 0))) AS total_notional,
      SUM(ABS(COALESCE(risk, 0))) AS total_dv01,
      EXTRACT(EPOCH FROM MAX(execution_timestamp) - MIN(execution_timestamp))::int AS duration_seconds
    FROM bucketed
    GROUP BY cluster_id
    HAVING COUNT(*) >= 3
    ORDER BY MIN(execution_timestamp) ASC
  `

  try {
    const { rows } = await query(sql, [date])
    return NextResponse.json(
      { cycles: rows, date },
      { headers: { 'Cache-Control': 'private, max-age=30, stale-while-revalidate=60' } },
    )
  } catch (error: any) {
    return NextResponse.json({ error: error?.message ?? 'failed' }, { status: 500 })
  }
}
