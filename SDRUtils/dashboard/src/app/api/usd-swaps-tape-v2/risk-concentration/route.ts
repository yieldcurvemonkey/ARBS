// ABOUTME: GET /api/usd-swaps-tape-v2/risk-concentration — grouped DV01 aggregation.
import { NextResponse } from 'next/server'
import { query } from '@/lib/db'
import {
  buildRiskConcentrationSql,
  type GroupByKey,
  GROUPABLE,
} from './route.logic'

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
