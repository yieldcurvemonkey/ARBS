// ABOUTME: GET /api/usd-swaps-tape-v2/clusters — temporal cluster timeline data.
import { NextResponse } from 'next/server'
import { query } from '@/lib/db'
import { CLUSTERS_SQL } from './route.logic'

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
