import crypto from 'crypto'

import type {
  UstsRvDataMode,
  UstsRvTimeseriesRequest,
  UstsRvTimeseriesResponse,
  UstsRvTimeseriesSeries,
  UstsRvValueColumn
} from '@/features/usts-rv/types'
import { query } from '@/lib/db'

const CACHE_TTL_MS = 30_000
const POINTS_TABLE = 'arbs_ust_rv_points_v1'
const INTRADAY_POINTS_TABLE = 'arbs_ust_rv_intraday_points_v1'
const DEFAULT_CURVE = 'USD-SOFR-1D'
const DEFAULT_LOOKBACK_DAYS = 365 * 5
const DEFAULT_INTRADAY_LOOKBACK_DAYS = 10
const MAX_INTRADAY_LOOKBACK_DAYS = 30
const DEFAULT_DATA_MODE: UstsRvDataMode = 'eod_live'
const CUSIP_RE = /^[0-9A-Z]{9}$/
const CT_RE = /^CT(\d{1,2})$/i

const VALUE_SQL_COLUMN: Record<UstsRvValueColumn, string> = {
  mmss: 'mmss',
  ytm: 'ytm',
  clean_price: 'clean_price',
  dirty_price: 'dirty_price',
  mdur: 'mdur',
  carry_bps: 'carry_bps',
  roll_bps: 'roll_bps',
  carry_and_roll_bps: 'carry_and_roll_bps',
  coupon: 'coupon'
}

type SnapshotDateRow = {
  as_of_date: string | Date | null
}

type MinDateRow = {
  min_date: string | Date | null
}

type TimeseriesRow = {
  as_of_date: string | Date | null
  cusip: string | null
  ust_label: string | null
  oi: string | null
  rank: number | null
  snapshot_ts: string | Date | null
  value: number | null
}

type IntradayTimeseriesRow = {
  market_timestamp: string | Date | null
  cusip: string | null
  ust_label: string | null
  oi: string | null
  rank: number | null
  snapshot_ts: string | Date | null
  value: number | null
}

type SeriesTarget =
  | { kind: 'cusip'; key: string }
  | { kind: 'ct'; key: string; tenorYears: number }

const responseCache = new Map<
  string,
  { createdAt: number; value: UstsRvTimeseriesResponse }
>()

function buildCacheKey(payload: UstsRvTimeseriesRequest) {
  const canonical = JSON.stringify(payload)
  return crypto.createHash('sha1').update(canonical).digest('hex')
}

function trimCache(now: number) {
  for (const [k, v] of responseCache.entries()) {
    if (now - v.createdAt > CACHE_TTL_MS) {
      responseCache.delete(k)
    }
  }
}

function asIsoDate(value: Date) {
  return value.toISOString().slice(0, 10)
}

function parseAsOf(raw: string | undefined) {
  const today = asIsoDate(new Date())

  if (!raw || !raw.trim()) {
    return { requestedAsOf: today, requestedLive: true }
  }

  const txt = raw.trim()
  if (txt.toLowerCase() === 'today' || txt.toLowerCase() === 'live') {
    return { requestedAsOf: today, requestedLive: true }
  }

  if (/^\d{4}-\d{2}-\d{2}$/.test(txt)) {
    return { requestedAsOf: txt, requestedLive: txt === today }
  }

  const parsed = new Date(txt)
  if (Number.isNaN(parsed.getTime())) {
    throw new Error(
      `Invalid asOf date '${raw}'. Expected YYYY-MM-DD, 'today', or 'live'.`
    )
  }

  const requestedAsOf = asIsoDate(parsed)
  return { requestedAsOf, requestedLive: requestedAsOf === today }
}

function parseDateOnly(raw: string | undefined): string | null {
  if (!raw || !raw.trim()) return null
  const txt = raw.trim()
  if (/^\d{4}-\d{2}-\d{2}$/.test(txt)) return txt
  const parsed = new Date(txt)
  if (Number.isNaN(parsed.getTime())) return null
  return asIsoDate(parsed)
}

function parseTimeOfDay(raw: string | undefined): string | null {
  if (!raw || !raw.trim()) return null
  const txt = raw.trim()
  const match = txt.match(/^(\d{1,2}):(\d{2})(?::(\d{2}))?$/)
  if (!match) return null
  const hour = Math.trunc(Number(match[1]))
  const minute = Math.trunc(Number(match[2]))
  const second = Math.trunc(Number(match[3] ?? '0'))
  if (
    !Number.isFinite(hour) ||
    !Number.isFinite(minute) ||
    !Number.isFinite(second) ||
    hour < 0 ||
    hour > 23 ||
    minute < 0 ||
    minute > 59 ||
    second < 0 ||
    second > 59
  ) {
    return null
  }
  return `${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}:${String(
    second
  ).padStart(2, '0')}`
}

function toIsoDate(value: unknown): string | null {
  if (value === null || value === undefined) return null
  if (value instanceof Date) return asIsoDate(value)
  const txt = String(value)
  if (/^\d{4}-\d{2}-\d{2}$/.test(txt)) return txt
  const parsed = new Date(txt)
  if (Number.isNaN(parsed.getTime())) return null
  return asIsoDate(parsed)
}

function toIsoTimestamp(value: unknown): string | null {
  if (value === null || value === undefined) return null
  if (value instanceof Date) return value.toISOString()
  const parsed = new Date(String(value))
  if (Number.isNaN(parsed.getTime())) return null
  return parsed.toISOString()
}

function shiftIsoDate(dateIso: string, days: number) {
  const d = new Date(`${dateIso}T00:00:00Z`)
  d.setUTCDate(d.getUTCDate() + days)
  return asIsoDate(d)
}

function normalizeDataMode(raw: unknown): UstsRvDataMode {
  return raw === 'intraday_live' ? 'intraday_live' : 'eod_live'
}

function normalizeSeriesTargets(raw: string[]) {
  const out: SeriesTarget[] = []
  const seen = new Set<string>()

  for (const rawValue of raw || []) {
    const value = String(rawValue || '').trim().toUpperCase()
    if (!value || seen.has(value)) continue

    if (CUSIP_RE.test(value)) {
      out.push({ kind: 'cusip', key: value })
      seen.add(value)
      continue
    }

    const ctMatch = value.match(CT_RE)
    if (ctMatch) {
      const tenorYears = Math.trunc(Number(ctMatch[1]))
      if (Number.isFinite(tenorYears) && tenorYears > 0) {
        out.push({ kind: 'ct', key: `CT${tenorYears}`, tenorYears })
        seen.add(`CT${tenorYears}`)
      }
    }
  }

  return out
}

function parseTenorYearsFromOi(oi: string | null | undefined) {
  if (!oi) return null
  const match = String(oi).match(/(\d{1,2})/)
  if (!match) return null
  const years = Math.trunc(Number(match[1]))
  return Number.isFinite(years) && years > 0 ? years : null
}

async function resolveSnapshotDate(curveName: string, requestedAsOf: string) {
  const warnings: string[] = []

  const preferred = await query<SnapshotDateRow>(
    `
      SELECT MAX(as_of_date)::date AS as_of_date
      FROM ${POINTS_TABLE}
      WHERE curve_name = $1
        AND as_of_date <= $2::date
    `,
    [curveName, requestedAsOf]
  )

  let selectedAsOf = toIsoDate(preferred.rows[0]?.as_of_date)

  if (!selectedAsOf) {
    const latestAny = await query<SnapshotDateRow>(
      `
        SELECT MAX(as_of_date)::date AS as_of_date
        FROM ${POINTS_TABLE}
        WHERE curve_name = $1
      `,
      [curveName]
    )

    selectedAsOf = toIsoDate(latestAny.rows[0]?.as_of_date)
    if (selectedAsOf) {
      warnings.push(
        `No DB snapshot found on/before ${requestedAsOf}; using latest available ${selectedAsOf}.`
      )
    }
  }

  if (!selectedAsOf) {
    throw new Error(
      `No UST RV snapshots found in ${POINTS_TABLE} for curve '${curveName}'. Run ingest_ustrv.py first.`
    )
  }

  if (selectedAsOf !== requestedAsOf) {
    warnings.push(
      `Using DB snapshot asOf ${selectedAsOf} for requested ${requestedAsOf}.`
    )
  }

  return { selectedAsOf, warnings }
}

async function resolveIntradaySnapshotDate(curveName: string, requestedAsOf: string) {
  const warnings: string[] = []

  const preferred = await query<SnapshotDateRow>(
    `
      SELECT MAX(as_of_date)::date AS as_of_date
      FROM ${INTRADAY_POINTS_TABLE}
      WHERE curve_name = $1
        AND as_of_date <= $2::date
    `,
    [curveName, requestedAsOf]
  )

  let selectedAsOf = toIsoDate(preferred.rows[0]?.as_of_date)

  if (!selectedAsOf) {
    const latestAny = await query<SnapshotDateRow>(
      `
        SELECT MAX(as_of_date)::date AS as_of_date
        FROM ${INTRADAY_POINTS_TABLE}
        WHERE curve_name = $1
      `,
      [curveName]
    )

    selectedAsOf = toIsoDate(latestAny.rows[0]?.as_of_date)
    if (selectedAsOf) {
      warnings.push(
        `No intraday DB snapshot found on/before ${requestedAsOf}; using latest available ${selectedAsOf}.`
      )
    }
  }

  if (!selectedAsOf) {
    throw new Error(
      `No UST RV intraday snapshots found in ${INTRADAY_POINTS_TABLE} for curve '${curveName}'. Run ingest_ustrv.py --mode intraday first.`
    )
  }

  if (selectedAsOf !== requestedAsOf) {
    warnings.push(
      `Using intraday DB asOf ${selectedAsOf} for requested ${requestedAsOf}.`
    )
  }

  return { selectedAsOf, warnings }
}

async function resolveDateRange(
  payload: UstsRvTimeseriesRequest,
  curveName: string,
  selectedAsOf: string,
  targets: SeriesTarget[]
) {
  const warnings: string[] = []

  let endDate = parseDateOnly(payload.endDate) || selectedAsOf
  if (endDate > selectedAsOf) {
    warnings.push(`Adjusted endDate from ${endDate} to snapshot asOf ${selectedAsOf}.`)
    endDate = selectedAsOf
  }

  let startDate = parseDateOnly(payload.startDate)
  if (!startDate) {
    const lookbackDays = Number.isFinite(Number(payload.lookbackDays))
      ? Math.max(1, Math.trunc(Number(payload.lookbackDays)))
      : DEFAULT_LOOKBACK_DAYS
    startDate = shiftIsoDate(endDate, -lookbackDays)
  }

  if (startDate > endDate) {
    warnings.push(`Adjusted startDate ${startDate} to endDate ${endDate}.`)
    startDate = endDate
  }

  const cusips = targets
    .filter((target): target is Extract<SeriesTarget, { kind: 'cusip' }> => target.kind === 'cusip')
    .map((target) => target.key)
  const ctTenors = targets
    .filter((target): target is Extract<SeriesTarget, { kind: 'ct' }> => target.kind === 'ct')
    .map((target) => target.tenorYears)

  let minAvailable: string | null = null

  if (cusips.length) {
    const minDateResult = await query<MinDateRow>(
      `
        SELECT MIN(as_of_date)::date AS min_date
        FROM ${POINTS_TABLE}
        WHERE curve_name = $1
          AND cusip = ANY($2::text[])
          AND as_of_date <= $3::date
      `,
      [curveName, cusips, endDate]
    )
    const minCusipDate = toIsoDate(minDateResult.rows[0]?.min_date)
    if (minCusipDate) {
      if (!minAvailable) {
        minAvailable = minCusipDate
      } else if (minCusipDate.localeCompare(minAvailable) < 0) {
        minAvailable = minCusipDate
      }
    }
  }

  if (ctTenors.length) {
    const minCtDateResult = await query<MinDateRow>(
      `
        SELECT MIN(as_of_date)::date AS min_date
        FROM ${POINTS_TABLE}
        WHERE curve_name = $1
          AND rank = 0
          AND as_of_date <= $2::date
          AND NULLIF(regexp_replace(COALESCE(oi, ''), '[^0-9]', '', 'g'), '')::int = ANY($3::int[])
      `,
      [curveName, endDate, ctTenors]
    )
    const minCtDate = toIsoDate(minCtDateResult.rows[0]?.min_date)
    if (minCtDate) {
      if (!minAvailable) {
        minAvailable = minCtDate
      } else if (minCtDate.localeCompare(minAvailable) < 0) {
        minAvailable = minCtDate
      }
    }
  }

  if (minAvailable && startDate < minAvailable) {
    warnings.push(
      `Adjusted startDate from ${startDate} to earliest available ${minAvailable} for selected series.`
    )
    startDate = minAvailable
  }

  return { startDate, endDate, warnings }
}

async function resolveIntradayDateRange(
  payload: UstsRvTimeseriesRequest,
  curveName: string,
  selectedAsOf: string,
  targets: SeriesTarget[]
) {
  const warnings: string[] = []
  const defaultStartTime = '00:00:00'
  const defaultEndTime = '23:59:59'

  let endDate = parseDateOnly(payload.endDate) || selectedAsOf
  if (endDate > selectedAsOf) {
    warnings.push(`Adjusted endDate from ${endDate} to snapshot asOf ${selectedAsOf}.`)
    endDate = selectedAsOf
  }

  let startDate = parseDateOnly(payload.startDate)
  if (!startDate) {
    const lookbackDaysRaw = Number.isFinite(Number(payload.lookbackDays))
      ? Math.max(1, Math.trunc(Number(payload.lookbackDays)))
      : DEFAULT_INTRADAY_LOOKBACK_DAYS
    const lookbackDays = Math.min(lookbackDaysRaw, MAX_INTRADAY_LOOKBACK_DAYS)
    if (lookbackDays < lookbackDaysRaw) {
      warnings.push(
        `Adjusted intraday lookbackDays from ${lookbackDaysRaw} to max ${MAX_INTRADAY_LOOKBACK_DAYS}.`
      )
    }
    startDate = shiftIsoDate(endDate, -lookbackDays)
  }

  if (startDate > endDate) {
    warnings.push(`Adjusted startDate ${startDate} to endDate ${endDate}.`)
    startDate = endDate
  }

  const spanDays = Math.max(
    0,
    Math.round(
      (new Date(`${endDate}T00:00:00Z`).getTime() -
        new Date(`${startDate}T00:00:00Z`).getTime()) /
        (24 * 60 * 60 * 1000)
    )
  )
  if (spanDays > MAX_INTRADAY_LOOKBACK_DAYS) {
    const adjusted = shiftIsoDate(endDate, -MAX_INTRADAY_LOOKBACK_DAYS)
    warnings.push(
      `Adjusted intraday startDate from ${startDate} to ${adjusted} (max ${MAX_INTRADAY_LOOKBACK_DAYS}D window).`
    )
    startDate = adjusted
  }

  const cusips = targets
    .filter((target): target is Extract<SeriesTarget, { kind: 'cusip' }> => target.kind === 'cusip')
    .map((target) => target.key)
  const ctTenors = targets
    .filter((target): target is Extract<SeriesTarget, { kind: 'ct' }> => target.kind === 'ct')
    .map((target) => target.tenorYears)

  let minAvailable: string | null = null

  if (cusips.length) {
    const minDateResult = await query<MinDateRow>(
      `
        SELECT MIN(as_of_date)::date AS min_date
        FROM ${INTRADAY_POINTS_TABLE}
        WHERE curve_name = $1
          AND cusip = ANY($2::text[])
          AND as_of_date <= $3::date
      `,
      [curveName, cusips, endDate]
    )
    const minCusipDate = toIsoDate(minDateResult.rows[0]?.min_date)
    if (minCusipDate) {
      if (!minAvailable) {
        minAvailable = minCusipDate
      } else if (minCusipDate.localeCompare(minAvailable) < 0) {
        minAvailable = minCusipDate
      }
    }
  }

  if (ctTenors.length) {
    const minCtDateResult = await query<MinDateRow>(
      `
        SELECT MIN(as_of_date)::date AS min_date
        FROM ${INTRADAY_POINTS_TABLE}
        WHERE curve_name = $1
          AND rank = 0
          AND as_of_date <= $2::date
          AND NULLIF(regexp_replace(COALESCE(oi, ''), '[^0-9]', '', 'g'), '')::int = ANY($3::int[])
      `,
      [curveName, endDate, ctTenors]
    )
    const minCtDate = toIsoDate(minCtDateResult.rows[0]?.min_date)
    if (minCtDate) {
      if (!minAvailable) {
        minAvailable = minCtDate
      } else if (minCtDate.localeCompare(minAvailable) < 0) {
        minAvailable = minCtDate
      }
    }
  }

  if (minAvailable && startDate < minAvailable) {
    warnings.push(
      `Adjusted startDate from ${startDate} to earliest available ${minAvailable} for selected intraday series.`
    )
    startDate = minAvailable
  }

  const parsedStartTime = parseTimeOfDay(payload.startTime)
  const parsedEndTime = parseTimeOfDay(payload.endTime)
  if (payload.startTime && !parsedStartTime) {
    warnings.push(
      `Invalid intraday startTime '${payload.startTime}'. Using ${defaultStartTime}.`
    )
  }
  if (payload.endTime && !parsedEndTime) {
    warnings.push(`Invalid intraday endTime '${payload.endTime}'. Using ${defaultEndTime}.`)
  }

  let startTime = parsedStartTime || defaultStartTime
  let endTime = parsedEndTime || defaultEndTime

  if (startDate === endDate && startTime > endTime) {
    warnings.push(
      `Adjusted intraday startTime ${startTime} to endTime ${endTime} for same-day range ${startDate}.`
    )
    startTime = endTime
  }

  return { startDate, endDate, startTime, endTime, warnings }
}

export async function getUstsRvTimeseries(
  payload: UstsRvTimeseriesRequest
): Promise<UstsRvTimeseriesResponse> {
  const dataMode = normalizeDataMode(payload.dataMode ?? DEFAULT_DATA_MODE)
  const normalizedPayload: UstsRvTimeseriesRequest = {
    ...payload,
    dataMode
  }

  const now = Date.now()
  trimCache(now)

  const cacheKey = buildCacheKey(normalizedPayload)
  const cached = responseCache.get(cacheKey)
  if (cached && now - cached.createdAt < CACHE_TTL_MS) {
    return cached.value
  }

  const targets = normalizeSeriesTargets(payload.cusips || [])
  if (!targets.length) {
    throw new Error('At least one valid CUSIP or CT tenor is required for timeseries.')
  }

  const valueColumn = payload.valueColumn
  if (!Object.prototype.hasOwnProperty.call(VALUE_SQL_COLUMN, valueColumn)) {
    throw new Error(`Unsupported valueColumn '${String(valueColumn)}'.`)
  }

  const curveName = (payload.curveName || DEFAULT_CURVE).trim() || DEFAULT_CURVE
  const { requestedAsOf, requestedLive } = parseAsOf(payload.asOf)
  const asOfResolution =
    dataMode === 'intraday_live'
      ? await resolveIntradaySnapshotDate(curveName, requestedAsOf)
      : await resolveSnapshotDate(curveName, requestedAsOf)
  const dateRange =
    dataMode === 'intraday_live'
      ? await resolveIntradayDateRange(
          payload,
          curveName,
          asOfResolution.selectedAsOf,
          targets
        )
      : await resolveDateRange(payload, curveName, asOfResolution.selectedAsOf, targets)
  const intradayRange =
    dataMode === 'intraday_live'
      ? (dateRange as {
          startDate: string
          endDate: string
          startTime: string
          endTime: string
          warnings: string[]
        })
      : null

  const cusipTargets = targets
    .filter((target): target is Extract<SeriesTarget, { kind: 'cusip' }> => target.kind === 'cusip')
    .map((target) => target.key)
  const ctTargets = targets.filter(
    (target): target is Extract<SeriesTarget, { kind: 'ct' }> => target.kind === 'ct'
  )

  const valueSql = VALUE_SQL_COLUMN[valueColumn]
  const ctTenors = ctTargets.map((target) => target.tenorYears)
  let cusipRowsEod: TimeseriesRow[] = []
  let ctRowsEod: TimeseriesRow[] = []
  let cusipRowsIntraday: IntradayTimeseriesRow[] = []
  let ctRowsIntraday: IntradayTimeseriesRow[] = []

  if (dataMode === 'intraday_live') {
    cusipRowsIntraday = cusipTargets.length
      ? (
          await query<IntradayTimeseriesRow>(
            `
              SELECT
                market_timestamp,
                cusip,
                ust_label,
                oi,
                rank::int AS rank,
                snapshot_ts,
                ${valueSql}::double precision AS value
              FROM ${INTRADAY_POINTS_TABLE}
              WHERE curve_name = $1
                AND cusip = ANY($2::text[])
                AND market_timestamp BETWEEN (($3::date + $5::time) AT TIME ZONE 'America/New_York')
                    AND (($4::date + $6::time) AT TIME ZONE 'America/New_York')
              ORDER BY market_timestamp ASC, cusip ASC
            `,
            [
              curveName,
              cusipTargets,
              intradayRange!.startDate,
              intradayRange!.endDate,
              intradayRange!.startTime,
              intradayRange!.endTime
            ]
          )
        ).rows
      : []

    ctRowsIntraday = ctTenors.length
      ? (
          await query<IntradayTimeseriesRow>(
            `
              SELECT
                market_timestamp,
                cusip,
                ust_label,
                oi,
                rank::int AS rank,
                snapshot_ts,
                ${valueSql}::double precision AS value
              FROM ${INTRADAY_POINTS_TABLE}
              WHERE curve_name = $1
                AND rank = 0
                AND market_timestamp BETWEEN (($2::date + $4::time) AT TIME ZONE 'America/New_York')
                    AND (($3::date + $5::time) AT TIME ZONE 'America/New_York')
                AND NULLIF(regexp_replace(COALESCE(oi, ''), '[^0-9]', '', 'g'), '')::int = ANY($6::int[])
              ORDER BY market_timestamp ASC, oi ASC, cusip ASC
            `,
            [
              curveName,
              intradayRange!.startDate,
              intradayRange!.endDate,
              intradayRange!.startTime,
              intradayRange!.endTime,
              ctTenors
            ]
          )
        ).rows
      : []
  } else {
    cusipRowsEod = cusipTargets.length
      ? (
          await query<TimeseriesRow>(
            `
              SELECT
                as_of_date::date AS as_of_date,
                cusip,
                ust_label,
                oi,
                rank::int AS rank,
                snapshot_ts,
                ${valueSql}::double precision AS value
              FROM ${POINTS_TABLE}
              WHERE curve_name = $1
                AND cusip = ANY($2::text[])
                AND as_of_date BETWEEN $3::date AND $4::date
              ORDER BY as_of_date ASC, cusip ASC
            `,
            [curveName, cusipTargets, dateRange.startDate, dateRange.endDate]
          )
        ).rows
      : []

    ctRowsEod = ctTenors.length
      ? (
          await query<TimeseriesRow>(
            `
              SELECT
                as_of_date::date AS as_of_date,
                cusip,
                ust_label,
                oi,
                rank::int AS rank,
                snapshot_ts,
                ${valueSql}::double precision AS value
              FROM ${POINTS_TABLE}
              WHERE curve_name = $1
                AND rank = 0
                AND as_of_date BETWEEN $2::date AND $3::date
                AND NULLIF(regexp_replace(COALESCE(oi, ''), '[^0-9]', '', 'g'), '')::int = ANY($4::int[])
              ORDER BY as_of_date ASC, oi ASC, cusip ASC
            `,
            [curveName, dateRange.startDate, dateRange.endDate, ctTenors]
          )
        ).rows
      : []
  }

  const seriesMap = new Map<string, UstsRvTimeseriesSeries>()
  for (const target of targets) {
    if (target.kind === 'ct') {
      seriesMap.set(target.key, {
        cusip: target.key,
        ust_label: `Constant Maturity ${target.tenorYears}Y`,
        oi: `${target.tenorYears}-Year`,
        rank: 0,
        points: []
      })
      continue
    }

    seriesMap.set(target.key, {
      cusip: target.key,
      ust_label: null,
      oi: null,
      rank: null,
      points: []
    })
  }

  if (dataMode === 'intraday_live') {
    for (const row of cusipRowsIntraday) {
      const cusip = row.cusip ? String(row.cusip).toUpperCase() : ''
      if (!cusip) continue
      const series = seriesMap.get(cusip)
      if (!series) continue

      if (series.ust_label === null && row.ust_label != null) series.ust_label = row.ust_label
      if (series.oi === null && row.oi != null) series.oi = row.oi
      if (series.rank === null && row.rank != null && Number.isFinite(Number(row.rank))) {
        series.rank = Math.trunc(Number(row.rank))
      }

      const asOf = toIsoTimestamp(row.market_timestamp)
      if (!asOf) continue

      const rawValue = row.value == null ? null : Number(row.value)
      const value = Number.isFinite(rawValue as number) ? (rawValue as number) : null

      series.points.push({
        asOf,
        value,
        snapshotTs: toIsoTimestamp(row.snapshot_ts)
      })
    }

    for (const row of ctRowsIntraday) {
      const tenorYears = parseTenorYearsFromOi(row.oi)
      if (tenorYears === null) continue
      const ctKey = `CT${tenorYears}`
      const series = seriesMap.get(ctKey)
      if (!series) continue

      if (series.oi === null && row.oi != null) series.oi = row.oi
      series.rank = 0

      const asOf = toIsoTimestamp(row.market_timestamp)
      if (!asOf) continue

      const rawValue = row.value == null ? null : Number(row.value)
      const value = Number.isFinite(rawValue as number) ? (rawValue as number) : null

      series.points.push({
        asOf,
        value,
        snapshotTs: toIsoTimestamp(row.snapshot_ts)
      })
    }
  } else {
    for (const row of cusipRowsEod) {
      const cusip = row.cusip ? String(row.cusip).toUpperCase() : ''
      if (!cusip) continue
      const series = seriesMap.get(cusip)
      if (!series) continue

      if (series.ust_label === null && row.ust_label != null) series.ust_label = row.ust_label
      if (series.oi === null && row.oi != null) series.oi = row.oi
      if (series.rank === null && row.rank != null && Number.isFinite(Number(row.rank))) {
        series.rank = Math.trunc(Number(row.rank))
      }

      const asOf = toIsoDate(row.as_of_date)
      if (!asOf) continue

      const rawValue = row.value == null ? null : Number(row.value)
      const value = Number.isFinite(rawValue as number) ? (rawValue as number) : null

      series.points.push({
        asOf,
        value,
        snapshotTs: toIsoTimestamp(row.snapshot_ts)
      })
    }

    for (const row of ctRowsEod) {
      const tenorYears = parseTenorYearsFromOi(row.oi)
      if (tenorYears === null) continue
      const ctKey = `CT${tenorYears}`
      const series = seriesMap.get(ctKey)
      if (!series) continue

      if (series.oi === null && row.oi != null) series.oi = row.oi
      series.rank = 0

      const asOf = toIsoDate(row.as_of_date)
      if (!asOf) continue

      const rawValue = row.value == null ? null : Number(row.value)
      const value = Number.isFinite(rawValue as number) ? (rawValue as number) : null

      series.points.push({
        asOf,
        value,
        snapshotTs: toIsoTimestamp(row.snapshot_ts)
      })
    }
  }

  const series = targets
    .map((target) => seriesMap.get(target.key))
    .filter((item): item is UstsRvTimeseriesSeries => Boolean(item))

  const totalPoints = series.reduce((sum, s) => sum + s.points.length, 0)
  const warnings = [...asOfResolution.warnings, ...dateRange.warnings]
  if (dataMode === 'intraday_live') {
    warnings.push(
      `Intraday DB source: ${INTRADAY_POINTS_TABLE} (${intradayRange!.startDate} ${intradayRange!.startTime} to ${intradayRange!.endDate} ${intradayRange!.endTime}, America/New_York).`
    )
  }
  if (totalPoints === 0) {
    warnings.push('No timeseries points found for selected series/date range.')
  }

  const out: UstsRvTimeseriesResponse = {
    requestedAsOf,
    asOf: asOfResolution.selectedAsOf,
    requestedLive,
    dataMode,
    curveName,
    valueColumn,
    startDate: dateRange.startDate,
    endDate: dateRange.endDate,
    series,
    meta: {
      seriesCount: series.length,
      totalPoints,
      warnings
    }
  }

  responseCache.set(cacheKey, { createdAt: now, value: out })
  return out
}
