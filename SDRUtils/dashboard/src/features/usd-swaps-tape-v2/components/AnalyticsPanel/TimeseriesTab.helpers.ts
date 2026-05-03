import type {
  AnalyticsMetricKey,
  AnalyticsViewKey,
  FocusedTrade,
  TimeseriesPointAug,
} from './analytics-types'

const NY_TZ = 'America/New_York'

function roundMetric(value: number | null): number | null {
  return value != null ? +value.toFixed(2) : null
}

function parseTs(ts: string | null | undefined): Date | null {
  if (!ts) return null
  const date = new Date(ts)
  return Number.isNaN(date.getTime()) ? null : date
}

export type TimeseriesTickParts = {
  primary: string
  secondary: string
}

export function formatTimeseriesTickParts(
  ts: string | null | undefined,
  view: AnalyticsViewKey,
): TimeseriesTickParts {
  const date = parseTs(ts)
  if (!date) return { primary: '-', secondary: '' }
  const monthDay = date.toLocaleDateString('en-US', {
    month: 'short',
    day: '2-digit',
    timeZone: NY_TZ,
  })
  if (view === 'INTRADAY') {
    return {
      primary: monthDay,
      secondary: date.toLocaleTimeString('en-US', {
        hour: '2-digit',
        minute: '2-digit',
        hour12: false,
        timeZone: NY_TZ,
      }),
    }
  }
  return {
    primary: monthDay,
    secondary: date.toLocaleDateString('en-US', {
      year: 'numeric',
      timeZone: NY_TZ,
    }),
  }
}

export type TimeseriesTooltipTime = {
  date: string
  timestamp: string
  timezone: string
}

export function formatTimeseriesTooltipTime(
  ts: string | null | undefined,
): TimeseriesTooltipTime {
  const date = parseTs(ts)
  if (!date) return { date: '-', timestamp: '-', timezone: 'NY' }
  return {
    date: date.toLocaleDateString('en-US', {
      weekday: 'short',
      year: 'numeric',
      month: 'short',
      day: '2-digit',
      timeZone: NY_TZ,
    }),
    timestamp: date.toLocaleTimeString('en-US', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
      timeZone: NY_TZ,
    }),
    timezone: 'NY',
  }
}

export function effectiveTimeseriesMetric(
  metric: AnalyticsMetricKey,
  view: AnalyticsViewKey,
): AnalyticsMetricKey {
  if (view !== 'VOLUME') return metric
  return metric === 'notional' ? 'notional' : 'dv01'
}

export function projectTimeseriesPoint(
  point: TimeseriesPointAug,
  index: number,
  metric: AnalyticsMetricKey,
  focused: Pick<FocusedTrade, 'tenor_years'>,
): TimeseriesPointAug & { idxPos: number } {
  let idb: number | null = point.idbClose ?? null
  let custy: number | null = point.custyClose ?? null

  if (metric === 'spread_to_mid') {
    idb =
      point.idbClose != null && point.custyClose != null
        ? (point.idbClose - point.custyClose) * 0.6
        : null
    custy =
      point.idbClose != null && point.custyClose != null
        ? (point.custyClose - point.idbClose) * 0.6
        : null
  } else if (metric === 'dv01') {
    idb = point.idbDv01 ?? null
    custy = point.custyDv01 ?? null
  } else if (metric === 'notional') {
    idb = point.idbNotional != null ? point.idbNotional / 1e6 : null
    custy = point.custyNotional != null ? point.custyNotional / 1e6 : null
  } else if (metric === 'tenor_years') {
    idb = focused.tenor_years
    custy = focused.tenor_years
  }

  return {
    ...point,
    idxPos: index,
    idbClose: roundMetric(idb),
    custyClose: roundMetric(custy),
  }
}

export function focusedTimeseriesValue(
  focused: FocusedTrade,
  metric: AnalyticsMetricKey,
): number {
  if (metric === 'fixed_rate') return focused.fixed_rate_bps
  if (metric === 'dv01') return focused.dv01_usd_per_bp
  if (metric === 'notional') return focused.notional_usd / 1e6
  if (metric === 'spread_to_mid') return -0.9
  return focused.tenor_years
}
