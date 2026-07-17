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
    ? `AND COALESCE(l.original_execution_timestamp, l.execution_timestamp) >= (NOW() - INTERVAL '${windowHours} hours')`
    : isMultiDay
      ? `AND l.as_of_date >= ($1::date - INTERVAL '4 days') AND l.as_of_date <= $1::date`
      : `AND l.as_of_date = $1::date`

  const todaySql = `
    SELECT
      ${fwdCase} AS fwd,
      ${tenorCase} AS tenor,
      SUM(ABS(l.risk::float)) AS dv01,
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
        SUM(ABS(l.risk::float)) AS daily_dv01
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
      AVG(daily_dv01) AS avg_dv01,
      STDDEV_POP(daily_dv01) AS std_dv01,
      COUNT(DISTINCT as_of_date) AS n_days
    FROM daily
    GROUP BY fwd, tenor
  `

  try {
    const [todayRes, histRes] = await Promise.all([
      query(todaySql, [date]),
      query(histSql, [date]),
    ])

    const histMap = new Map<string, { avg_dv01: number; std_dv01: number; n_days: number }>()
    for (const r of histRes.rows) {
      histMap.set(`${r.fwd}|${r.tenor}`, {
        avg_dv01: Number(r.avg_dv01) || 0,
        std_dv01: Number(r.std_dv01) || 0,
        n_days: Number(r.n_days) || 0,
      })
    }

    const cells = todayRes.rows.map((r: any) => {
      const key = `${r.fwd}|${r.tenor}`
      const hist = histMap.get(key)
      const dv01 = Number(r.dv01) || 0
      const avg = hist?.avg_dv01 ?? 0
      const std = hist?.std_dv01 ?? 0
      const z = std > 0 ? (dv01 - avg) / std : 0
      return {
        fwd: r.fwd,
        tenor: r.tenor,
        dv01,
        trade_count: Number(r.trade_count) || 0,
        hist_avg: avg,
        hist_std: std,
        z_score: Math.round(z * 100) / 100,
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
