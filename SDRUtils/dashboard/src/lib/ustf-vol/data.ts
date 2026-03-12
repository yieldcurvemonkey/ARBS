import { query } from '@/lib/db'
import type {
  AssetType,
  ComparisonSnapshotResponse,
  SeriesConfig,
  SeriesStats,
  SmileDateSlice,
  SmilePoint,
  SmileXAxis,
  TermStructureDateSlice,
  TimeRange,
  TimeseriesMode,
  TimeseriesPoint,
  TimeseriesResponse,
  TermStructureResponse,
  SmileResponse,
  UstfTimeseriesMultiResponse,
  UstfTimeseriesSeries,
} from '@/features/ustf-vol/types'
import {
  STANDARD_PAIRS,
  USTF_PRODUCTS,
  SWAPTION_TAILS,
} from '@/features/ustf-vol/constants'
import {
  formatSeriesConfigLabel,
  getLatestSnapshotDate,
  getSeriesConfigKey,
  getSeriesVolMetric,
} from '@/features/ustf-vol/utils'

const USTF_TABLE = 'arbs_ustf_vol_snapshots_v2'
const SWAPTION_TABLE = 'arbs_swaption_vol_snapshots_v2'
const COMPARISON_TABLE = 'arbs_ustf_vs_swaption_comparison_v2'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function parseNumber(value: unknown): number | null {
  if (value === null || value === undefined) return null
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

function formatDbDate(value: unknown): string | null {
  if (!value) return null

  if (typeof value === 'string') {
    const trimmed = value.trim()
    if (!trimmed) return null
    if (/^\d{4}-\d{2}-\d{2}$/.test(trimmed)) {
      return trimmed
    }

    const parsed = new Date(trimmed)
    return Number.isNaN(parsed.getTime()) ? null : parsed.toISOString().slice(0, 10)
  }

  if (value instanceof Date) {
    return Number.isNaN(value.getTime()) ? null : value.toISOString().slice(0, 10)
  }

  return null
}

function formatDbTimestamp(value: unknown): string | null {
  if (!value) return null

  if (typeof value === 'string') {
    const trimmed = value.trim()
    if (!trimmed) return null

    const parsed = new Date(trimmed)
    return Number.isNaN(parsed.getTime()) ? trimmed : parsed.toISOString()
  }

  if (value instanceof Date) {
    return Number.isNaN(value.getTime()) ? null : value.toISOString()
  }

  return null
}

function rangeToInterval(range: TimeRange): string {
  switch (range) {
    case '1M': return '1 month'
    case '3M': return '3 months'
    case '6M': return '6 months'
    case '1Y': return '1 year'
    case 'ALL': return '10 years'
  }
}

function computeStats(values: Array<number | null>): SeriesStats {
  const clean = values.filter((v): v is number => v !== null && Number.isFinite(v))
  if (clean.length === 0) {
    return { latest: null, mean: null, min: null, max: null, stdev: null, zScore: null, count: 0 }
  }
  const latest = clean[clean.length - 1]
  const mean = clean.reduce((a, b) => a + b, 0) / clean.length
  const min = Math.min(...clean)
  const max = Math.max(...clean)
  const variance = clean.reduce((s, v) => s + (v - mean) ** 2, 0) / clean.length
  const stdev = Math.sqrt(variance)
  const zScore = stdev > 1e-12 ? (latest - mean) / stdev : null
  return { latest, mean, min, max, stdev, zScore, count: clean.length }
}

function computeSeriesZScore(
  currentValue: number | null,
  historyValues: Array<number | null>
): number | null {
  if (currentValue === null || !Number.isFinite(currentValue)) {
    return null
  }

  const clean = historyValues.filter((value): value is number => value !== null && Number.isFinite(value))
  if (clean.length === 0) {
    return null
  }

  const mean = clean.reduce((sum, value) => sum + value, 0) / clean.length
  const variance = clean.reduce((sum, value) => sum + (value - mean) ** 2, 0) / clean.length
  const stdev = Math.sqrt(variance)
  return stdev > 1e-12 ? (currentValue - mean) / stdev : null
}

function timestampToMillis(value: string | null): number {
  if (!value) {
    return Number.NEGATIVE_INFINITY
  }

  const parsed = Date.parse(value)
  return Number.isNaN(parsed) ? Number.NEGATIVE_INFINITY : parsed
}

function parseJsonObject(value: unknown): Record<string, any> | null {
  if (value === null || value === undefined) return null

  if (typeof value === 'string') {
    try {
      const parsed = JSON.parse(value)
      return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : null
    } catch {
      return null
    }
  }

  if (typeof value === 'object' && !Array.isArray(value)) {
    return value as Record<string, any>
  }

  return null
}

function extractOtmNodeVolBps(
  payloadValue: unknown,
  side: string,
  selector: string
): number | null {
  const payload = parseJsonObject(payloadValue)
  const sideBucket = payload ? parseJsonObject(payload[side]) : null
  const node = sideBucket ? parseJsonObject(sideBucket[selector]) : null
  return node ? parseNumber(node.vol_bps) : null
}

function extractSeriesValue(
  config: SeriesConfig,
  row: Record<string, unknown>
): number | null {
  const metric = getSeriesVolMetric(config)
  if (metric.kind === 'atm') {
    return parseNumber(row.atm_nvol_bps)
  }

  if (metric.kind === 'delta_otm') {
    return extractOtmNodeVolBps(row.delta_otm_vols, metric.side, `${metric.delta}d`)
  }

  return extractOtmNodeVolBps(
    row.strike_offset_otm_vols,
    metric.side,
    String(metric.offsetBps)
  )
}

// ---------------------------------------------------------------------------
// Normal SABR Vol (Hagan approximation) — ported from MDP/sabr_calibration.py
// ---------------------------------------------------------------------------

export function sabrNormalVol(params: {
  strike: number
  forward: number
  timeToExpiry: number
  alpha: number
  beta: number
  rho: number
  nu: number
}): number {
  const eps = 1e-12
  const f = params.forward
  const k = params.strike
  const t = Math.max(params.timeToExpiry, 0)
  const a = params.alpha
  const b = params.beta
  const r = params.rho
  const n = params.nu

  // ATM case
  if (Math.abs(f - k) < eps) {
    const correction =
      ((b - 1) * (b - 2) * a * a) / (24 * f ** (2 - 2 * b)) +
      (r * b * n * a) / (4 * f ** (1 - b)) +
      ((2 - 3 * r * r) * n * n) / 24
    return a * f ** b * (1 + correction * t)
  }

  const logFK = Math.log(f / k)
  const fMid = Math.sqrt(f * k)

  let zeta: number
  if (Math.abs(b - 1) < eps) {
    zeta = (n / a) * logFK
  } else {
    zeta = (n / a) * ((f ** (1 - b) - k ** (1 - b)) / (1 - b))
  }

  const disc = Math.sqrt(Math.max(1 - 2 * r * zeta + zeta * zeta, 1e-18))
  const xZeta = Math.log((disc + zeta - r) / (1 - r))
  const zetaOverX = Math.abs(xZeta) < eps ? 1 : zeta / xZeta

  let prefactor: number
  if (Math.abs(b) < eps) {
    prefactor = a
  } else if (Math.abs(b - 1) < eps) {
    prefactor = (a * (f - k)) / logFK
  } else {
    prefactor = (a * (1 - b) * (f - k)) / (f ** (1 - b) - k ** (1 - b))
  }

  const correction =
    ((b - 1) * (b - 2) * a * a) / (24 * fMid ** (2 - 2 * b)) +
    (r * b * n * a) / (4 * fMid ** (1 - b)) +
    ((2 - 3 * r * r) * n * n) / 24

  return prefactor * zetaOverX * (1 + correction * t)
}

// ---------------------------------------------------------------------------
// Timeseries
// ---------------------------------------------------------------------------

type TimeseriesParams = {
  series1Type: AssetType
  series1Product?: string
  series1Expiry: string
  series1Tail?: string
  series2Type?: AssetType
  series2Product?: string
  series2Expiry?: string
  series2Tail?: string
  mode: TimeseriesMode
  range: TimeRange
}

type TimeseriesCollectionParams = {
  series: SeriesConfig[]
  range?: TimeRange
  startDate?: string
  endDate?: string
}

type SeriesWindow = {
  interval?: string
  startDate?: string
  endDate?: string
}

export async function fetchTimeseries(params: TimeseriesParams): Promise<TimeseriesResponse> {
  const interval = rangeToInterval(params.range)
  const hasSeries2 = params.series2Type && params.series2Expiry

  const series1Config: SeriesConfig = {
    type: params.series1Type,
    product: params.series1Product as SeriesConfig['product'],
    expiry: params.series1Expiry,
    tail: params.series1Tail as SeriesConfig['tail'],
  }
  const s1 = await fetchSingleSeries(series1Config, interval)

  let s2: Map<string, number | null> | null = null
  if (hasSeries2) {
    s2 = await fetchSingleSeries(
      {
        type: params.series2Type!,
        product: params.series2Product as SeriesConfig['product'],
        expiry: params.series2Expiry!,
        tail: params.series2Tail as SeriesConfig['tail'],
      },
      interval
    )
  }

  // Merge on dates
  const allDates = new Set<string>()
  for (const d of s1.keys()) allDates.add(d)
  if (s2) for (const d of s2.keys()) allDates.add(d)
  const sortedDates = [...allDates].sort()

  const points: TimeseriesPoint[] = sortedDates.map((date) => {
    const v1 = s1.get(date) ?? null
    const v2 = s2?.get(date) ?? null
    const spread = v1 !== null && v2 !== null ? v1 - v2 : null
    return { date, series1: v1, series2: v2, spread }
  })

  const series1Label = buildSeriesLabel(series1Config)
  const series2Label = hasSeries2
    ? buildSeriesLabel({
        type: params.series2Type!,
        product: params.series2Product as SeriesConfig['product'],
        expiry: params.series2Expiry!,
        tail: params.series2Tail as SeriesConfig['tail'],
      })
    : null

  return {
    series1Label,
    series2Label,
    points,
    stats: {
      series1: computeStats(points.map((p) => p.series1)),
      series2: hasSeries2 ? computeStats(points.map((p) => p.series2)) : null,
      spread: hasSeries2 ? computeStats(points.map((p) => p.spread)) : null,
    },
  }
}

export async function fetchTimeseriesCollection(
  params: TimeseriesCollectionParams
): Promise<UstfTimeseriesMultiResponse> {
  const uniqueSeries = Array.from(
    new Map(params.series.map((config) => [getSeriesConfigKey(config), config])).values()
  )

  const seriesWindow: SeriesWindow =
    params.startDate || params.endDate
      ? {
          startDate: params.startDate,
          endDate: params.endDate,
        }
      : {
          interval: rangeToInterval(params.range ?? '6M'),
        }

  const series = await Promise.all(
    uniqueSeries.map(async (config): Promise<UstfTimeseriesSeries> => {
      const points = await fetchSingleSeriesPoints(config, seriesWindow)

      return {
        id: getSeriesConfigKey(config),
        label: formatSeriesConfigLabel(config),
        config,
        points,
        stats: computeStats(points.map((point) => point.value)),
      }
    })
  )

  const allDates = series.flatMap((entry) => entry.points.map((point) => point.asOf)).sort()
  const warnings = series
    .filter((entry) => entry.points.length === 0)
    .map((entry) => `No data returned for ${entry.label}.`)

  return {
    startDate: allDates[0] ?? null,
    endDate: allDates.at(-1) ?? null,
    asOfDate: allDates.at(-1) ?? null,
    series,
    warnings,
  }
}

export async function fetchComparisonSnapshot(): Promise<ComparisonSnapshotResponse> {
  const params: Array<string> = []
  const filters = STANDARD_PAIRS.map((pair) => {
    params.push(
      pair.series1.product,
      pair.series1.expiry,
      pair.series2.expiry,
      pair.series2.tail
    )
    const base = params.length - 3
    return `(
      product = $${base}
      AND expiry_label = $${base + 1}
      AND swaption_expiry_label = $${base + 2}
      AND swaption_tail_label = $${base + 3}
    )`
  })

  const res = await query(
    `SELECT
        as_of_date::text AS as_of_date,
        product,
        expiry_label,
        swaption_expiry_label,
        swaption_tail_label,
        ustf_atm_nvol_bps,
        swaption_atm_nvol_bps,
        updated_at
     FROM ${COMPARISON_TABLE}
     WHERE ${filters.join(' OR ')}
     ORDER BY as_of_date`,
    params
  )

  type SnapshotHistoryRow = {
    asOfDate: string
    updatedAt: string | null
    listedVol: number | null
    otcVol: number | null
    spread: number | null
  }

  const historyByPair = new Map<string, SnapshotHistoryRow[]>()

  for (const row of res.rows) {
    const asOfDate = formatDbDate(row.as_of_date)
    if (!asOfDate) {
      continue
    }

    const pairKey = [
      String(row.product ?? ''),
      String(row.expiry_label ?? ''),
      String(row.swaption_expiry_label ?? ''),
      String(row.swaption_tail_label ?? ''),
    ].join('|')
    const listedVol = parseNumber(row.ustf_atm_nvol_bps)
    const otcVol = parseNumber(row.swaption_atm_nvol_bps)
    const spread =
      listedVol !== null && otcVol !== null
        ? listedVol - otcVol
        : null

    const entry: SnapshotHistoryRow = {
      asOfDate,
      updatedAt: formatDbTimestamp(row.updated_at),
      listedVol,
      otcVol,
      spread,
    }

    const history = historyByPair.get(pairKey)
    if (history) {
      history.push(entry)
    } else {
      historyByPair.set(pairKey, [entry])
    }
  }

  const rows = STANDARD_PAIRS.map((pair) => {
    const pairKey = [
      pair.series1.product,
      pair.series1.expiry,
      pair.series2.expiry,
      pair.series2.tail,
    ].join('|')
    const history = historyByPair.get(pairKey) ?? []

    let latestRow: SnapshotHistoryRow | null = null
    for (const candidate of history) {
      if (!latestRow) {
        latestRow = candidate
        continue
      }

      const candidateMillis = timestampToMillis(candidate.updatedAt)
      const latestMillis = timestampToMillis(latestRow.updatedAt)
      if (
        candidateMillis > latestMillis ||
        (candidateMillis === latestMillis && candidate.asOfDate > latestRow.asOfDate)
      ) {
        latestRow = candidate
      }
    }

    return {
      pairLabel: pair.label,
      asOfDate: latestRow?.asOfDate ?? null,
      updatedAt: latestRow?.updatedAt ?? null,
      listedLabel: formatSeriesConfigLabel(pair.series1),
      otcLabel: formatSeriesConfigLabel(pair.series2),
      listedVol: latestRow?.listedVol ?? null,
      otcVol: latestRow?.otcVol ?? null,
      spread: latestRow?.spread ?? null,
      spreadZScore: computeSeriesZScore(
        latestRow?.spread ?? null,
        history.map((entry) => entry.spread)
      ),
    }
  })

  const latestUpdatedAt =
    rows
      .map((row) => row.updatedAt)
      .filter((value): value is string => Boolean(value))
      .sort()
      .at(-1) ?? null

  return {
    latestDate: getLatestSnapshotDate(rows),
    latestUpdatedAt,
    rows,
  }
}

async function fetchSingleSeries(
  config: SeriesConfig,
  interval: string,
): Promise<Map<string, number | null>> {
  const result = new Map<string, number | null>()
  const points = await fetchSingleSeriesPoints(config, { interval })

  for (const point of points) {
    result.set(point.asOf, point.value)
  }

  return result
}

function buildSeriesLabel(config: SeriesConfig): string {
  return formatSeriesConfigLabel(config)
}

async function fetchSingleSeriesPoints(
  config: SeriesConfig,
  window: SeriesWindow
): Promise<Array<{ asOf: string; value: number | null }>> {
  const rows: Array<{ asOf: string; value: number | null }> = []

  if (config.type === 'ustf') {
    if (!config.product) return rows

    const params: Array<string> = [config.product, config.expiry]
    const filters = ['product = $1', 'expiry_label = $2']

    if (window.startDate) {
      params.push(window.startDate)
      filters.push(`as_of_date >= $${params.length}::date`)
    } else if (window.interval) {
      params.push(window.interval)
      filters.push(`as_of_date >= CURRENT_DATE - $${params.length}::interval`)
    }

    if (window.endDate) {
      params.push(window.endDate)
      filters.push(`as_of_date <= $${params.length}::date`)
    }

    const res = await query(
      `SELECT as_of_date::text AS as_of_date, atm_nvol_bps, delta_otm_vols, strike_offset_otm_vols
       FROM ${USTF_TABLE}
       WHERE ${filters.join(' AND ')}
       ORDER BY as_of_date`,
      params
    )

    for (const row of res.rows) {
      const asOf = formatDbDate(row.as_of_date)
      if (!asOf) continue
      rows.push({ asOf, value: extractSeriesValue(config, row) })
    }

    return rows
  }

  if (!config.tail) return rows

  const params: Array<string> = [config.expiry, config.tail]
  const filters = ['expiry_label = $1', 'tail_label = $2']

  if (window.startDate) {
    params.push(window.startDate)
    filters.push(`as_of_date >= $${params.length}::date`)
  } else if (window.interval) {
    params.push(window.interval)
    filters.push(`as_of_date >= CURRENT_DATE - $${params.length}::interval`)
  }

  if (window.endDate) {
    params.push(window.endDate)
    filters.push(`as_of_date <= $${params.length}::date`)
  }

  const res = await query(
    `SELECT as_of_date::text AS as_of_date, atm_nvol_bps, delta_otm_vols, strike_offset_otm_vols
     FROM ${SWAPTION_TABLE}
     WHERE ${filters.join(' AND ')}
     ORDER BY as_of_date`,
    params
  )

  for (const row of res.rows) {
    const asOf = formatDbDate(row.as_of_date)
    if (!asOf) continue
    rows.push({ asOf, value: extractSeriesValue(config, row) })
  }

  return rows
}

// ---------------------------------------------------------------------------
// Term Structure
// ---------------------------------------------------------------------------

type TermStructureParams = {
  assetType: AssetType
  expiry: string
  dates: string[]
  strikeOffsetBps: number
}

export async function fetchTermStructure(params: TermStructureParams): Promise<TermStructureResponse> {
  const dates: TermStructureDateSlice[] = []

  for (const dateStr of params.dates) {
    if (params.assetType === 'ustf') {
      dates.push(await fetchUstfTermStructureSlice(dateStr, params.expiry, params.strikeOffsetBps))
    } else {
      dates.push(await fetchSwaptionTermStructureSlice(dateStr, params.expiry, params.strikeOffsetBps))
    }
  }

  return {
    assetType: params.assetType,
    expiry: params.expiry,
    strikeOffsetBps: params.strikeOffsetBps,
    dates,
  }
}

async function fetchUstfTermStructureSlice(
  dateStr: string,
  expiry: string,
  strikeOffsetBps: number,
): Promise<TermStructureDateSlice> {
  const res = await query(
    `SELECT product, atm_nvol_bps, forward_price, fv01,
            sabr_alpha, sabr_beta, sabr_rho, sabr_nu, time_to_expiry
     FROM ${USTF_TABLE}
     WHERE as_of_date = $1 AND expiry_label = $2
     ORDER BY product`,
    [dateStr, expiry]
  )

  const rowsByProduct = new Map<string, any>()
  for (const row of res.rows) {
    rowsByProduct.set(row.product, row)
  }

  const points = USTF_PRODUCTS.map((product) => {
    const row = rowsByProduct.get(product)
    if (!row) return { label: product, vol: null }

    if (strikeOffsetBps === 0) {
      return { label: product, vol: parseNumber(row.atm_nvol_bps) }
    }

    const fwd = parseNumber(row.forward_price)
    const fv01 = parseNumber(row.fv01)
    const alpha = parseNumber(row.sabr_alpha)
    const beta = parseNumber(row.sabr_beta)
    const rho = parseNumber(row.sabr_rho)
    const nu = parseNumber(row.sabr_nu)
    const tte = parseNumber(row.time_to_expiry)

    if (fwd === null || fv01 === null || alpha === null || beta === null || rho === null || nu === null || tte === null || fv01 < 1e-12) {
      return { label: product, vol: null }
    }

    const strike = fwd + (strikeOffsetBps / 10000) * fv01
    const vol = sabrNormalVol({ strike, forward: fwd, timeToExpiry: tte, alpha, beta, rho, nu })
    return { label: product, vol: vol / fv01 }
  })

  return { date: dateStr, points }
}

async function fetchSwaptionTermStructureSlice(
  dateStr: string,
  expiry: string,
  strikeOffsetBps: number,
): Promise<TermStructureDateSlice> {
  const res = await query(
    `SELECT tail_label, atm_nvol_bps, atmf_rate,
            sabr_alpha, sabr_beta, sabr_rho, sabr_nu, expiry_time
     FROM ${SWAPTION_TABLE}
     WHERE as_of_date = $1 AND expiry_label = $2
     ORDER BY tail_label`,
    [dateStr, expiry]
  )

  const rowsByTail = new Map<string, any>()
  for (const row of res.rows) {
    rowsByTail.set(row.tail_label, row)
  }

  const points = SWAPTION_TAILS.map((tail) => {
    const row = rowsByTail.get(tail)
    if (!row) return { label: tail, vol: null }

    if (strikeOffsetBps === 0) {
      return { label: tail, vol: parseNumber(row.atm_nvol_bps) }
    }

    const fwd = parseNumber(row.atmf_rate)
    const alpha = parseNumber(row.sabr_alpha)
    const beta = parseNumber(row.sabr_beta)
    const rho = parseNumber(row.sabr_rho)
    const nu = parseNumber(row.sabr_nu)
    const tte = parseNumber(row.expiry_time)

    if (fwd === null || alpha === null || beta === null || rho === null || nu === null || tte === null) {
      return { label: tail, vol: null }
    }

    const strike = fwd + strikeOffsetBps / 10000
    const vol = sabrNormalVol({ strike, forward: fwd, timeToExpiry: tte, alpha, beta, rho, nu })
    return { label: tail, vol: vol * 10000 }
  })

  return { date: dateStr, points }
}

// ---------------------------------------------------------------------------
// Vol Smile
// ---------------------------------------------------------------------------

type SmileParams = {
  assetType: AssetType
  product?: string
  expiry: string
  tail?: string
  dates: string[]
  xAxis: SmileXAxis
  numPoints: number
}

export async function fetchSmile(params: SmileParams): Promise<SmileResponse> {
  const dates: SmileDateSlice[] = []

  for (const dateStr of params.dates) {
    if (params.assetType === 'ustf') {
      const slice = await fetchUstfSmileSlice(dateStr, params.product!, params.expiry, params.xAxis, params.numPoints)
      if (slice) dates.push(slice)
    } else {
      const slice = await fetchSwaptionSmileSlice(dateStr, params.expiry, params.tail!, params.xAxis, params.numPoints)
      if (slice) dates.push(slice)
    }
  }

  const label =
    params.assetType === 'ustf'
      ? `${params.expiry} ${params.product}`
      : `${params.expiry}x${params.tail}`

  return {
    assetType: params.assetType,
    label,
    xAxis: params.xAxis,
    dates,
  }
}

async function fetchUstfSmileSlice(
  dateStr: string,
  product: string,
  expiry: string,
  xAxis: SmileXAxis,
  numPoints: number,
): Promise<SmileDateSlice | null> {
  const res = await query(
    `SELECT forward_price, fv01,
            sabr_alpha, sabr_beta, sabr_rho, sabr_nu, time_to_expiry,
            smile_points
     FROM ${USTF_TABLE}
     WHERE as_of_date = $1 AND product = $2 AND expiry_label = $3`,
    [dateStr, product, expiry]
  )
  if (res.rows.length === 0) return null
  const row = res.rows[0]

  const fwd = parseNumber(row.forward_price)
  const fv01 = parseNumber(row.fv01)
  const alpha = parseNumber(row.sabr_alpha)
  const beta = parseNumber(row.sabr_beta)
  const rho = parseNumber(row.sabr_rho)
  const nu = parseNumber(row.sabr_nu)
  const tte = parseNumber(row.time_to_expiry)

  if (fwd === null || fv01 === null || alpha === null || beta === null || rho === null || nu === null || tte === null || fv01 < 1e-12) {
    return null
  }

  const smilePoints: SmilePoint[] = []
  const halfSpread = xAxis === 'delta' ? 45 : 200
  const step = (halfSpread * 2) / (numPoints - 1)

  for (let i = 0; i < numPoints; i++) {
    const x = -halfSpread + i * step

    let strike: number
    if (xAxis === 'strike_offset_bps') {
      strike = fwd + (x / 10000) * fv01
    } else {
      // delta-based: x ranges from -45 to +45, convert to strike
      // Negative x = put delta (OTM put), positive x = call delta (OTM call)
      const deltaPct = 50 + x // ranges from 5 to 95
      if (deltaPct <= 0 || deltaPct >= 100) continue
      const atmVol = sabrNormalVol({ strike: fwd, forward: fwd, timeToExpiry: tte, alpha, beta, rho, nu })
      const scale = atmVol * Math.sqrt(Math.max(tte, 1e-12))
      // Normal delta inversion: strike = fwd - scale * N_inv(delta)
      strike = fwd - scale * normalInverseCDF(deltaPct / 100)
    }

    const vol = sabrNormalVol({ strike, forward: fwd, timeToExpiry: tte, alpha, beta, rho, nu })
    smilePoints.push({ x, vol: vol / fv01 })
  }

  // Parse stored market points
  let marketPoints: SmilePoint[] | undefined
  const rawPts = row.smile_points
  if (Array.isArray(rawPts) && rawPts.length > 0) {
    marketPoints = rawPts.map((pt: any) => ({
      x: xAxis === 'delta' ? (pt.right === 'C' ? pt.delta_abs : -pt.delta_abs) : 0,
      vol: parseNumber(pt.iv_normal_bps) ?? 0,
    }))
  }

  return {
    date: dateStr,
    forward: fwd,
    smilePoints,
    sabrParams: { alpha, beta, rho, nu },
    marketPoints,
  }
}

async function fetchSwaptionSmileSlice(
  dateStr: string,
  expiry: string,
  tail: string,
  xAxis: SmileXAxis,
  numPoints: number,
): Promise<SmileDateSlice | null> {
  const res = await query(
    `SELECT atmf_rate, sabr_alpha, sabr_beta, sabr_rho, sabr_nu, expiry_time
     FROM ${SWAPTION_TABLE}
     WHERE as_of_date = $1 AND expiry_label = $2 AND tail_label = $3`,
    [dateStr, expiry, tail]
  )
  if (res.rows.length === 0) return null
  const row = res.rows[0]

  const fwd = parseNumber(row.atmf_rate)
  const alpha = parseNumber(row.sabr_alpha)
  const beta = parseNumber(row.sabr_beta)
  const rho = parseNumber(row.sabr_rho)
  const nu = parseNumber(row.sabr_nu)
  const tte = parseNumber(row.expiry_time)

  if (fwd === null || alpha === null || beta === null || rho === null || nu === null || tte === null) {
    return null
  }

  const smilePoints: SmilePoint[] = []
  const halfSpread = xAxis === 'delta' ? 45 : 200
  const step = (halfSpread * 2) / (numPoints - 1)

  for (let i = 0; i < numPoints; i++) {
    const x = -halfSpread + i * step

    let strike: number
    if (xAxis === 'strike_offset_bps') {
      strike = fwd + x / 10000
    } else {
      const deltaPct = 50 + x
      if (deltaPct <= 0 || deltaPct >= 100) continue
      const atmVol = sabrNormalVol({ strike: fwd, forward: fwd, timeToExpiry: tte, alpha, beta, rho, nu })
      const scale = atmVol * Math.sqrt(Math.max(tte, 1e-12))
      strike = fwd - scale * normalInverseCDF(deltaPct / 100)
    }

    const vol = sabrNormalVol({ strike, forward: fwd, timeToExpiry: tte, alpha, beta, rho, nu })
    smilePoints.push({ x, vol: vol * 10000 })
  }

  return {
    date: dateStr,
    forward: fwd,
    smilePoints,
    sabrParams: { alpha, beta, rho, nu },
  }
}

// ---------------------------------------------------------------------------
// Rational approximation of the inverse normal CDF (Beasley-Springer-Moro)
// ---------------------------------------------------------------------------

function normalInverseCDF(p: number): number {
  if (p <= 0) return -Infinity
  if (p >= 1) return Infinity
  if (Math.abs(p - 0.5) < 1e-15) return 0

  const a = [
    -3.969683028665376e1, 2.209460984245205e2, -2.759285104469687e2,
    1.383577518672690e2, -3.066479806614716e1, 2.506628277459239e0,
  ]
  const b = [
    -5.447609879822406e1, 1.615858368580409e2, -1.556989798598866e2,
    6.680131188771972e1, -1.328068155288572e1,
  ]
  const c = [
    -7.784894002430293e-3, -3.223964580411365e-1, -2.400758277161838e0,
    -2.549732539343734e0, 4.374664141464968e0, 2.938163982698783e0,
  ]
  const d = [
    7.784695709041462e-3, 3.224671290700398e-1, 2.445134137142996e0,
    3.754408661907416e0,
  ]

  const pLow = 0.02425
  const pHigh = 1 - pLow

  let q: number, r: number

  if (p < pLow) {
    q = Math.sqrt(-2 * Math.log(p))
    return (
      (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) /
      ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    )
  } else if (p <= pHigh) {
    q = p - 0.5
    r = q * q
    return (
      ((((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q) /
      (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)
    )
  } else {
    q = Math.sqrt(-2 * Math.log(1 - p))
    return -(
      (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) /
      ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    )
  }
}
