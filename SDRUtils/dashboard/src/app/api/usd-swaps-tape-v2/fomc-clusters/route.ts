// ABOUTME: GET /api/usd-swaps-tape-v2/fomc-clusters — per-meeting rollups.
import { NextResponse } from 'next/server'
import { query } from '@/lib/db'
import { FOMC_CLUSTERS_SQL } from './route.logic'

export async function GET(req: Request) {
  const url = new URL(req.url)
  const date = url.searchParams.get('date') ?? new Date().toISOString().slice(0, 10)
  try {
    const result = await query(FOMC_CLUSTERS_SQL, [date])
    const meetings = result.rows.map((row: any) => ({
      fomc_meeting_label: row.fomc_meeting_label,
      meeting_date: null, // v1: FOMC schedule lookup deferred to follow-up
      trade_count: Number(row.trade_count),
      net_risk: Number(row.net_risk),
      gross_notional: Number(row.gross_notional),
      has_multi_meeting_flow: Boolean(row.has_multi_meeting_flow),
    }))
    return NextResponse.json({ meetings })
  } catch (error: any) {
    return NextResponse.json({ error: error?.message ?? 'failed' }, { status: 500 })
  }
}
