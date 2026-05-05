// ABOUTME: Pure helpers for /api/usd-swaps-tape-v2/volume-grid. Split out
// from route.ts so SQL construction, parameter parsing, percentile math,
// and totals aggregation can be unit-tested without spinning up a DB.
//
// Two window-comparison modes:
//   - time_of_day: today vs prior days at the same time-of-day in ET
//     (used for periods 'today' and '1h'). Today's cumulative-since-midnight
//     (or last-1h slot) is ranked against prior days' cumulative-up-to-the-
//     same-time-of-day (or same 1h slot of prior days). Mirrors the
//     swaptions-tape intraday-pace pattern.
//   - rolling: today's last 24h or 7d vs prior 24h/7d windows shifted in
//     time (used for periods '24h' and '1w'). Time-of-day is meaningless
//     for these because the window crosses days.

import { buildBucketSqlCases } from '@/lib/usd-swaps-tape-v2/volumeGridBuckets'
import type {
  VolumeGridCell,
  VolumeMetric,
  VolumePeriod,
  VolumeGridResponse,
} from '@/features/usd-swaps-tape-v2/types/volume-grid.types'

export interface VolumeGridParams {
  metric: VolumeMetric
  period: VolumePeriod
  lookbackDays: number
}

export type ParseResult<T> =
  | { ok: true; value: T }
  | { ok: false; error: string }

const VALID_METRICS: ReadonlySet<VolumeMetric> = new Set(['notional', 'dv01'])
const VALID_PERIODS: ReadonlySet<VolumePeriod> = new Set(['today', '1h', '24h', '1w'])

export function parseVolumeGridParams(search: URLSearchParams): ParseResult<VolumeGridParams> {
  const metricRaw = (search.get('metric') ?? 'notional').toLowerCase()
  const periodRaw = (search.get('period') ?? 'today').toLowerCase()
  const lookbackRaw = search.get('lookbackDays')
  if (!VALID_METRICS.has(metricRaw as VolumeMetric)) {
    return { ok: false, error: `metric must be one of ${[...VALID_METRICS].join(', ')}` }
  }
  if (!VALID_PERIODS.has(periodRaw as VolumePeriod)) {
    return { ok: false, error: `period must be one of ${[...VALID_PERIODS].join(', ')}` }
  }
  let lookbackDays = 90
  if (lookbackRaw != null) {
    const n = Number(lookbackRaw)
    if (!Number.isFinite(n) || n < 1 || n > 365) {
      return { ok: false, error: 'lookbackDays must be 1..365' }
    }
    lookbackDays = Math.floor(n)
  }
  return {
    ok: true,
    value: {
      metric: metricRaw as VolumeMetric,
      period: periodRaw as VolumePeriod,
      lookbackDays,
    },
  }
}

export type WindowBounds =
  | {
      kind: 'time_of_day'
      lookbackStart: Date
      lookbackEnd: Date
      /** Today's calendar date in America/New_York, formatted YYYY-MM-DD. */
      todayDateEt: string
      /** Inclusive lower bound of the time-of-day filter, in seconds since local midnight ET. */
      todSecondsLo: number
      /** Inclusive upper bound of the time-of-day filter, in seconds since local midnight ET. */
      todSecondsHi: number
    }
  | {
      kind: 'rolling'
      lookbackStart: Date
      lookbackEnd: Date
      currentStart: Date
      windowIdSql: string
    }

const ONE_HOUR_MS = 60 * 60 * 1000
const ONE_DAY_MS = 24 * ONE_HOUR_MS
const ONE_HOUR_S = 60 * 60
const ONE_DAY_S = 24 * ONE_HOUR_S

/**
 * Compute today's calendar date and seconds-of-day in America/New_York
 * from a UTC `Date`. Uses Intl to handle DST so callers don't have to.
 */
export function timeOfDayInEt(now: Date): { dateEt: string; todSeconds: number } {
  const fmt = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'America/New_York',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  })
  const parts = fmt.formatToParts(now)
  const get = (type: string): string => parts.find((p) => p.type === type)?.value ?? '0'
  const year = get('year')
  const month = get('month')
  const day = get('day')
  // Intl en-CA can emit '24' for hour at midnight on some runtimes; normalise.
  const hour = parseInt(get('hour'), 10) % 24
  const minute = parseInt(get('minute'), 10)
  const second = parseInt(get('second'), 10)
  return {
    dateEt: `${year}-${month}-${day}`,
    todSeconds: hour * 3600 + minute * 60 + second,
  }
}

export function computeWindowBounds(
  period: VolumePeriod,
  lookbackDays: number,
  now: Date = new Date(),
): WindowBounds {
  const lookbackEnd = now
  switch (period) {
    case 'today': {
      const { dateEt, todSeconds } = timeOfDayInEt(now)
      const lookbackStart = new Date(now.getTime() - lookbackDays * ONE_DAY_MS)
      return {
        kind: 'time_of_day',
        lookbackStart,
        lookbackEnd,
        todayDateEt: dateEt,
        todSecondsLo: 0,
        todSecondsHi: todSeconds,
      }
    }
    case '1h': {
      const { dateEt, todSeconds } = timeOfDayInEt(now)
      const lookbackStart = new Date(now.getTime() - lookbackDays * ONE_DAY_MS)
      return {
        kind: 'time_of_day',
        lookbackStart,
        lookbackEnd,
        todayDateEt: dateEt,
        todSecondsLo: Math.max(0, todSeconds - ONE_HOUR_S),
        todSecondsHi: todSeconds,
      }
    }
    case '24h': {
      const lookbackStart = new Date(now.getTime() - lookbackDays * ONE_DAY_MS)
      return {
        kind: 'rolling',
        lookbackStart,
        lookbackEnd,
        currentStart: new Date(now.getTime() - 24 * ONE_HOUR_MS),
        windowIdSql: `date_trunc('day', ts AT TIME ZONE 'America/New_York')`,
      }
    }
    case '1w': {
      // 52 weeks of weekly samples regardless of lookbackDays input.
      const lookbackStart = new Date(now.getTime() - 52 * 7 * ONE_DAY_MS)
      return {
        kind: 'rolling',
        lookbackStart,
        lookbackEnd,
        currentStart: new Date(now.getTime() - 7 * ONE_DAY_MS),
        windowIdSql: `date_trunc('week', ts AT TIME ZONE 'America/New_York')`,
      }
    }
  }
}

/**
 * Build the SQL for a time-of-day comparison ('today' / '1h').
 *
 * Bind order:
 *   $1 = lookbackStart timestamptz
 *   $2 = lookbackEnd   timestamptz
 *   $3 = todayDateEt   date         (today in America/New_York)
 *   $4 = todSecondsLo  numeric      (seconds since local midnight ET)
 *   $5 = todSecondsHi  numeric      (seconds since local midnight ET)
 *
 * Each prior day in [lookbackStart, todayDateEt) contributes one
 * `window_value` per (fwd, tenor) bucket: the SUM(metric) of trades
 * whose time-of-day in ET falls in [todSecondsLo, todSecondsHi].
 * Today contributes the same SUM over the same time-of-day range —
 * that becomes `current_value`.
 */
export function buildVolumeGridSqlTimeOfDay(metric: VolumeMetric): string {
  const { fwdCase, tenorCase } = buildBucketSqlCases('l')
  const metricCol = metric === 'notional' ? 'gross_notional' : 'gross_dv01'
  return `
    WITH legs AS (
      SELECT
        COALESCE(l.original_execution_timestamp, l.execution_timestamp) AS ts,
        ABS(COALESCE(l.notional, 0)) AS gross_notional,
        ABS(COALESCE(l.risk, 0))     AS gross_dv01,
        ${fwdCase} AS fwd_bucket,
        ${tenorCase} AS tenor_bucket,
        (date_trunc('day', COALESCE(l.original_execution_timestamp, l.execution_timestamp) AT TIME ZONE 'America/New_York'))::date AS day_et,
        EXTRACT(EPOCH FROM (
          (COALESCE(l.original_execution_timestamp, l.execution_timestamp) AT TIME ZONE 'America/New_York')
          - date_trunc('day', COALESCE(l.original_execution_timestamp, l.execution_timestamp) AT TIME ZONE 'America/New_York')
        )) AS tod_seconds_et
      FROM arbs_usd_swap_tape_legs_v2 l
      WHERE COALESCE(l.contributes_to_flow, FALSE) = TRUE
        AND COALESCE(l.original_execution_timestamp, l.execution_timestamp) >= $1::timestamptz
        AND COALESCE(l.original_execution_timestamp, l.execution_timestamp) <  $2::timestamptz
    ),
    bucketed AS (
      SELECT * FROM legs
      WHERE fwd_bucket <> 'fwd_other'
        AND tenor_bucket IS NOT NULL
        AND tod_seconds_et >= $4::numeric
        AND tod_seconds_et <= $5::numeric
    ),
    prior_per_day AS (
      SELECT fwd_bucket, tenor_bucket, day_et,
        SUM(${metricCol}) AS window_value
      FROM bucketed
      WHERE day_et < $3::date
      GROUP BY fwd_bucket, tenor_bucket, day_et
    ),
    prior_summary AS (
      SELECT fwd_bucket, tenor_bucket,
        array_agg(window_value ORDER BY window_value) AS prior_array,
        percentile_cont(0.25) WITHIN GROUP (ORDER BY window_value) AS p25,
        percentile_cont(0.50) WITHIN GROUP (ORDER BY window_value) AS p50,
        percentile_cont(0.75) WITHIN GROUP (ORDER BY window_value) AS p75,
        MIN(window_value) AS pmin,
        MAX(window_value) AS pmax,
        COUNT(*)::int AS n
      FROM prior_per_day
      GROUP BY fwd_bucket, tenor_bucket
    ),
    current_agg AS (
      SELECT fwd_bucket, tenor_bucket,
        SUM(${metricCol}) AS current_value,
        COUNT(*)::int AS trade_count,
        MAX(ts) AS last_ts
      FROM bucketed
      WHERE day_et = $3::date
      GROUP BY fwd_bucket, tenor_bucket
    )
    SELECT
      COALESCE(c.fwd_bucket, p.fwd_bucket)     AS fwd,
      COALESCE(c.tenor_bucket, p.tenor_bucket) AS tenor,
      COALESCE(c.current_value, 0)             AS current_value,
      COALESCE(c.trade_count, 0)               AS trade_count,
      COALESCE(p.prior_array, ARRAY[]::numeric[]) AS prior_array,
      COALESCE(p.p25, 0)  AS p25,
      COALESCE(p.p50, 0)  AS p50,
      COALESCE(p.p75, 0)  AS p75,
      COALESCE(p.pmin, 0) AS pmin,
      COALESCE(p.pmax, 0) AS pmax,
      COALESCE(p.n, 0)    AS n,
      MAX(c.last_ts) OVER () AS as_of_ts
    FROM current_agg c
    FULL OUTER JOIN prior_summary p USING (fwd_bucket, tenor_bucket)
  `
}

/**
 * Build the SQL for a rolling-window comparison ('24h' / '1w').
 *
 * Bind order:
 *   $1 = lookbackStart timestamptz
 *   $2 = lookbackEnd   timestamptz
 *   $3 = currentStart  timestamptz (rows >= this are 'current')
 *
 * The window-id SQL fragment (e.g. `date_trunc('day', ...)`) is inlined
 * via the `%WINDOW_ID_SQL%` placeholder by the route handler.
 */
export function buildVolumeGridSqlRolling(metric: VolumeMetric): string {
  const { fwdCase, tenorCase } = buildBucketSqlCases('l')
  const metricCol = metric === 'notional' ? 'gross_notional' : 'gross_dv01'
  return `
    WITH legs AS (
      SELECT
        COALESCE(l.original_execution_timestamp, l.execution_timestamp) AS ts,
        ABS(COALESCE(l.notional, 0)) AS gross_notional,
        ABS(COALESCE(l.risk, 0))     AS gross_dv01,
        ${fwdCase} AS fwd_bucket,
        ${tenorCase} AS tenor_bucket
      FROM arbs_usd_swap_tape_legs_v2 l
      WHERE COALESCE(l.contributes_to_flow, FALSE) = TRUE
        AND COALESCE(l.original_execution_timestamp, l.execution_timestamp) >= $1::timestamptz
        AND COALESCE(l.original_execution_timestamp, l.execution_timestamp) <  $2::timestamptz
    ),
    bucketed AS (
      SELECT * FROM legs
      WHERE fwd_bucket <> 'fwd_other'
        AND tenor_bucket IS NOT NULL
    ),
    windowed AS (
      SELECT *,
        CASE
          WHEN ts >= $3::timestamptz THEN 'current'
          ELSE 'baseline'
        END AS window_kind,
        %WINDOW_ID_SQL% AS baseline_window_id
      FROM bucketed
    ),
    prior_per_window AS (
      SELECT fwd_bucket, tenor_bucket, baseline_window_id,
        SUM(${metricCol}) AS window_value
      FROM windowed
      WHERE window_kind = 'baseline'
      GROUP BY fwd_bucket, tenor_bucket, baseline_window_id
    ),
    prior_summary AS (
      SELECT fwd_bucket, tenor_bucket,
        array_agg(window_value ORDER BY window_value) AS prior_array,
        percentile_cont(0.25) WITHIN GROUP (ORDER BY window_value) AS p25,
        percentile_cont(0.50) WITHIN GROUP (ORDER BY window_value) AS p50,
        percentile_cont(0.75) WITHIN GROUP (ORDER BY window_value) AS p75,
        MIN(window_value) AS pmin,
        MAX(window_value) AS pmax,
        COUNT(*)::int AS n
      FROM prior_per_window
      GROUP BY fwd_bucket, tenor_bucket
    ),
    current_agg AS (
      SELECT fwd_bucket, tenor_bucket,
        SUM(${metricCol}) AS current_value,
        COUNT(*)::int AS trade_count,
        MAX(ts) AS last_ts
      FROM windowed
      WHERE window_kind = 'current'
      GROUP BY fwd_bucket, tenor_bucket
    )
    SELECT
      COALESCE(c.fwd_bucket, p.fwd_bucket)     AS fwd,
      COALESCE(c.tenor_bucket, p.tenor_bucket) AS tenor,
      COALESCE(c.current_value, 0)             AS current_value,
      COALESCE(c.trade_count, 0)               AS trade_count,
      COALESCE(p.prior_array, ARRAY[]::numeric[]) AS prior_array,
      COALESCE(p.p25, 0)  AS p25,
      COALESCE(p.p50, 0)  AS p50,
      COALESCE(p.p75, 0)  AS p75,
      COALESCE(p.pmin, 0) AS pmin,
      COALESCE(p.pmax, 0) AS pmax,
      COALESCE(p.n, 0)    AS n,
      MAX(c.last_ts) OVER () AS as_of_ts
    FROM current_agg c
    FULL OUTER JOIN prior_summary p USING (fwd_bucket, tenor_bucket)
  `
}

/** Dispatches to the right SQL builder based on bounds.kind. */
export function buildVolumeGridSql(metric: VolumeMetric, bounds: WindowBounds): string {
  return bounds.kind === 'time_of_day'
    ? buildVolumeGridSqlTimeOfDay(metric)
    : buildVolumeGridSqlRolling(metric)
}

export function computePercentile(current: number, prior: ReadonlyArray<number>): number | null {
  if (prior.length === 0) return null
  let lessOrEqual = 0
  for (const v of prior) if (v <= current) lessOrEqual += 1
  return (lessOrEqual / prior.length) * 100
}

export function summariseCells(
  cells: ReadonlyArray<VolumeGridCell>,
): VolumeGridResponse['totals'] {
  const rowTotals: Record<string, { current: number }> = {}
  const colTotals: Record<string, { current: number }> = {}
  let grandCurrent = 0
  for (const c of cells) {
    if (!rowTotals[c.fwd]) rowTotals[c.fwd] = { current: 0 }
    if (!colTotals[c.tenor]) colTotals[c.tenor] = { current: 0 }
    rowTotals[c.fwd].current += c.current
    colTotals[c.tenor].current += c.current
    grandCurrent += c.current
  }
  const wrap = (entry: { current: number }) => ({
    current: entry.current,
    percentile: null as number | null,
  })
  return {
    rowTotals: Object.fromEntries(
      Object.entries(rowTotals).map(([k, v]) => [k, wrap(v)]),
    ),
    colTotals: Object.fromEntries(
      Object.entries(colTotals).map(([k, v]) => [k, wrap(v)]),
    ),
    grand: { current: grandCurrent, percentile: null },
  }
}

export interface RawVolumeGridRow {
  fwd: string
  tenor: string
  current_value: number | string
  trade_count: number | string
  prior_array: Array<number | string>
  p25: number | string
  p50: number | string
  p75: number | string
  pmin: number | string
  pmax: number | string
  n: number | string
  as_of_ts: string | Date | null
}

const num = (v: unknown): number => {
  const n = typeof v === 'number' ? v : Number(v)
  return Number.isFinite(n) ? n : 0
}

export function shapeVolumeGridResponse(
  rows: ReadonlyArray<RawVolumeGridRow>,
  params: VolumeGridParams,
): VolumeGridResponse {
  const cells: VolumeGridCell[] = rows
    .filter((r) => r.fwd !== 'fwd_other' && r.tenor !== null && r.tenor !== '')
    .map((r) => {
      const prior = r.prior_array.map(num)
      const current = num(r.current_value)
      return {
        fwd: r.fwd as VolumeGridCell['fwd'],
        tenor: r.tenor as VolumeGridCell['tenor'],
        current,
        tradeCount: num(r.trade_count),
        baseline: {
          p25: num(r.p25),
          p50: num(r.p50),
          p75: num(r.p75),
          min: num(r.pmin),
          max: num(r.pmax),
          n: num(r.n),
        },
        percentile: computePercentile(current, prior),
      }
    })
  const totals = summariseCells(cells)
  const asOf = (() => {
    const raw = rows[0]?.as_of_ts
    if (!raw) return new Date().toISOString()
    if (raw instanceof Date) return raw.toISOString()
    return new Date(String(raw)).toISOString()
  })()
  return {
    asOf,
    metric: params.metric,
    period: params.period,
    lookbackDays: params.lookbackDays,
    cells,
    totals,
  }
}
