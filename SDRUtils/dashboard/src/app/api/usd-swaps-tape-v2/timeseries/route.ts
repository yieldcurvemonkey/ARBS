// ABOUTME: Legacy raw-tick timeseries route, with groupBy extension.
import { NextResponse } from 'next/server'
import { query } from '@/lib/db'
import { TAPE_LEGS } from '@/lib/tape-tables'

const MAX_TIMESERIES_ROWS = 50_000
const LEGS_TABLE = TAPE_LEGS

const GROUP_BY_COLUMN: Record<string, string> = {
  package: 'l.package_id',
  tape_label: 'l.tape_label',
  trade_type: 'l.trade_type',
  tenor: 'l.tenor_label',
  // Phase 4 canonical underlier (see SDRUtils/core/underlier_canonical.py).
  canonical: 'l.canonical_underlier_key',
}

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url)
  const groupByRaw = (searchParams.get('groupBy') ?? 'package').toLowerCase()
  const column = GROUP_BY_COLUMN[groupByRaw]
  if (!column) {
    return NextResponse.json(
      { error: `invalid groupBy: ${groupByRaw}` },
      { status: 400 },
    )
  }
  const value = searchParams.get('value')
  if (!value) {
    return NextResponse.json(
      { error: 'value parameter is required' },
      { status: 400 },
    )
  }
  const metric = searchParams.get('metric') ?? 'risk'
  const range = searchParams.get('range') ?? '1D'

  try {
    const params: unknown[] = [value]
    const now = new Date()
    let startDate = new Date(now)
    if (range === '1D') startDate.setUTCDate(now.getUTCDate() - 1)
    else if (range === '1W') startDate.setUTCDate(now.getUTCDate() - 7)
    else if (range === '1M') startDate.setUTCMonth(now.getUTCMonth() - 1)
    else startDate = new Date('2020-01-01')
    params.push(startDate.toISOString())

    const metricExpr = (() => {
      switch (metric) {
        case 'notional':
          return 'l.notional::float'
        case 'risk':
          return 'l.risk::float'
        case 'fixed_rate':
          return 'l.fixed_rate::float'
        case 'trade_count':
          return '1::float'
        default:
          return 'l.risk::float'
      }
    })()

    const sql = `
      SELECT
        COALESCE(l.original_execution_timestamp, l.execution_timestamp) AS ts,
        ${metricExpr} AS value,
        l.notional::float AS notional,
        l.risk::float AS risk,
        l.fixed_rate::float AS fixed_rate,
        l.trade_id AS trade_id,
        l.package_id AS package_id,
        l.tape_label AS tape_label,
        l.tenor_label AS tenor_label,
        l.trade_type AS trade_type
      FROM ${LEGS_TABLE} l
      WHERE ${column} = $1
        AND COALESCE(l.original_execution_timestamp, l.execution_timestamp) >= $2::timestamptz
      ORDER BY COALESCE(l.original_execution_timestamp, l.execution_timestamp) ASC
      LIMIT ${MAX_TIMESERIES_ROWS}
    `
    const result = await query(sql, params)
    const rows = result.rows
    return NextResponse.json({
      rows,
      points: rows.map((r: any) => ({
        ts: r.ts,
        value: r.value,
        notional: r.notional,
        risk: r.risk,
        fixed_rate: r.fixed_rate,
      })),
      count: rows.length,
      truncated: rows.length >= MAX_TIMESERIES_ROWS,
      groupBy: groupByRaw,
      value,
      metric,
      range,
    })
  } catch (error: any) {
    console.error('usd-swaps-tape-v2/timeseries GET error', error)
    return NextResponse.json(
      { error: error?.message || 'Failed to fetch timeseries' },
      { status: 500 },
    )
  }
}
