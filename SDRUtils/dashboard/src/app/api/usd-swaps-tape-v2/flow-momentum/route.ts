import { NextResponse } from 'next/server'
import { query } from '@/lib/db'
import {
  buildBucketCaseSql,
  resolveForwardSchema,
  resolveTenorSchema,
} from '@/lib/usd-swaps-tape-v2/volumeGridBuckets'

const LEGS_TABLE = 'arbs_usd_swap_tape_legs_v2'

const WINDOW_HOURS: Record<string, number | null> = {
  '1h': 1,
  '4h': 4,
  today: null,
  '5d': null,
}

export async function GET(req: Request) {
  const url = new URL(req.url)
  const date = url.searchParams.get('date') ?? new Date().toISOString().slice(0, 10)
  const window = url.searchParams.get('window') ?? 'today'
  const histDays = parseInt(url.searchParams.get('histDays') ?? '20', 10)

  const fwdSchema = resolveForwardSchema('default')
  const tenorSchema = resolveTenorSchema('default')
  const fwdCase = buildBucketCaseSql('l', 'forward_start_years', fwdSchema.buckets)
  const tenorCase = buildBucketCaseSql('l', 'tenor_years', tenorSchema.buckets)

  const windowHours = WINDOW_HOURS[window]
  const isMultiDay = window === '5d'

  const timePredicate = windowHours != null
    ? `AND l.execution_timestamp >= (NOW() - INTERVAL '${windowHours} hours')`
    : isMultiDay
      ? `AND l.as_of_date >= ($1::date - INTERVAL '4 days') AND l.as_of_date <= $1::date`
      : `AND l.as_of_date = $1::date`

  const todaySql = `
    SELECT
      ${fwdCase} AS fwd,
      ${tenorCase} AS tenor,
      SUM(l.risk::float) AS net_dv01,
      SUM(ABS(l.risk::float)) AS gross_dv01,
      SUM(CASE WHEN l.risk::float > 0 THEN 1 ELSE 0 END) AS pay_count,
      SUM(CASE WHEN l.risk::float < 0 THEN 1 ELSE 0 END) AS rcv_count,
      COUNT(*) AS trade_count
    FROM ${LEGS_TABLE} l
    WHERE l.contributes_to_flow = TRUE
      AND l.risk IS NOT NULL
      ${timePredicate}
    GROUP BY 1, 2
    HAVING ${fwdCase} <> 'other' AND ${tenorCase} <> 'other'
    ORDER BY 1, 2
  `

  const histSql = `
    WITH daily AS (
      SELECT
        l.as_of_date,
        ${fwdCase} AS fwd,
        ${tenorCase} AS tenor,
        SUM(l.risk::float) AS daily_net
      FROM ${LEGS_TABLE} l
      WHERE l.contributes_to_flow = TRUE
        AND l.risk IS NOT NULL
        AND l.as_of_date >= ($1::date - INTERVAL '${histDays} days')
        AND l.as_of_date < $1::date
      GROUP BY 1, 2, 3
      HAVING ${fwdCase} <> 'other' AND ${tenorCase} <> 'other'
    )
    SELECT
      fwd,
      tenor,
      AVG(daily_net) AS avg_net,
      STDDEV_POP(daily_net) AS std_net,
      COUNT(DISTINCT as_of_date) AS n_days
    FROM daily
    GROUP BY fwd, tenor
  `

  try {
    const [todayRes, histRes] = await Promise.all([
      query(todaySql, [date]),
      query(histSql, [date]),
    ])

    const histMap = new Map<string, { avg_net: number; std_net: number; n_days: number }>()
    for (const r of histRes.rows) {
      histMap.set(`${r.fwd}|${r.tenor}`, {
        avg_net: Number(r.avg_net) || 0,
        std_net: Number(r.std_net) || 0,
        n_days: Number(r.n_days) || 0,
      })
    }

    const cells = todayRes.rows.map((r: any) => {
      const key = `${r.fwd}|${r.tenor}`
      const hist = histMap.get(key)
      const net = Number(r.net_dv01) || 0
      const avg = hist?.avg_net ?? 0
      const std = hist?.std_net ?? 0
      const z = std > 0 ? (net - avg) / std : 0
      return {
        fwd: r.fwd,
        tenor: r.tenor,
        net_dv01: net,
        gross_dv01: Number(r.gross_dv01) || 0,
        pay_count: Number(r.pay_count) || 0,
        rcv_count: Number(r.rcv_count) || 0,
        trade_count: Number(r.trade_count) || 0,
        hist_avg: avg,
        hist_std: std,
        z_score: Math.round(z * 100) / 100,
        dominant_side: net > 0 ? 'PAY' : net < 0 ? 'RCV' : 'NEUTRAL',
      }
    })

    const fwdBuckets = fwdSchema.buckets.map(b => ({ id: b.id, label: b.label }))
    const tenorBuckets = tenorSchema.buckets.map(b => ({ id: b.id, label: b.label }))

    return NextResponse.json(
      { cells, fwdBuckets, tenorBuckets, date, window },
      { headers: { 'Cache-Control': 'private, max-age=30, stale-while-revalidate=60' } },
    )
  } catch (error: any) {
    return NextResponse.json({ error: error?.message ?? 'failed' }, { status: 500 })
  }
}
