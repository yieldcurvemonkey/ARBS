// ABOUTME: GET /api/usd-swaps-tape-v2/risk-concentration — grouped DV01 aggregation.
import { NextResponse } from 'next/server'
import { query } from '@/lib/db'

export const GROUPABLE = {
  tape_label: 'l.tape_label',
  trade_type: 'l.trade_type',
  venue: 'l.venue',
  ccp: 'l.ccp',
  session: 'l.execution_session',
  tenor: 'l.tenor_label',
  rate_index: 'l.rate_index_clean',
  fomc_meeting: 'l.fomc_meeting_label',
} as const

export type GroupByKey = keyof typeof GROUPABLE

export function buildRiskConcentrationSql(
  groupBy: GroupByKey,
  clean: boolean,
): string {
  const expr = GROUPABLE[groupBy]
  const whereClean = clean
    ? ` AND NOT l.is_unwind AND NOT l.is_compression AND NOT l.is_ufro AND NOT l.is_reset_optimization`
    : ''
  return `
    SELECT ${expr} AS value,
           COUNT(*)::int AS trade_count,
           SUM(l.risk)::float AS total_dv01,
           SUM(l.notional)::float AS total_notional
    FROM arbs_usd_swap_tape_legs_v1 l
    WHERE l.as_of_date = $1::date
    ${whereClean}
      AND ${expr} IS NOT NULL
    GROUP BY ${expr}
    ORDER BY ABS(SUM(l.risk)) DESC NULLS LAST
    LIMIT 30
  `
}

export async function GET(req: Request) {
  const url = new URL(req.url)
  const groupBy = (url.searchParams.get('groupBy') ?? 'tape_label') as string
  if (!(groupBy in GROUPABLE)) {
    return NextResponse.json(
      { error: `invalid groupBy: ${groupBy}` },
      { status: 400 },
    )
  }
  const date = url.searchParams.get('date') ?? new Date().toISOString().slice(0, 10)
  const clean = url.searchParams.get('clean') === 'true'
  try {
    const result = await query(
      buildRiskConcentrationSql(groupBy as GroupByKey, clean),
      [date],
    )
    return NextResponse.json({ groups: result.rows })
  } catch (error: any) {
    return NextResponse.json(
      { error: error?.message ?? 'failed' },
      { status: 500 },
    )
  }
}
