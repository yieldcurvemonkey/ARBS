// GET /api/usd-swaps-tape-v2/analytics-timeseries
// Returns pre-aggregated daily (or intraday) series split into custy + IDB
// platforms, plus daily-summed DV01 for the VOLUME view. Shape is the
// TimeseriesPointAug contract the analytics dock consumes directly.
import { NextResponse } from 'next/server'
import { query } from '@/lib/db'
import {
  packageAnalyticsCtes,
  packageAnalyticsFilterPredicate,
  rangeToStartDate,
  rateToBps,
  safeNum,
} from '@/lib/usd-swaps-tape-v2/analytics'

// Phase 2 cutover: analytics-timeseries reads from the v2 leg table so it
// benefits from the new (filter, original_execution_timestamp DESC)
// composite indexes added in _tape_schema_v2.py. v1 stays the rollback
// target; flip this constant to revert.
const LEGS_TABLE = 'arbs_usd_swap_tape_legs_v2'
const PACKAGES_TABLE = 'arbs_usd_swap_tape_packages_v2'

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
  idb_notional: number | null
  custy_notional: number | null
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

export function parseBooleanParam(
  searchParams: URLSearchParams,
  key: string,
  defaultValue: boolean,
): boolean {
  const raw = searchParams.get(key)
  if (raw == null) return defaultValue
  const normalized = raw.trim().toLowerCase()
  if (['true', '1', 'yes', 'y'].includes(normalized)) return true
  if (['false', '0', 'no', 'n'].includes(normalized)) return false
  return defaultValue
}

export function riskAggregateExpression(useGrossDv01: boolean): string {
  return useGrossDv01 ? 'SUM(ABS(risk))' : 'SUM(risk)'
}

export function custyNotionalOutlierPredicate(
  rowAlias: string,
  thresholdAlias: string,
  excludeLargeCusty: boolean,
): string {
  if (!excludeLargeCusty) return 'TRUE'
  return `NOT (
            ${rowAlias}.platform = 'CUSTY'
            AND ${thresholdAlias}.median_notional IS NOT NULL
            AND ${thresholdAlias}.median_notional > 0
            AND ABS(COALESCE(${rowAlias}.notional, 0)) > ${thresholdAlias}.median_notional * 5
          )`
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
  const useGrossDv01 = parseBooleanParam(searchParams, 'useGrossDv01', false)
  const excludeLargeCusty = parseBooleanParam(searchParams, 'excludeLargeCusty', true)
  const filterPredicate = packageAnalyticsFilterPredicate(groupBy, '$1', LEGS_TABLE)
  if (!filterPredicate) {
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

  const riskAgg = riskAggregateExpression(useGrossDv01)
  const outlierPredicate = custyNotionalOutlierPredicate('b', 't', excludeLargeCusty)

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
          SELECT COALESCE(MAX(COALESCE(p.original_execution_start, p.execution_start)), NOW()) AS last_ts
          FROM ${PACKAGES_TABLE} p
          WHERE ${filterPredicate}
            AND NOT COALESCE(p.is_unwind, false)
        ),
        ${packageAnalyticsCtes({
          packagesTable: PACKAGES_TABLE,
          legsTable: LEGS_TABLE,
          filterPredicate,
          timePredicate: `COALESCE(p.original_execution_start, p.execution_start)
                >= (SELECT last_ts FROM anchor) - INTERVAL '${INTRADAY_HOURS} hours'`,
        })},
        custy_threshold AS (
          SELECT
            percentile_cont(0.5) WITHIN GROUP (ORDER BY ABS(notional)) AS median_notional
          FROM package_summary
          WHERE platform = 'CUSTY' AND notional IS NOT NULL
        )
        SELECT
          b.ts,
          b.platform,
          b.fixed_rate,
          b.risk,
          b.notional
        FROM package_summary b
        CROSS JOIN custy_threshold t
        WHERE ${outlierPredicate}
        ORDER BY b.ts ASC
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
        idbDv01: r.platform === 'IDB'
          ? useGrossDv01 ? Math.abs(safeNum(r.risk)) : safeNum(r.risk)
          : 0,
        custyDv01: r.platform === 'CUSTY'
          ? useGrossDv01 ? Math.abs(safeNum(r.risk)) : safeNum(r.risk)
          : 0,
        idbNotional: r.platform === 'IDB' ? Math.abs(safeNum(r.notional)) : 0,
        custyNotional: r.platform === 'CUSTY' ? Math.abs(safeNum(r.notional)) : 0,
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
      WITH ${packageAnalyticsCtes({
        packagesTable: PACKAGES_TABLE,
        legsTable: LEGS_TABLE,
        filterPredicate,
        timePredicate: `COALESCE(p.original_execution_start, p.execution_start)
              >= $2::timestamptz
          AND COALESCE(p.original_execution_start, p.execution_start)
              <= $3::timestamptz`,
      })},
      base AS (
        SELECT
          ts,
          fixed_rate,
          risk,
          notional,
          platform,
          DATE_TRUNC('day', ts AT TIME ZONE 'America/New_York') AS day
        FROM package_summary
      ),
      custy_threshold AS (
        SELECT
          percentile_cont(0.5) WITHIN GROUP (ORDER BY ABS(notional)) AS median_notional
        FROM base
        WHERE platform = 'CUSTY' AND notional IS NOT NULL
      ),
      classified AS (
        SELECT b.*
        FROM base b
        CROSS JOIN custy_threshold t
        WHERE ${outlierPredicate}
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
          ${riskAgg} AS daily_dv01,
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
        COALESCE(MAX(daily_notional) FILTER (WHERE platform = 'IDB'),   0) AS idb_notional,
        COALESCE(MAX(daily_notional) FILTER (WHERE platform = 'CUSTY'), 0) AS custy_notional,
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
      idbNotional: safeNum(r.idb_notional),
      custyNotional: safeNum(r.custy_notional),
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
