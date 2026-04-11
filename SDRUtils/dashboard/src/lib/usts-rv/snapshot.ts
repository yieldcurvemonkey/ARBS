import crypto from 'crypto'

import type {
  UstsRvDataMode,
  UstsRvPoint,
  UstsRvSplineConfigRequest,
  UstsRvSplineSeries,
  UstsRvSnapshotRequest,
  UstsRvSnapshotResponse,
  UstsRvValueColumn,
  UstsRvXColumn
} from '@/features/usts-rv/types'
import { query } from '@/lib/db'

const CACHE_TTL_MS = 45_000
const POINTS_TABLE = 'arbs_ust_rv_points_v1'
const INTRADAY_POINTS_TABLE = 'arbs_ust_rv_intraday_points_v1'
const DEFAULT_CURVE = 'USD-SOFR-1D'
const DEFAULT_MIN_TTM = 1.0
const DEFAULT_DATA_MODE: UstsRvDataMode = 'eod_live'

const AVAILABLE_VALUE_COLUMNS: UstsRvValueColumn[] = [
  'mmss',
  'ytm',
  'clean_price',
  'dirty_price',
  'mdur',
  'carry_bps',
  'roll_bps',
  'carry_and_roll_bps',
  'coupon'
]

const responseCache = new Map<
  string,
  { createdAt: number; value: UstsRvSnapshotResponse }
>()

type SnapshotDateRow = {
  as_of_date: string | Date | null
}

type IntradaySnapshotRow = {
  as_of_date: string | Date | null
  market_timestamp: string | Date | null
}

type PointRow = {
  cusip: string | null
  oi: string | null
  ust_label: string | null
  rank: number | null
  ttm: number | null
  mdur: number | null
  ytm: number | null
  mmss: number | null
  clean_price: number | null
  dirty_price: number | null
  coupon: number | null
  carry_bps: number | null
  roll_bps: number | null
  carry_and_roll_bps: number | null
  carry_1m_bps: number | null
  roll_1m_bps: number | null
  carry_and_roll_1m_bps: number | null
  carry_2m_bps: number | null
  roll_2m_bps: number | null
  carry_and_roll_2m_bps: number | null
  carry_3m_bps: number | null
  roll_3m_bps: number | null
  carry_and_roll_3m_bps: number | null
  carry_6m_bps: number | null
  roll_6m_bps: number | null
  carry_and_roll_6m_bps: number | null
  swap_carry_bps: number | null
  swap_roll_bps: number | null
  swap_carry_and_roll_bps: number | null
  swap_carry_1m_bps: number | null
  swap_roll_1m_bps: number | null
  swap_carry_and_roll_1m_bps: number | null
  swap_carry_2m_bps: number | null
  swap_roll_2m_bps: number | null
  swap_carry_and_roll_2m_bps: number | null
  swap_carry_3m_bps: number | null
  swap_roll_3m_bps: number | null
  swap_carry_and_roll_3m_bps: number | null
  swap_carry_6m_bps: number | null
  swap_roll_6m_bps: number | null
  swap_carry_and_roll_6m_bps: number | null
  mmss_carry_bps: number | null
  mmss_roll_bps: number | null
  mmss_carry_and_roll_bps: number | null
  mmss_carry_1m_bps: number | null
  mmss_roll_1m_bps: number | null
  mmss_carry_and_roll_1m_bps: number | null
  mmss_carry_2m_bps: number | null
  mmss_roll_2m_bps: number | null
  mmss_carry_and_roll_2m_bps: number | null
  mmss_carry_3m_bps: number | null
  mmss_roll_3m_bps: number | null
  mmss_carry_and_roll_3m_bps: number | null
  mmss_carry_6m_bps: number | null
  mmss_roll_6m_bps: number | null
  mmss_carry_and_roll_6m_bps: number | null
  issue_date: string | Date | null
  maturity_date: string | Date | null
  market_timestamp: string | Date | null
  snapshot_ts: string | Date | null
}

function buildCacheKey(payload: UstsRvSnapshotRequest) {
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

function parseTimeOfDay(raw: string | undefined): string | null {
  if (!raw || !raw.trim()) return null
  const txt = raw.trim()
  const match = txt.match(/^(\d{1,2}):(\d{2})(?::(\d{2}))?$/)
  if (!match) {
    throw new Error(
      `Invalid time '${raw}'. Expected HH:MM or HH:MM:SS in 24-hour format.`
    )
  }
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
    throw new Error(`Invalid time '${raw}'. Expected a valid 24-hour clock time.`)
  }
  return `${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}:${String(
    second
  ).padStart(2, '0')}`
}

function toFiniteNumber(value: unknown): number | null {
  if (value === null || value === undefined) return null
  const num = Number(value)
  return Number.isFinite(num) ? num : null
}

function toInteger(value: unknown): number | null {
  const num = toFiniteNumber(value)
  return num === null ? null : Math.trunc(num)
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

function normalizeDataMode(raw: unknown): UstsRvDataMode {
  return raw === 'intraday_live' ? 'intraday_live' : 'eod_live'
}

function clamp(v: number, lo: number, hi: number) {
  return Math.max(lo, Math.min(hi, v))
}

function linspace(lo: number, hi: number, count: number) {
  if (count <= 1 || hi <= lo) return [lo]
  const out = new Array<number>(count)
  const step = (hi - lo) / (count - 1)
  for (let i = 0; i < count; i += 1) out[i] = lo + step * i
  // Lock endpoints to exact bounds to avoid tiny FP drift at the tail.
  out[0] = lo
  out[count - 1] = hi
  return out
}

function pointValue(point: UstsRvPoint, key: string): number | null {
  return toFiniteNumber((point as Record<string, unknown>)[key])
}

function normalizeKnots(raw: number[] | undefined, xMin: number, xMax: number) {
  if (!Array.isArray(raw)) return []
  return Array.from(
    new Set(
      raw
        .map((v) => Number(v))
        .filter((v) => Number.isFinite(v) && v > xMin && v < xMax)
    )
  ).sort((a, b) => a - b)
}

function quantile(sorted: number[], q: number) {
  if (!sorted.length) return NaN
  if (q <= 0) return sorted[0]
  if (q >= 1) return sorted[sorted.length - 1]
  const pos = (sorted.length - 1) * q
  const lo = Math.floor(pos)
  const hi = Math.ceil(pos)
  if (lo === hi) return sorted[lo]
  const w = pos - lo
  return sorted[lo] * (1 - w) + sorted[hi] * w
}

function gaussianSolve(matrix: number[][], rhs: number[]) {
  const n = rhs.length
  const a = matrix.map((row) => row.slice())
  const b = rhs.slice()

  for (let col = 0; col < n; col += 1) {
    let pivotRow = col
    let pivotAbs = Math.abs(a[col][col])
    for (let row = col + 1; row < n; row += 1) {
      const cand = Math.abs(a[row][col])
      if (cand > pivotAbs) {
        pivotAbs = cand
        pivotRow = row
      }
    }

    if (!Number.isFinite(pivotAbs) || pivotAbs < 1e-12) return null

    if (pivotRow !== col) {
      ;[a[col], a[pivotRow]] = [a[pivotRow], a[col]]
      ;[b[col], b[pivotRow]] = [b[pivotRow], b[col]]
    }

    const pivot = a[col][col]
    for (let row = col + 1; row < n; row += 1) {
      const factor = a[row][col] / pivot
      if (!Number.isFinite(factor) || factor === 0) continue
      for (let j = col; j < n; j += 1) {
        a[row][j] -= factor * a[col][j]
      }
      b[row] -= factor * b[col]
    }
  }

  const out = new Array<number>(n).fill(0)
  for (let row = n - 1; row >= 0; row -= 1) {
    let sum = b[row]
    for (let j = row + 1; j < n; j += 1) sum -= a[row][j] * out[j]
    const pivot = a[row][row]
    if (!Number.isFinite(pivot) || Math.abs(pivot) < 1e-12) return null
    out[row] = sum / pivot
  }

  return out
}

function bsplineBasis(
  i: number,
  degree: number,
  x: number,
  knots: number[],
  lastBasisIndex: number
): number {
  if (degree === 0) {
    if (x === knots[knots.length - 1]) return i === lastBasisIndex ? 1 : 0
    return knots[i] <= x && x < knots[i + 1] ? 1 : 0
  }

  let leftTerm = 0
  const leftDen = knots[i + degree] - knots[i]
  if (leftDen > 0) {
    leftTerm =
      ((x - knots[i]) / leftDen) *
      bsplineBasis(i, degree - 1, x, knots, lastBasisIndex)
  }

  let rightTerm = 0
  const rightDen = knots[i + degree + 1] - knots[i + 1]
  if (rightDen > 0) {
    rightTerm =
      ((knots[i + degree + 1] - x) / rightDen) *
      bsplineBasis(i + 1, degree - 1, x, knots, lastBasisIndex)
  }

  return leftTerm + rightTerm
}

function loessPredict(xs: number[], ys: number[], x0: number, frac: number) {
  const n = xs.length
  if (!n) return null

  const k = Math.max(2, Math.min(n, Math.floor(frac * n)))
  const sortedDistances = xs
    .map((x) => Math.abs(x - x0))
    .sort((a, b) => a - b)
  const bandwidth = sortedDistances[Math.min(k - 1, sortedDistances.length - 1)]

  if (!Number.isFinite(bandwidth) || bandwidth <= 0) {
    let nearestIdx = 0
    let nearestDist = Math.abs(xs[0] - x0)
    for (let i = 1; i < n; i += 1) {
      const d = Math.abs(xs[i] - x0)
      if (d < nearestDist) {
        nearestDist = d
        nearestIdx = i
      }
    }
    return ys[nearestIdx]
  }

  let sw = 0
  let sx = 0
  let sy = 0
  let sxx = 0
  let sxy = 0

  for (let i = 0; i < n; i += 1) {
    const d = Math.abs(xs[i] - x0) / bandwidth
    if (d >= 1) continue
    const w = (1 - d ** 3) ** 3
    const x = xs[i]
    const y = ys[i]
    sw += w
    sx += w * x
    sy += w * y
    sxx += w * x * x
    sxy += w * x * y
  }

  if (!Number.isFinite(sw) || sw <= 0) return null

  const denom = sw * sxx - sx * sx
  if (!Number.isFinite(denom) || Math.abs(denom) < 1e-12) {
    return sy / sw
  }

  const beta = (sw * sxy - sx * sy) / denom
  const alpha = (sy - beta * sx) / sw
  return alpha + beta * x0
}

function buildSplineSeries(
  points: UstsRvPoint[],
  cfg: UstsRvSplineConfigRequest,
  fallbackXColumn: UstsRvXColumn | string,
  index: number
): UstsRvSplineSeries {
  const splineId = String(cfg.id || `spline_${index + 1}`)
  const method = cfg.method === 'loess' ? 'loess' : 'bspline'
  const name = cfg.name?.trim() || `${method.toUpperCase()} ${index + 1}`
  const xColumn = String(cfg.xColumn || fallbackXColumn)
  const valueColumn = String(cfg.valueColumn || 'mmss')
  const color = cfg.color || null
  const lineWidth = toFiniteNumber(cfg.lineWidth) ?? 2
  const pointCount = Math.round(clamp(toFiniteNumber(cfg.pointCount) ?? 350, 25, 2000))

  const xFieldExists = points.some((p) =>
    Object.prototype.hasOwnProperty.call(p, xColumn)
  )
  if (!xFieldExists) {
    return {
      id: splineId,
      name,
      method,
      valueColumn,
      xColumn,
      color,
      lineWidth,
      fitCount: 0,
      x: [],
      y: [],
      error: `Unknown xColumn '${xColumn}'`
    }
  }

  const yFieldExists = points.some((p) =>
    Object.prototype.hasOwnProperty.call(p, valueColumn)
  )
  if (!yFieldExists) {
    return {
      id: splineId,
      name,
      method,
      valueColumn,
      xColumn,
      color,
      lineWidth,
      fitCount: 0,
      x: [],
      y: [],
      error: `Unknown valueColumn '${valueColumn}'`
    }
  }

  const excludeRanks = Array.isArray(cfg.excludeRanks) && cfg.excludeRanks.length
    ? cfg.excludeRanks.map((r) => Math.trunc(Number(r))).filter(Number.isFinite)
    : [0, 1, 2]
  const excluded = new Set(excludeRanks)

  const buckets = new Map<number, { sum: number; count: number }>()
  for (const point of points) {
    if (excluded.size && point.rank !== null && excluded.has(Math.trunc(point.rank))) {
      continue
    }
    const x = pointValue(point, xColumn)
    const y = pointValue(point, valueColumn)
    if (x === null || y === null) continue

    const bucket = buckets.get(x)
    if (bucket) {
      bucket.sum += y
      bucket.count += 1
    } else {
      buckets.set(x, { sum: y, count: 1 })
    }
  }

  const dedup = Array.from(buckets.entries())
    .map(([x, agg]) => ({ x, y: agg.sum / agg.count }))
    .sort((a, b) => a.x - b.x)

  if (dedup.length < 4) {
    return {
      id: splineId,
      name,
      method,
      valueColumn,
      xColumn,
      color,
      lineWidth,
      fitCount: dedup.length,
      x: [],
      y: [],
      error: 'Need at least 4 unique x points to build spline'
    }
  }

  const xs = dedup.map((d) => d.x)
  const ys = dedup.map((d) => d.y)
  const xMinFit = xs[0]
  const xMaxFit = xs[xs.length - 1]
  const isTtmSpline = xColumn === 'ttm'
  const ttmRightBound = 30
  const ttmMaxInternalKnot = 25

  const reqMin = toFiniteNumber(cfg.xMin)
  const reqMax = toFiniteNumber(cfg.xMax)
  let xMin = reqMin ?? xMinFit
  let xMax = reqMax ?? (isTtmSpline ? ttmRightBound : xMaxFit)

  if (!(xMax > xMin)) {
    xMin = xMinFit
    xMax = isTtmSpline ? Math.max(xMaxFit, ttmRightBound) : xMaxFit
  }
  if (!(xMax > xMin)) {
    return {
      id: splineId,
      name,
      method,
      valueColumn,
      xColumn,
      color,
      lineWidth,
      fitCount: dedup.length,
      x: [],
      y: [],
      error: 'Invalid x range for spline'
    }
  }

  const xGrid = linspace(xMin, xMax, pointCount)
  let yGrid: Array<number | null> = []

  try {
    if (method === 'loess') {
      const frac = clamp(toFiniteNumber(cfg.frac) ?? 0.25, 0.05, 1.0)
      yGrid = xGrid.map((x) => loessPredict(xs, ys, x, frac))
    } else {
      let degree = Math.round(clamp(toFiniteNumber(cfg.degree) ?? 2, 1, 5))
      if (xs.length <= degree) degree = Math.max(1, xs.length - 1)

      let internalKnots = normalizeKnots(cfg.knots, xMinFit, xMax)
      if (isTtmSpline) {
        internalKnots = internalKnots.filter((k) => k <= ttmMaxInternalKnot)
      }
      const maxInternal = Math.max(0, xs.length - degree - 1)
      if (!internalKnots.length && maxInternal > 0) {
        const sortedX = xs.slice().sort((a, b) => a - b)
        const autoCount = Math.min(maxInternal, Math.max(2, Math.floor(xs.length / 8)))
        const auto = new Set<number>()
        for (let i = 1; i <= autoCount; i += 1) {
          const q = i / (autoCount + 1)
          const knot = quantile(sortedX, q)
          if (Number.isFinite(knot) && knot > xMinFit && knot < xMax) auto.add(knot)
        }
        if (isTtmSpline && ttmMaxInternalKnot > xMinFit && ttmMaxInternalKnot < xMax) {
          auto.add(ttmMaxInternalKnot)
        }
        internalKnots = Array.from(auto).sort((a, b) => a - b).slice(0, maxInternal)
      } else if (internalKnots.length > maxInternal) {
        internalKnots = internalKnots.slice(0, maxInternal)
      }

      const knotVector = [
        ...new Array(degree + 1).fill(xMinFit),
        ...internalKnots,
        ...new Array(degree + 1).fill(xMax)
      ]
      const nBasis = knotVector.length - degree - 1
      if (nBasis <= 0) {
        throw new Error('Failed to build B-spline basis')
      }

      const basisRows = xs.map((x) => {
        const row = new Array<number>(nBasis)
        for (let j = 0; j < nBasis; j += 1) {
          row[j] = bsplineBasis(j, degree, x, knotVector, nBasis - 1)
        }
        return row
      })

      const ata = Array.from({ length: nBasis }, () => new Array(nBasis).fill(0))
      const aty = new Array<number>(nBasis).fill(0)

      for (let r = 0; r < basisRows.length; r += 1) {
        const row = basisRows[r]
        const y = ys[r]
        for (let i = 0; i < nBasis; i += 1) {
          aty[i] += row[i] * y
          for (let j = 0; j < nBasis; j += 1) {
            ata[i][j] += row[i] * row[j]
          }
        }
      }

      for (let i = 0; i < nBasis; i += 1) {
        ata[i][i] += 1e-8
      }

      const coeffs = gaussianSolve(ata, aty)
      if (!coeffs) throw new Error('Unable to solve B-spline coefficients')

      yGrid = xGrid.map((x) => {
        // Clamp eval domain so we never emit artificial zeros outside knot support.
        const xEval = clamp(x, xMinFit, xMax)
        let y = 0
        for (let j = 0; j < nBasis; j += 1) {
          y += coeffs[j] * bsplineBasis(j, degree, xEval, knotVector, nBasis - 1)
        }
        return y
      })
    }
  } catch (error: any) {
    return {
      id: splineId,
      name,
      method,
      valueColumn,
      xColumn,
      color,
      lineWidth,
      fitCount: dedup.length,
      x: [],
      y: [],
      error: error?.message || String(error)
    }
  }

  const xOut: number[] = []
  const yOut: number[] = []
  for (let i = 0; i < xGrid.length; i += 1) {
    const y = yGrid[i]
    if (!Number.isFinite(xGrid[i]) || !Number.isFinite(y as number)) continue
    xOut.push(xGrid[i])
    yOut.push(y as number)
  }

  return {
    id: splineId,
    name,
    method,
    valueColumn,
    xColumn,
    color,
    lineWidth,
    fitCount: dedup.length,
    x: xOut,
    y: yOut,
    error: null
  }
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

async function resolveIntradaySnapshot(
  curveName: string,
  requestedAsOf: string,
  requestedAsOfTime: string | null
) {
  const warnings: string[] = []

  const preferred = requestedAsOfTime
    ? await query<IntradaySnapshotRow>(
        `
          SELECT
            as_of_date::date AS as_of_date,
            market_timestamp
          FROM ${INTRADAY_POINTS_TABLE}
          WHERE curve_name = $1
            AND market_timestamp <= (($2::date + $3::time) AT TIME ZONE 'America/New_York')
          ORDER BY market_timestamp DESC
          LIMIT 1
        `,
        [curveName, requestedAsOf, requestedAsOfTime]
      )
    : await query<IntradaySnapshotRow>(
        `
          SELECT
            as_of_date::date AS as_of_date,
            market_timestamp
          FROM ${INTRADAY_POINTS_TABLE}
          WHERE curve_name = $1
            AND as_of_date <= $2::date
          ORDER BY market_timestamp DESC
          LIMIT 1
        `,
        [curveName, requestedAsOf]
      )

  let selectedAsOf = toIsoDate(preferred.rows[0]?.as_of_date)
  let selectedMarketTimestamp = toIsoTimestamp(preferred.rows[0]?.market_timestamp)

  if (!selectedAsOf || !selectedMarketTimestamp) {
    const latestAny = await query<IntradaySnapshotRow>(
      `
        SELECT
          as_of_date::date AS as_of_date,
          market_timestamp
        FROM ${INTRADAY_POINTS_TABLE}
        WHERE curve_name = $1
        ORDER BY market_timestamp DESC
        LIMIT 1
      `,
      [curveName]
    )

    selectedAsOf = toIsoDate(latestAny.rows[0]?.as_of_date)
    selectedMarketTimestamp = toIsoTimestamp(latestAny.rows[0]?.market_timestamp)
    if (selectedAsOf && selectedMarketTimestamp) {
      if (requestedAsOfTime) {
        warnings.push(
          `No intraday DB snapshot found on/before ${requestedAsOf} ${requestedAsOfTime} America/New_York; using latest available ${selectedAsOf} @ ${selectedMarketTimestamp}.`
        )
      } else {
        warnings.push(
          `No intraday DB snapshot found on/before ${requestedAsOf}; using latest available ${selectedAsOf} @ ${selectedMarketTimestamp}.`
        )
      }
    }
  }

  if (!selectedAsOf || !selectedMarketTimestamp) {
    throw new Error(
      `No UST RV intraday snapshots found in ${INTRADAY_POINTS_TABLE} for curve '${curveName}'. Run ingest_ustrv.py --mode intraday first.`
    )
  }

  if (selectedAsOf !== requestedAsOf) {
    warnings.push(
      `Using intraday DB asOf ${selectedAsOf} for requested ${requestedAsOf}.`
    )
  }
  if (requestedAsOfTime) {
    warnings.push(
      `Requested intraday cutoff: ${requestedAsOf} ${requestedAsOfTime} America/New_York.`
    )
  }

  return { selectedAsOf, selectedMarketTimestamp, warnings }
}

async function loadPoints(
  curveName: string,
  asOf: string,
  minTtm: number
): Promise<{ points: UstsRvPoint[]; latestSnapshotTs: string | null }> {
  const result = await query<PointRow>(
    `
      SELECT
        cusip,
        oi,
        ust_label,
        rank::int AS rank,
        ttm::double precision AS ttm,
        mdur::double precision AS mdur,
        ytm::double precision AS ytm,
        mmss::double precision AS mmss,
        clean_price::double precision AS clean_price,
        dirty_price::double precision AS dirty_price,
        coupon::double precision AS coupon,
        carry_bps::double precision AS carry_bps,
        roll_bps::double precision AS roll_bps,
        carry_and_roll_bps::double precision AS carry_and_roll_bps,
        carry_1m_bps::double precision AS carry_1m_bps,
        roll_1m_bps::double precision AS roll_1m_bps,
        carry_and_roll_1m_bps::double precision AS carry_and_roll_1m_bps,
        carry_2m_bps::double precision AS carry_2m_bps,
        roll_2m_bps::double precision AS roll_2m_bps,
        carry_and_roll_2m_bps::double precision AS carry_and_roll_2m_bps,
        carry_3m_bps::double precision AS carry_3m_bps,
        roll_3m_bps::double precision AS roll_3m_bps,
        carry_and_roll_3m_bps::double precision AS carry_and_roll_3m_bps,
        carry_6m_bps::double precision AS carry_6m_bps,
        roll_6m_bps::double precision AS roll_6m_bps,
        carry_and_roll_6m_bps::double precision AS carry_and_roll_6m_bps,
        swap_carry_bps::double precision AS swap_carry_bps,
        swap_roll_bps::double precision AS swap_roll_bps,
        swap_carry_and_roll_bps::double precision AS swap_carry_and_roll_bps,
        swap_carry_1m_bps::double precision AS swap_carry_1m_bps,
        swap_roll_1m_bps::double precision AS swap_roll_1m_bps,
        swap_carry_and_roll_1m_bps::double precision AS swap_carry_and_roll_1m_bps,
        swap_carry_2m_bps::double precision AS swap_carry_2m_bps,
        swap_roll_2m_bps::double precision AS swap_roll_2m_bps,
        swap_carry_and_roll_2m_bps::double precision AS swap_carry_and_roll_2m_bps,
        swap_carry_3m_bps::double precision AS swap_carry_3m_bps,
        swap_roll_3m_bps::double precision AS swap_roll_3m_bps,
        swap_carry_and_roll_3m_bps::double precision AS swap_carry_and_roll_3m_bps,
        swap_carry_6m_bps::double precision AS swap_carry_6m_bps,
        swap_roll_6m_bps::double precision AS swap_roll_6m_bps,
        swap_carry_and_roll_6m_bps::double precision AS swap_carry_and_roll_6m_bps,
        mmss_carry_bps::double precision AS mmss_carry_bps,
        mmss_roll_bps::double precision AS mmss_roll_bps,
        mmss_carry_and_roll_bps::double precision AS mmss_carry_and_roll_bps,
        mmss_carry_1m_bps::double precision AS mmss_carry_1m_bps,
        mmss_roll_1m_bps::double precision AS mmss_roll_1m_bps,
        mmss_carry_and_roll_1m_bps::double precision AS mmss_carry_and_roll_1m_bps,
        mmss_carry_2m_bps::double precision AS mmss_carry_2m_bps,
        mmss_roll_2m_bps::double precision AS mmss_roll_2m_bps,
        mmss_carry_and_roll_2m_bps::double precision AS mmss_carry_and_roll_2m_bps,
        mmss_carry_3m_bps::double precision AS mmss_carry_3m_bps,
        mmss_roll_3m_bps::double precision AS mmss_roll_3m_bps,
        mmss_carry_and_roll_3m_bps::double precision AS mmss_carry_and_roll_3m_bps,
        mmss_carry_6m_bps::double precision AS mmss_carry_6m_bps,
        mmss_roll_6m_bps::double precision AS mmss_roll_6m_bps,
        mmss_carry_and_roll_6m_bps::double precision AS mmss_carry_and_roll_6m_bps,
        issue_date,
        maturity_date,
        market_timestamp,
        snapshot_ts
      FROM ${POINTS_TABLE}
      WHERE curve_name = $1
        AND as_of_date = $2::date
        AND (ttm IS NULL OR ttm >= $3::double precision)
      ORDER BY ttm NULLS LAST, oi NULLS LAST, rank NULLS LAST, cusip
    `,
    [curveName, asOf, minTtm]
  )

  const points: UstsRvPoint[] = []
  let latestSnapshotTs: string | null = null
  let latestSnapshotMs = -Infinity

  for (const row of result.rows) {
    const cusip = row.cusip ? String(row.cusip) : ''
    if (!cusip) continue

    const snapshotTs = toIsoTimestamp(row.snapshot_ts)
    if (snapshotTs) {
      const tsMs = new Date(snapshotTs).getTime()
      if (Number.isFinite(tsMs) && tsMs > latestSnapshotMs) {
        latestSnapshotMs = tsMs
        latestSnapshotTs = snapshotTs
      }
    }

    points.push({
      cusip,
      ust_label: row.ust_label ?? null,
      oi: row.oi ?? null,
      rank: toInteger(row.rank),
      ttm: toFiniteNumber(row.ttm),
      mdur: toFiniteNumber(row.mdur),
      ytm: toFiniteNumber(row.ytm),
      mmss: toFiniteNumber(row.mmss),
      clean_price: toFiniteNumber(row.clean_price),
      dirty_price: toFiniteNumber(row.dirty_price),
      coupon: toFiniteNumber(row.coupon),
      carry_bps: toFiniteNumber(row.carry_bps),
      roll_bps: toFiniteNumber(row.roll_bps),
      carry_and_roll_bps: toFiniteNumber(row.carry_and_roll_bps),
      carry_1m_bps: toFiniteNumber(row.carry_1m_bps),
      roll_1m_bps: toFiniteNumber(row.roll_1m_bps),
      carry_and_roll_1m_bps: toFiniteNumber(row.carry_and_roll_1m_bps),
      carry_2m_bps: toFiniteNumber(row.carry_2m_bps),
      roll_2m_bps: toFiniteNumber(row.roll_2m_bps),
      carry_and_roll_2m_bps: toFiniteNumber(row.carry_and_roll_2m_bps),
      carry_3m_bps: toFiniteNumber(row.carry_3m_bps),
      roll_3m_bps: toFiniteNumber(row.roll_3m_bps),
      carry_and_roll_3m_bps: toFiniteNumber(row.carry_and_roll_3m_bps),
      carry_6m_bps: toFiniteNumber(row.carry_6m_bps),
      roll_6m_bps: toFiniteNumber(row.roll_6m_bps),
      carry_and_roll_6m_bps: toFiniteNumber(row.carry_and_roll_6m_bps),
      swap_carry_bps: toFiniteNumber(row.swap_carry_bps),
      swap_roll_bps: toFiniteNumber(row.swap_roll_bps),
      swap_carry_and_roll_bps: toFiniteNumber(row.swap_carry_and_roll_bps),
      swap_carry_1m_bps: toFiniteNumber(row.swap_carry_1m_bps),
      swap_roll_1m_bps: toFiniteNumber(row.swap_roll_1m_bps),
      swap_carry_and_roll_1m_bps: toFiniteNumber(row.swap_carry_and_roll_1m_bps),
      swap_carry_2m_bps: toFiniteNumber(row.swap_carry_2m_bps),
      swap_roll_2m_bps: toFiniteNumber(row.swap_roll_2m_bps),
      swap_carry_and_roll_2m_bps: toFiniteNumber(row.swap_carry_and_roll_2m_bps),
      swap_carry_3m_bps: toFiniteNumber(row.swap_carry_3m_bps),
      swap_roll_3m_bps: toFiniteNumber(row.swap_roll_3m_bps),
      swap_carry_and_roll_3m_bps: toFiniteNumber(row.swap_carry_and_roll_3m_bps),
      swap_carry_6m_bps: toFiniteNumber(row.swap_carry_6m_bps),
      swap_roll_6m_bps: toFiniteNumber(row.swap_roll_6m_bps),
      swap_carry_and_roll_6m_bps: toFiniteNumber(row.swap_carry_and_roll_6m_bps),
      mmss_carry_bps: toFiniteNumber(row.mmss_carry_bps),
      mmss_roll_bps: toFiniteNumber(row.mmss_roll_bps),
      mmss_carry_and_roll_bps: toFiniteNumber(row.mmss_carry_and_roll_bps),
      mmss_carry_1m_bps: toFiniteNumber(row.mmss_carry_1m_bps),
      mmss_roll_1m_bps: toFiniteNumber(row.mmss_roll_1m_bps),
      mmss_carry_and_roll_1m_bps: toFiniteNumber(row.mmss_carry_and_roll_1m_bps),
      mmss_carry_2m_bps: toFiniteNumber(row.mmss_carry_2m_bps),
      mmss_roll_2m_bps: toFiniteNumber(row.mmss_roll_2m_bps),
      mmss_carry_and_roll_2m_bps: toFiniteNumber(row.mmss_carry_and_roll_2m_bps),
      mmss_carry_3m_bps: toFiniteNumber(row.mmss_carry_3m_bps),
      mmss_roll_3m_bps: toFiniteNumber(row.mmss_roll_3m_bps),
      mmss_carry_and_roll_3m_bps: toFiniteNumber(row.mmss_carry_and_roll_3m_bps),
      mmss_carry_6m_bps: toFiniteNumber(row.mmss_carry_6m_bps),
      mmss_roll_6m_bps: toFiniteNumber(row.mmss_roll_6m_bps),
      mmss_carry_and_roll_6m_bps: toFiniteNumber(row.mmss_carry_and_roll_6m_bps),
      issue_date: toIsoDate(row.issue_date),
      maturity_date: toIsoDate(row.maturity_date),
      market_timestamp: toIsoTimestamp(row.market_timestamp)
    })
  }

  return { points, latestSnapshotTs }
}

async function loadIntradayPoints(
  curveName: string,
  marketTimestamp: string,
  minTtm: number
): Promise<{ points: UstsRvPoint[]; latestSnapshotTs: string | null }> {
  const result = await query<PointRow>(
    `
      SELECT
        cusip,
        oi,
        ust_label,
        rank::int AS rank,
        ttm::double precision AS ttm,
        mdur::double precision AS mdur,
        ytm::double precision AS ytm,
        mmss::double precision AS mmss,
        clean_price::double precision AS clean_price,
        dirty_price::double precision AS dirty_price,
        coupon::double precision AS coupon,
        carry_bps::double precision AS carry_bps,
        roll_bps::double precision AS roll_bps,
        carry_and_roll_bps::double precision AS carry_and_roll_bps,
        carry_1m_bps::double precision AS carry_1m_bps,
        roll_1m_bps::double precision AS roll_1m_bps,
        carry_and_roll_1m_bps::double precision AS carry_and_roll_1m_bps,
        carry_2m_bps::double precision AS carry_2m_bps,
        roll_2m_bps::double precision AS roll_2m_bps,
        carry_and_roll_2m_bps::double precision AS carry_and_roll_2m_bps,
        carry_3m_bps::double precision AS carry_3m_bps,
        roll_3m_bps::double precision AS roll_3m_bps,
        carry_and_roll_3m_bps::double precision AS carry_and_roll_3m_bps,
        carry_6m_bps::double precision AS carry_6m_bps,
        roll_6m_bps::double precision AS roll_6m_bps,
        carry_and_roll_6m_bps::double precision AS carry_and_roll_6m_bps,
        swap_carry_bps::double precision AS swap_carry_bps,
        swap_roll_bps::double precision AS swap_roll_bps,
        swap_carry_and_roll_bps::double precision AS swap_carry_and_roll_bps,
        swap_carry_1m_bps::double precision AS swap_carry_1m_bps,
        swap_roll_1m_bps::double precision AS swap_roll_1m_bps,
        swap_carry_and_roll_1m_bps::double precision AS swap_carry_and_roll_1m_bps,
        swap_carry_2m_bps::double precision AS swap_carry_2m_bps,
        swap_roll_2m_bps::double precision AS swap_roll_2m_bps,
        swap_carry_and_roll_2m_bps::double precision AS swap_carry_and_roll_2m_bps,
        swap_carry_3m_bps::double precision AS swap_carry_3m_bps,
        swap_roll_3m_bps::double precision AS swap_roll_3m_bps,
        swap_carry_and_roll_3m_bps::double precision AS swap_carry_and_roll_3m_bps,
        swap_carry_6m_bps::double precision AS swap_carry_6m_bps,
        swap_roll_6m_bps::double precision AS swap_roll_6m_bps,
        swap_carry_and_roll_6m_bps::double precision AS swap_carry_and_roll_6m_bps,
        mmss_carry_bps::double precision AS mmss_carry_bps,
        mmss_roll_bps::double precision AS mmss_roll_bps,
        mmss_carry_and_roll_bps::double precision AS mmss_carry_and_roll_bps,
        mmss_carry_1m_bps::double precision AS mmss_carry_1m_bps,
        mmss_roll_1m_bps::double precision AS mmss_roll_1m_bps,
        mmss_carry_and_roll_1m_bps::double precision AS mmss_carry_and_roll_1m_bps,
        mmss_carry_2m_bps::double precision AS mmss_carry_2m_bps,
        mmss_roll_2m_bps::double precision AS mmss_roll_2m_bps,
        mmss_carry_and_roll_2m_bps::double precision AS mmss_carry_and_roll_2m_bps,
        mmss_carry_3m_bps::double precision AS mmss_carry_3m_bps,
        mmss_roll_3m_bps::double precision AS mmss_roll_3m_bps,
        mmss_carry_and_roll_3m_bps::double precision AS mmss_carry_and_roll_3m_bps,
        mmss_carry_6m_bps::double precision AS mmss_carry_6m_bps,
        mmss_roll_6m_bps::double precision AS mmss_roll_6m_bps,
        mmss_carry_and_roll_6m_bps::double precision AS mmss_carry_and_roll_6m_bps,
        issue_date,
        maturity_date,
        market_timestamp,
        snapshot_ts
      FROM ${INTRADAY_POINTS_TABLE}
      WHERE curve_name = $1
        AND market_timestamp = $2::timestamptz
        AND (ttm IS NULL OR ttm >= $3::double precision)
      ORDER BY ttm NULLS LAST, oi NULLS LAST, rank NULLS LAST, cusip
    `,
    [curveName, marketTimestamp, minTtm]
  )

  const points: UstsRvPoint[] = []
  let latestSnapshotTs: string | null = null
  let latestSnapshotMs = -Infinity

  for (const row of result.rows) {
    const cusip = row.cusip ? String(row.cusip) : ''
    if (!cusip) continue

    const snapshotTs = toIsoTimestamp(row.snapshot_ts)
    if (snapshotTs) {
      const tsMs = new Date(snapshotTs).getTime()
      if (Number.isFinite(tsMs) && tsMs > latestSnapshotMs) {
        latestSnapshotMs = tsMs
        latestSnapshotTs = snapshotTs
      }
    }

    points.push({
      cusip,
      ust_label: row.ust_label ?? null,
      oi: row.oi ?? null,
      rank: toInteger(row.rank),
      ttm: toFiniteNumber(row.ttm),
      mdur: toFiniteNumber(row.mdur),
      ytm: toFiniteNumber(row.ytm),
      mmss: toFiniteNumber(row.mmss),
      clean_price: toFiniteNumber(row.clean_price),
      dirty_price: toFiniteNumber(row.dirty_price),
      coupon: toFiniteNumber(row.coupon),
      carry_bps: toFiniteNumber(row.carry_bps),
      roll_bps: toFiniteNumber(row.roll_bps),
      carry_and_roll_bps: toFiniteNumber(row.carry_and_roll_bps),
      carry_1m_bps: toFiniteNumber(row.carry_1m_bps),
      roll_1m_bps: toFiniteNumber(row.roll_1m_bps),
      carry_and_roll_1m_bps: toFiniteNumber(row.carry_and_roll_1m_bps),
      carry_2m_bps: toFiniteNumber(row.carry_2m_bps),
      roll_2m_bps: toFiniteNumber(row.roll_2m_bps),
      carry_and_roll_2m_bps: toFiniteNumber(row.carry_and_roll_2m_bps),
      carry_3m_bps: toFiniteNumber(row.carry_3m_bps),
      roll_3m_bps: toFiniteNumber(row.roll_3m_bps),
      carry_and_roll_3m_bps: toFiniteNumber(row.carry_and_roll_3m_bps),
      carry_6m_bps: toFiniteNumber(row.carry_6m_bps),
      roll_6m_bps: toFiniteNumber(row.roll_6m_bps),
      carry_and_roll_6m_bps: toFiniteNumber(row.carry_and_roll_6m_bps),
      swap_carry_bps: toFiniteNumber(row.swap_carry_bps),
      swap_roll_bps: toFiniteNumber(row.swap_roll_bps),
      swap_carry_and_roll_bps: toFiniteNumber(row.swap_carry_and_roll_bps),
      swap_carry_1m_bps: toFiniteNumber(row.swap_carry_1m_bps),
      swap_roll_1m_bps: toFiniteNumber(row.swap_roll_1m_bps),
      swap_carry_and_roll_1m_bps: toFiniteNumber(row.swap_carry_and_roll_1m_bps),
      swap_carry_2m_bps: toFiniteNumber(row.swap_carry_2m_bps),
      swap_roll_2m_bps: toFiniteNumber(row.swap_roll_2m_bps),
      swap_carry_and_roll_2m_bps: toFiniteNumber(row.swap_carry_and_roll_2m_bps),
      swap_carry_3m_bps: toFiniteNumber(row.swap_carry_3m_bps),
      swap_roll_3m_bps: toFiniteNumber(row.swap_roll_3m_bps),
      swap_carry_and_roll_3m_bps: toFiniteNumber(row.swap_carry_and_roll_3m_bps),
      swap_carry_6m_bps: toFiniteNumber(row.swap_carry_6m_bps),
      swap_roll_6m_bps: toFiniteNumber(row.swap_roll_6m_bps),
      swap_carry_and_roll_6m_bps: toFiniteNumber(row.swap_carry_and_roll_6m_bps),
      mmss_carry_bps: toFiniteNumber(row.mmss_carry_bps),
      mmss_roll_bps: toFiniteNumber(row.mmss_roll_bps),
      mmss_carry_and_roll_bps: toFiniteNumber(row.mmss_carry_and_roll_bps),
      mmss_carry_1m_bps: toFiniteNumber(row.mmss_carry_1m_bps),
      mmss_roll_1m_bps: toFiniteNumber(row.mmss_roll_1m_bps),
      mmss_carry_and_roll_1m_bps: toFiniteNumber(row.mmss_carry_and_roll_1m_bps),
      mmss_carry_2m_bps: toFiniteNumber(row.mmss_carry_2m_bps),
      mmss_roll_2m_bps: toFiniteNumber(row.mmss_roll_2m_bps),
      mmss_carry_and_roll_2m_bps: toFiniteNumber(row.mmss_carry_and_roll_2m_bps),
      mmss_carry_3m_bps: toFiniteNumber(row.mmss_carry_3m_bps),
      mmss_roll_3m_bps: toFiniteNumber(row.mmss_roll_3m_bps),
      mmss_carry_and_roll_3m_bps: toFiniteNumber(row.mmss_carry_and_roll_3m_bps),
      mmss_carry_6m_bps: toFiniteNumber(row.mmss_carry_6m_bps),
      mmss_roll_6m_bps: toFiniteNumber(row.mmss_roll_6m_bps),
      mmss_carry_and_roll_6m_bps: toFiniteNumber(row.mmss_carry_and_roll_6m_bps),
      issue_date: toIsoDate(row.issue_date),
      maturity_date: toIsoDate(row.maturity_date),
      market_timestamp: toIsoTimestamp(row.market_timestamp)
    })
  }

  return { points, latestSnapshotTs }
}

export async function getUstsRvSnapshot(
  payload: UstsRvSnapshotRequest
): Promise<UstsRvSnapshotResponse> {
  const dataMode = normalizeDataMode(payload.dataMode ?? DEFAULT_DATA_MODE)
  const normalizedPayload: UstsRvSnapshotRequest = {
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

  const curveName = (payload.curveName || DEFAULT_CURVE).trim() || DEFAULT_CURVE
  const xColumn = payload.xColumn || 'ttm'
  const includeValues = payload.includeValues?.length
    ? payload.includeValues.map((v) => String(v))
    : ['mmss', 'ytm']
  const minTtm = Number.isFinite(Number(payload.minTtm))
    ? Number(payload.minTtm)
    : DEFAULT_MIN_TTM
  const { requestedAsOf, requestedLive } = parseAsOf(payload.asOf)
  let selectedAsOf = requestedAsOf
  let warnings: string[] = []
  let points: UstsRvPoint[] = []
  let latestSnapshotTs: string | null = null

  if (dataMode === 'intraday_live') {
    const requestedAsOfTime = parseTimeOfDay(payload.asOfTime)
    const intradayResolution = await resolveIntradaySnapshot(
      curveName,
      requestedAsOf,
      requestedAsOfTime
    )
    selectedAsOf = intradayResolution.selectedAsOf
    warnings = [...intradayResolution.warnings]

    const intradayPoints = await loadIntradayPoints(
      curveName,
      intradayResolution.selectedMarketTimestamp,
      minTtm
    )
    points = intradayPoints.points
    latestSnapshotTs = intradayPoints.latestSnapshotTs
    warnings.push(`Intraday snapshot timestamp: ${intradayResolution.selectedMarketTimestamp}`)
  } else {
    const eodResolution = await resolveSnapshotDate(curveName, requestedAsOf)
    selectedAsOf = eodResolution.selectedAsOf
    warnings = [...eodResolution.warnings]

    const eodPoints = await loadPoints(curveName, selectedAsOf, minTtm)
    points = eodPoints.points
    latestSnapshotTs = eodPoints.latestSnapshotTs
  }

  const splineSeries: UstsRvSplineSeries[] = []
  for (let i = 0; i < (payload.splineConfigs || []).length; i += 1) {
    const cfg = payload.splineConfigs?.[i]
    if (!cfg || cfg.enabled === false) continue
    splineSeries.push(buildSplineSeries(points, cfg, xColumn, i))
  }

  const parsed: UstsRvSnapshotResponse = {
    requestedAsOf,
    asOf: selectedAsOf,
    requestedLive,
    dataMode,
    curveName,
    xColumn,
    includeValues,
    availableValueColumns: AVAILABLE_VALUE_COLUMNS,
    points,
    splineSeries,
    meta: {
      asOf: selectedAsOf,
      pointCount: points.length,
      curveName,
      warnings: latestSnapshotTs
        ? [...warnings, `Snapshot timestamp: ${latestSnapshotTs}`]
        : warnings
    }
  }

  responseCache.set(cacheKey, { createdAt: now, value: parsed })
  return parsed
}
