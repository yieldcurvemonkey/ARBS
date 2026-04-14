// ABOUTME: GET /api/usd-swaps-tape-v2/clusters — temporal cluster timeline data.
import { NextResponse } from 'next/server'
import { query } from '@/lib/db'

export const CLUSTERS_SQL = `
  SELECT
    cluster_id,
    MIN(execution_timestamp) AS start_ts,
    MAX(execution_timestamp) AS end_ts,
    COUNT(*)::int AS trade_count,
    SUM(risk)::float AS total_risk,
    SUM(ABS(notional))::float AS gross_notional,
    (ARRAY_AGG(DISTINCT tape_label ORDER BY tape_label))[1:5] AS tape_labels,
    (ARRAY_AGG(DISTINCT lifecycle_type ORDER BY lifecycle_type))[1:5] AS lifecycle_types
  FROM arbs_usd_swap_tape_legs_v1
  WHERE as_of_date = $1::date
    AND cluster_id IS NOT NULL
  GROUP BY cluster_id
  ORDER BY MIN(execution_timestamp)
`

export async function GET(req: Request) {
  const url = new URL(req.url)
  const date = url.searchParams.get('date') ?? new Date().toISOString().slice(0, 10)
  try {
    const result = await query(CLUSTERS_SQL, [date])
    const clusters = result.rows.map((row: any) => ({
      cluster_id: row.cluster_id,
      start_ts: row.start_ts,
      end_ts: row.end_ts,
      trade_count: Number(row.trade_count),
      total_risk: Number(row.total_risk),
      gross_notional: Number(row.gross_notional),
      tape_labels: row.tape_labels ?? [],
      lifecycle_types: row.lifecycle_types ?? [],
    }))
    return NextResponse.json({ clusters })
  } catch (error: any) {
    return NextResponse.json({ error: error?.message ?? 'failed' }, { status: 500 })
  }
}
