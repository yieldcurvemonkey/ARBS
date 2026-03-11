import { query } from '@/lib/db'
import type {
  AssetType,
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
} from '@/features/ustf-vol/types'
import {
  USTF_PRODUCTS,
  SWAPTION_TAILS,
} from '@/features/ustf-vol/constants'

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

export async function fetchTimeseries(params: TimeseriesParams): Promise<TimeseriesResponse> {
  const interval = rangeToInterval(params.range)
  const hasSeries2 = params.series2Type && params.series2Expiry

  // Build series1 query
  const s1 = await fetchSingleSeries(
    params.series1Type,
    params.series1Product,
    params.series1Expiry,
    params.series1Tail,
    interval,
  )

  let s2: Map<string, number | null> | null = null
  if (hasSeries2) {
    s2 = await fetchSingleSeries(
      params.series2Type!,
      params.series2Product,
      params.series2Expiry!,
      params.series2Tail,
      interval,
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

  const series1Label = buildSeriesLabel(params.series1Type, params.series1Product, params.series1Expiry, params.series1Tail)
  const series2Label = hasSeries2
    ? buildSeriesLabel(params.series2Type!, params.series2Product, params.series2Expiry!, params.series2Tail)
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

async function fetchSingleSeries(
  type: AssetType,
  product: string | undefined,
  expiry: string,
  tail: string | undefined,
  interval: string,
): Promise<Map<string, number | null>> {
  const result = new Map<string, number | null>()

  if (type === 'ustf') {
    if (!product) return result
    const res = await query(
      `SELECT as_of_date, atm_nvol_bps FROM ${USTF_TABLE}
       WHERE product = $1 AND expiry_label = $2
         AND as_of_date >= CURRENT_DATE - $3::interval
       ORDER BY as_of_date`,
      [product, expiry, interval]
    )
    for (const row of res.rows) {
      result.set(String(row.as_of_date).slice(0, 10), parseNumber(row.atm_nvol_bps))
    }
  } else {
    if (!tail) return result
    const res = await query(
      `SELECT as_of_date, atm_nvol_bps FROM ${SWAPTION_TABLE}
       WHERE expiry_label = $1 AND tail_label = $2
         AND as_of_date >= CURRENT_DATE - $3::interval
       ORDER BY as_of_date`,
      [expiry, tail, interval]
    )
    for (const row of res.rows) {
      result.set(String(row.as_of_date).slice(0, 10), parseNumber(row.atm_nvol_bps))
    }
  }

  return result
}

function buildSeriesLabel(type: AssetType, product?: string, expiry?: string, tail?: string): string {
  if (type === 'ustf') {
    return `${expiry} ${product} ATM`
  }
  return `${expiry}x${tail} Swpn`
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
