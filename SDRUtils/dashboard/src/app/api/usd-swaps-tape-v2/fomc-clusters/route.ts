// ABOUTME: GET /api/usd-swaps-tape-v2/fomc-clusters — per-meeting rollups.
import { NextResponse } from 'next/server'
import { query } from '@/lib/db'

export const FOMC_CLUSTERS_SQL = `
  SELECT
    l.fomc_meeting_label,
    COUNT(*)::int AS trade_count,
    SUM(l.risk)::float AS net_risk,
    SUM(ABS(l.notional))::float AS gross_notional,
    BOOL_OR(l.is_multi_meeting_cluster) AS has_multi_meeting_flow
  FROM arbs_usd_swap_tape_legs_v1 l
  WHERE l.as_of_date = $1::date
    AND l.is_fomc_dated = TRUE
    AND l.fomc_meeting_label IS NOT NULL
  GROUP BY l.fomc_meeting_label
  ORDER BY l.fomc_meeting_label
`

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
