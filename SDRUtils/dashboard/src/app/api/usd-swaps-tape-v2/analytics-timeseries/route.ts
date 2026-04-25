// GET /api/usd-swaps-tape-v2/analytics-timeseries
// Returns pre-aggregated daily (or intraday) series split into custy + IDB
// platforms, plus daily-summed DV01 for the VOLUME view. Shape is the
// TimeseriesPointAug contract the analytics dock consumes directly.
import { NextResponse } from 'next/server'
import { query } from '@/lib/db'
import {
  platformCaseSql,
  rangeToStartDate,
  rateToBps,
  safeNum,
} from '@/lib/usd-swaps-tape-v2/analytics'

// Phase 2 cutover: analytics-timeseries reads from the v2 leg table so it
// benefits from the new (filter, original_execution_timestamp DESC)
// composite indexes added in _tape_schema_v2.py. v1 stays the rollback
// target; flip this constant to revert.
const LEGS_TABLE = 'arbs_usd_swap_tape_legs_v2'

// Phase 2 cap: at most this many daily rows / intraday ticks per request.
// Daily series LIMIT covers ~5y of trading days; intraday is intrinsically
// bounded by the 72h anchor window and stays at the smaller cap.
const DAILY_ROW_CAP = 2000
const INTRADAY_TICK_CAP = 5000

type DailyRow = {
  day: string
  idb_close: number | null
  custy_close: number | null
  idb_open: number | null
  custy_open: number | null
  idb_high: number | null
  idb_low: number | null
  custy_high: number | null
  custy_low: number | null
  idb_dv01: number | null
  custy_dv01: number | null
  idb_prints: number | null
  custy_prints: number | null
}

type IntradayRow = {
  ts: string
  platform: 'IDB' | 'CUSTY'
  fixed_rate: number | null
  risk: number | null
  notional: number | null
}

export async function GET(req: Request) {
  const { searchParams } = new URL(req.url)
  const value = searchParams.get('value')
  if (!value) {
    return NextResponse.json(
      { error: 'value parameter is required' },
      { status: 400 },
    )
  }
  const view = (searchParams.get('view') ?? 'DAILY_CLOSE').toUpperCase()
  const range = (searchParams.get('range') ?? '1Y').toUpperCase()
  const groupBy = (searchParams.get('groupBy') ?? 'tape_label').toLowerCase()
  const groupCol: Record<string, string> = {
    tape_label: 'l.tape_label',
    package: 'l.package_id',
    trade_type: 'l.trade_type',
    tenor: 'l.tenor_label',
    // Phase 4: canonical underlier key — collapses SDR-feed display
    // variations of the same economic underlier into one bucket. Pass
    // groupBy=canonical with value=USD/SOFR-OIS/COMPOUND etc.
    canonical: 'l.canonical_underlier_key',
  }
  const filterCol = groupCol[groupBy]
  if (!filterCol) {
    return NextResponse.json(
      { error: `invalid groupBy: ${groupBy}` },
      { status: 400 },
    )
  }
  const fromParam = searchParams.get('from')
  const toParam = searchParams.get('to')
  const startDate =
    range === 'CUSTOM' && fromParam ? new Date(fromParam) : rangeToStartDate(range)
  const endDate = range === 'CUSTOM' && toParam ? new Date(toParam) : new Date()

  const platformExpr = platformCaseSql('l')

  try {
    if (view === 'INTRADAY') {
      // Intraday is intrinsically a short-window view — pin the server
      // lookback to the latest N trading-ish days regardless of the
      // client's range selector. Using MAX(execution_timestamp) for the
      // bucket as the anchor keeps the window useful even on weekends
      // when "now - 1 day" would otherwise pre-date the last print.
      const INTRADAY_HOURS = 72
      const intradaySql = `
        WITH anchor AS (
          SELECT COALESCE(MAX(l.original_execution_timestamp), MAX(l.execution_timestamp), NOW()) AS last_ts
          FROM ${LEGS_TABLE} l
          WHERE ${filterCol} = $1 AND NOT COALESCE(l.is_unwind, false)
        )
        SELECT
          COALESCE(l.original_execution_timestamp, l.execution_timestamp) AS ts,
          ${platformExpr} AS platform,
          l.fixed_rate::float AS fixed_rate,
          l.risk::float AS risk,
          l.notional::float AS notional
        FROM ${LEGS_TABLE} l, anchor
        WHERE ${filterCol} = $1
          AND COALESCE(l.original_execution_timestamp, l.execution_timestamp)
              >= anchor.last_ts - INTERVAL '${INTRADAY_HOURS} hours'
          AND l.fixed_rate IS NOT NULL
          AND NOT COALESCE(l.is_unwind, false)
        ORDER BY COALESCE(l.original_execution_timestamp, l.execution_timestamp) ASC
        LIMIT ${INTRADAY_TICK_CAP}
      `
      // startDate/endDate params retained for API shape parity; actual
      // window is anchor-derived above.
      void startDate; void endDate
      const { rows } = await query<IntradayRow>(intradaySql, [value])
      // Project raw ticks onto the TimeseriesPointAug shape — one side
      // of the pair is null when the other platform produced the print.
      // DV01 / notional populated per-tick so the DV01 view gets proper
      // per-print bars without needing a second fetch.
      const points = rows.map((r) => ({
        ts: r.ts,
        idbClose: r.platform === 'IDB' ? rateToBps(r.fixed_rate) : null,
        custyClose: r.platform === 'CUSTY' ? rateToBps(r.fixed_rate) : null,
        idbDv01: r.platform === 'IDB' ? Math.abs(safeNum(r.risk)) : 0,
        custyDv01: r.platform === 'CUSTY' ? Math.abs(safeNum(r.risk)) : 0,
        idbPrints: r.platform === 'IDB' ? 1 : 0,
        custyPrints: r.platform === 'CUSTY' ? 1 : 0,
      }))
      return NextResponse.json({ points, count: points.length, view, range })
    }

    // DAILY_CLOSE / DAILY_OHLC / VOLUME — all share a daily aggregate,
    // extra columns filled in only for the OHLC / VOLUME overlays.
    //
    // Close/open are implemented via array_agg(... ORDER BY ts)[1] so we
    // get "the row that actually closed the day" rather than a numeric
    // MIN/MAX over rates. That keeps sparse days intact: if only one
    // platform printed, the other side stays NULL and the client drops
    // the point from that line instead of drawing to zero.
    const sql = `
      WITH classified AS (
        SELECT
          COALESCE(l.original_execution_timestamp, l.execution_timestamp) AS ts,
          l.fixed_rate::float AS fixed_rate,
          l.risk::float AS risk,
          l.notional::float AS notional,
          ${platformExpr} AS platform,
          DATE_TRUNC(
            'day',
            COALESCE(l.original_execution_timestamp, l.execution_timestamp)
              AT TIME ZONE 'America/New_York'
          ) AS day
        FROM ${LEGS_TABLE} l
        WHERE ${filterCol} = $1
          AND COALESCE(l.original_execution_timestamp, l.execution_timestamp)
              >= $2::timestamptz
          AND COALESCE(l.original_execution_timestamp, l.execution_timestamp)
              <= $3::timestamptz
          AND NOT COALESCE(l.is_unwind, false)
      ),
      per_day_platform AS (
        SELECT
          day,
          platform,
          (array_agg(fixed_rate ORDER BY ts DESC)
            FILTER (WHERE fixed_rate IS NOT NULL))[1] AS close_rate,
          (array_agg(fixed_rate ORDER BY ts ASC)
            FILTER (WHERE fixed_rate IS NOT NULL))[1] AS open_rate,
          MAX(fixed_rate) AS high_rate,
          MIN(fixed_rate) AS low_rate,
          SUM(ABS(risk)) AS daily_dv01,
          SUM(ABS(notional)) AS daily_notional,
          COUNT(*) AS prints
        FROM classified
        GROUP BY day, platform
      )
      SELECT
        day,
        MAX(close_rate) FILTER (WHERE platform = 'IDB')   AS idb_close,
        MAX(close_rate) FILTER (WHERE platform = 'CUSTY') AS custy_close,
        MAX(open_rate)  FILTER (WHERE platform = 'IDB')   AS idb_open,
        MAX(open_rate)  FILTER (WHERE platform = 'CUSTY') AS custy_open,
        MAX(high_rate)  FILTER (WHERE platform = 'IDB')   AS idb_high,
        MIN(low_rate)   FILTER (WHERE platform = 'IDB')   AS idb_low,
        MAX(high_rate)  FILTER (WHERE platform = 'CUSTY') AS custy_high,
        MIN(low_rate)   FILTER (WHERE platform = 'CUSTY') AS custy_low,
        COALESCE(MAX(daily_dv01) FILTER (WHERE platform = 'IDB'),   0) AS idb_dv01,
        COALESCE(MAX(daily_dv01) FILTER (WHERE platform = 'CUSTY'), 0) AS custy_dv01,
        COALESCE(MAX(prints)     FILTER (WHERE platform = 'IDB'),   0) AS idb_prints,
        COALESCE(MAX(prints)     FILTER (WHERE platform = 'CUSTY'), 0) AS custy_prints
      FROM per_day_platform
      GROUP BY day
      ORDER BY day ASC
      LIMIT ${DAILY_ROW_CAP}
    `
    const { rows } = await query<DailyRow>(sql, [
      value,
      startDate.toISOString(),
      endDate.toISOString(),
    ])
    const points = rows.map((r) => ({
      ts: typeof r.day === 'string' ? r.day : new Date(r.day as unknown as Date).toISOString(),
      idbClose: r.idb_close != null ? rateToBps(r.idb_close) : null,
      custyClose: r.custy_close != null ? rateToBps(r.custy_close) : null,
      open: r.idb_open != null ? rateToBps(r.idb_open) : null,
      high: r.idb_high != null ? rateToBps(r.idb_high) : null,
      low: r.idb_low != null ? rateToBps(r.idb_low) : null,
      close: r.idb_close != null ? rateToBps(r.idb_close) : null,
      idbDv01: safeNum(r.idb_dv01),
      custyDv01: safeNum(r.custy_dv01),
      idbPrints: safeNum(r.idb_prints),
      custyPrints: safeNum(r.custy_prints),
    }))
    return NextResponse.json({ points, count: points.length, view, range })
  } catch (error) {
    console.error('usd-swaps-tape-v2/analytics-timeseries error', error)
    const message = error instanceof Error ? error.message : 'Failed to fetch timeseries'
    return NextResponse.json({ error: message }, { status: 500 })
  }
}
