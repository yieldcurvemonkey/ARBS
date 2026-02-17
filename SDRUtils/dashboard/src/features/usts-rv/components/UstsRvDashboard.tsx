'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import type {
  UstsRvSplineConfigRequest,
  UstsRvSnapshotRequest,
  UstsRvSnapshotResponse,
  UstsRvTimeseriesRequest,
  UstsRvTimeseriesResponse,
  UstsRvTimeseriesSeries,
  UstsRvValueColumn,
  UstsRvXColumn
} from '@/features/usts-rv/types'

const VALUE_OPTIONS: Array<{ key: UstsRvValueColumn; label: string }> = [
  { key: 'mmss', label: 'MMSS' },
  { key: 'ytm', label: 'YTM' },
  { key: 'clean_price', label: 'Clean Price' },
  { key: 'dirty_price', label: 'Dirty Price' },
  { key: 'mdur', label: 'Mod Duration' },
  { key: 'coupon', label: 'Coupon' }
]

const X_OPTIONS: Array<{ key: UstsRvXColumn; label: string }> = [
  { key: 'ttm', label: 'Time To Maturity' },
  { key: 'mdur', label: 'Mod Duration' }
]

const OI_COLOR_PALETTE = [
  '#38bdf8',
  '#f97316',
  '#22c55e',
  '#f43f5e',
  '#a78bfa',
  '#eab308',
  '#14b8a6',
  '#fb7185',
  '#60a5fa',
  '#84cc16',
  '#f59e0b',
  '#06b6d4'
]

const VALUE_SYMBOLS: Record<UstsRvValueColumn, string> = {
  mmss: 'circle',
  ytm: 'diamond',
  clean_price: 'square',
  dirty_price: 'cross',
  mdur: 'triangle-up',
  coupon: 'triangle-down'
}

type PlotViewport = {
  xRange: [number, number] | null
  yRange: [number, number] | null
  autoX: boolean
  autoY: boolean
}

type UstsRvSelectedBond = {
  cusip: string
  ust_label: string | null
  oi: string | null
  rank: number | null
  sourceCusip: string | null
  isConstantMaturity: boolean
}

type TimeseriesTechnicals = {
  sma20: boolean
  sma50: boolean
  ema20: boolean
  ema50: boolean
}

type TimeseriesAxis = 'y' | 'y2'

type TimeseriesFormulaLegDraft = {
  id: string
  cusip: string
  weight: number
}

type TimeseriesFormulaLeg = {
  cusip: string
  weight: number
}

type TimeseriesFormulaConfig = {
  id: string
  name: string
  yaxis: TimeseriesAxis
  scaleBy100: boolean
  legs: TimeseriesFormulaLeg[]
}

type TimeseriesFormulaSeries = {
  id: string
  name: string
  yaxis: TimeseriesAxis
  scaleBy100: boolean
  expression: string
  points: Array<{ asOf: string; value: number | null }>
  nonNullCount: number
}

type TimeseriesQuickSpreadPreset = {
  id: string
  name: string
  description: string
  yaxis: TimeseriesAxis
  scaleBy100?: boolean
  legs: TimeseriesFormulaLeg[]
}

type SplinePreset = {
  id: string
  name: string
  description: string
  config: UstsRvSplineConfigRequest
}

const SPLINE_PRESETS: SplinePreset[] = [
  {
    id: 'mmss_bspline_d1_piecewise',
    name: 'MMSS B-Spline D1 Piecewise',
    description: 'Degree 1 with front/belly/long-end knots',
    config: {
      id: 'mmss_bspline_d1_piecewise',
      method: 'bspline',
      valueColumn: 'mmss',
      color: '#f97316',
      lineWidth: 2,
      degree: 1,
      knots: [2, 4, 7, 10, 20],
      excludeRanks: [0, 1, 2]
    }
  },
  {
    id: 'mmss_bspline_d2_balanced',
    name: 'MMSS B-Spline D2 Balanced',
    description: 'Degree 2 balanced curve with broad tenor knots',
    config: {
      id: 'mmss_bspline_d2_balanced',
      method: 'bspline',
      valueColumn: 'mmss',
      color: '#fb923c',
      lineWidth: 2.1,
      degree: 2,
      knots: [2, 3, 5, 7, 10, 20, 25],
      excludeRanks: [0, 1, 2]
    }
  },
  {
    id: 'mmss_bspline_d3_curvy',
    name: 'MMSS B-Spline D3 Curvy',
    description: 'Degree 3 curve emphasizing subtle humps',
    config: {
      id: 'mmss_bspline_d3_curvy',
      method: 'bspline',
      valueColumn: 'mmss',
      color: '#f59e0b',
      lineWidth: 2.2,
      degree: 3,
      knots: [2, 4, 6, 9, 12, 20, 30],
      excludeRanks: [0, 1, 2]
    }
  },
  {
    id: 'mmss_bspline_d4_ultrasmooth',
    name: 'MMSS B-Spline D4 Ultra Smooth',
    description: 'Degree 4 smoother macro shape fit',
    config: {
      id: 'mmss_bspline_d4_ultrasmooth',
      method: 'bspline',
      valueColumn: 'mmss',
      color: '#ef4444',
      lineWidth: 2.25,
      degree: 4,
      knots: [3, 5, 8, 12, 20],
      excludeRanks: [0, 1, 2]
    }
  },
  {
    id: 'mmss_loess_tight',
    name: 'MMSS LOESS Tight',
    description: 'LOESS with smaller neighborhood for local shape',
    config: {
      id: 'mmss_loess_tight',
      method: 'loess',
      valueColumn: 'mmss',
      color: '#f43f5e',
      lineWidth: 2.05,
      frac: 0.18,
      it: 50,
      excludeRanks: [0, 1, 2]
    }
  },
  {
    id: 'mmss_loess_smooth',
    name: 'MMSS LOESS Smooth',
    description: 'LOESS with larger neighborhood for trend view',
    config: {
      id: 'mmss_loess_smooth',
      method: 'loess',
      valueColumn: 'mmss',
      color: '#e11d48',
      lineWidth: 2.2,
      frac: 0.35,
      it: 50,
      excludeRanks: [0, 1, 2]
    }
  },
  {
    id: 'ytm_bspline_d2_balanced',
    name: 'YTM B-Spline D2 Balanced',
    description: 'Degree 2 YTM spline with benchmark knots',
    config: {
      id: 'ytm_bspline_d2_balanced',
      method: 'bspline',
      valueColumn: 'ytm',
      color: '#38bdf8',
      lineWidth: 2,
      degree: 2,
      knots: [2, 3, 5, 7, 10, 20, 30],
      excludeRanks: [0, 1, 2]
    }
  },
  {
    id: 'ytm_bspline_d3_curvy',
    name: 'YTM B-Spline D3 Curvy',
    description: 'Degree 3 YTM fit for richer curvature',
    config: {
      id: 'ytm_bspline_d3_curvy',
      method: 'bspline',
      valueColumn: 'ytm',
      color: '#0ea5e9',
      lineWidth: 2.1,
      degree: 3,
      knots: [1.5, 3, 5, 8, 12, 20, 30],
      excludeRanks: [0, 1, 2]
    }
  },
  {
    id: 'ytm_loess_mid',
    name: 'YTM LOESS Mid',
    description: 'LOESS mid smoothing for YTM term-structure',
    config: {
      id: 'ytm_loess_mid',
      method: 'loess',
      valueColumn: 'ytm',
      color: '#22d3ee',
      lineWidth: 2.05,
      frac: 0.27,
      it: 50,
      excludeRanks: [0, 1, 2]
    }
  },
  {
    id: 'clean_px_bspline_d2',
    name: 'Clean Price B-Spline D2',
    description: 'Clean price shape with degree 2 knots',
    config: {
      id: 'clean_px_bspline_d2',
      method: 'bspline',
      valueColumn: 'clean_price',
      color: '#22c55e',
      lineWidth: 2,
      degree: 2,
      knots: [2, 4, 7, 10, 20, 30],
      excludeRanks: [0, 1, 2]
    }
  },
  {
    id: 'dirty_px_bspline_d2',
    name: 'Dirty Price B-Spline D2',
    description: 'Dirty price shape with degree 2 knots',
    config: {
      id: 'dirty_px_bspline_d2',
      method: 'bspline',
      valueColumn: 'dirty_price',
      color: '#a78bfa',
      lineWidth: 2,
      degree: 2,
      knots: [2, 4, 7, 10, 20, 30],
      excludeRanks: [0, 1, 2]
    }
  },
  {
    id: 'mdur_bspline_d2',
    name: 'MDur B-Spline D2',
    description: 'Modified duration spline with broad knots',
    config: {
      id: 'mdur_bspline_d2',
      method: 'bspline',
      valueColumn: 'mdur',
      color: '#14b8a6',
      lineWidth: 2,
      degree: 2,
      knots: [1.5, 3, 5, 8, 12, 18, 24],
      excludeRanks: [0, 1, 2]
    }
  },
  {
    id: 'coupon_bspline_d2',
    name: 'Coupon B-Spline D2',
    description: 'Coupon term profile with degree 2 knots',
    config: {
      id: 'coupon_bspline_d2',
      method: 'bspline',
      valueColumn: 'coupon',
      color: '#eab308',
      lineWidth: 2,
      degree: 2,
      knots: [2, 3, 5, 7, 10, 20, 30],
      excludeRanks: [0, 1, 2]
    }
  }
]

const DEFAULT_PRESET_IDS = ['ytm_bspline_d2_balanced']

const TIMESERIES_LINE_PALETTE = [
  '#38bdf8',
  '#f97316',
  '#22c55e',
  '#f43f5e',
  '#a78bfa',
  '#eab308',
  '#14b8a6',
  '#fb7185'
]

const FORMULA_LINE_PALETTE = [
  '#fbbf24',
  '#22d3ee',
  '#f472b6',
  '#34d399',
  '#c084fc',
  '#f87171'
]

const CUSIP_TOKEN_RE = /^[0-9A-Z]{9}$/
const SAVED_YTM_QUICK_SPREADS_STORAGE_KEY = 'usts-rv-ytm-quick-spreads-v1'
const YTM_QUICK_TENOR_UNIVERSE = [1, 2, 3, 5, 7, 10, 20, 30]

function createCurvePreset(
  frontTenor: number,
  backTenor: number
): TimeseriesQuickSpreadPreset {
  return {
    id: `curve_${frontTenor}s${backTenor}s`,
    name: `${frontTenor}s${backTenor}s`,
    description: `CT${backTenor} - CT${frontTenor}`,
    yaxis: 'y2',
    legs: [
      { cusip: `CT${backTenor}`, weight: 1 },
      { cusip: `CT${frontTenor}`, weight: -1 }
    ]
  }
}

function createFlyPreset(
  wingLeft: number,
  belly: number,
  wingRight: number
): TimeseriesQuickSpreadPreset {
  return {
    id: `fly_${wingLeft}s${belly}s${wingRight}s`,
    name: `${wingLeft}s${belly}s${wingRight}s`,
    description: `+CT${wingLeft} - 2*CT${belly} + CT${wingRight}`,
    yaxis: 'y2',
    legs: [
      { cusip: `CT${wingLeft}`, weight: 1 },
      { cusip: `CT${belly}`, weight: -2 },
      { cusip: `CT${wingRight}`, weight: 1 }
    ]
  }
}

function buildCurvePairs(tenors: number[]): Array<[number, number]> {
  const pairs: Array<[number, number]> = []
  for (let i = 0; i < tenors.length; i += 1) {
    for (let j = i + 1; j < tenors.length; j += 1) {
      pairs.push([tenors[i], tenors[j]])
    }
  }
  return pairs
}

function buildFlyTriplets(tenors: number[]): Array<[number, number, number]> {
  const triplets: Array<[number, number, number]> = []
  for (let i = 0; i < tenors.length; i += 1) {
    for (let j = i + 1; j < tenors.length; j += 1) {
      for (let k = j + 1; k < tenors.length; k += 1) {
        triplets.push([tenors[i], tenors[j], tenors[k]])
      }
    }
  }
  return triplets
}

const YTM_QUICK_CURVE_PAIRS = buildCurvePairs(YTM_QUICK_TENOR_UNIVERSE)
const YTM_QUICK_FLY_TRIPLETS = buildFlyTriplets(YTM_QUICK_TENOR_UNIVERSE)

const YTM_QUICK_SPREAD_PRESETS: TimeseriesQuickSpreadPreset[] = [
  ...YTM_QUICK_CURVE_PAIRS.map(([a, b]) => createCurvePreset(a, b)),
  ...YTM_QUICK_FLY_TRIPLETS.map(([a, b, c]) => createFlyPreset(a, b, c))
]

type PlotlyFigureProps = {
  data: any[]
  layout: any
  config: any
  onViewportChange?: (viewport: PlotViewport) => void
  onPointClick?: (point: UstsRvSelectedBond) => void
}

function todayIsoDate() {
  return new Date().toISOString().slice(0, 10)
}

function formatTimestamp(value: string | null | undefined) {
  if (!value) return '--'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return value
  return new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/New_York',
    year: 'numeric',
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit'
  }).format(d)
}

function toFiniteNumber(value: unknown): number | null {
  const num = Number(value)
  return Number.isFinite(num) ? num : null
}

function normalizeRange(raw: unknown): [number, number] | null {
  if (!Array.isArray(raw) || raw.length < 2) return null
  const lo = toFiniteNumber(raw[0])
  const hi = toFiniteNumber(raw[1])
  if (lo === null || hi === null) return null
  return lo <= hi ? [lo, hi] : [hi, lo]
}

function oiSortKey(oi: string) {
  const match = oi.match(/^(\d+(?:\.\d+)?)/)
  return match ? Number(match[1]) : Number.POSITIVE_INFINITY
}

function sortOiLabels(labels: string[]) {
  return labels.slice().sort((a, b) => {
    const aKey = oiSortKey(a)
    const bKey = oiSortKey(b)
    if (aKey !== bKey) return aKey - bKey
    return a.localeCompare(b)
  })
}

function buildOiColorMap(labels: string[]) {
  const out = new Map<string, string>()
  const ordered = sortOiLabels(labels)
  ordered.forEach((label, idx) => {
    out.set(label, OI_COLOR_PALETTE[idx % OI_COLOR_PALETTE.length])
  })
  return out
}

function extractViewportFromFullLayout(fullLayout: any): PlotViewport {
  const autoX = fullLayout?.xaxis?.autorange !== false
  const autoY = fullLayout?.yaxis?.autorange !== false
  const xRange = autoX ? null : normalizeRange(fullLayout?.xaxis?.range)
  const yRange = autoY ? null : normalizeRange(fullLayout?.yaxis?.range)
  return { xRange, yRange, autoX, autoY }
}

function computeSma(values: Array<number | null>, period: number) {
  if (period <= 0) return values.map(() => null)
  const out: Array<number | null> = new Array(values.length).fill(null)
  let rolling = 0
  let validCount = 0
  const queue: Array<number | null> = []

  for (let i = 0; i < values.length; i += 1) {
    const v = values[i]
    queue.push(v)
    if (typeof v === 'number' && Number.isFinite(v)) {
      rolling += v
      validCount += 1
    }

    if (queue.length > period) {
      const dropped = queue.shift()
      if (typeof dropped === 'number' && Number.isFinite(dropped)) {
        rolling -= dropped
        validCount -= 1
      }
    }

    if (queue.length === period && validCount === period) {
      out[i] = rolling / period
    }
  }

  return out
}

function computeEma(values: Array<number | null>, period: number) {
  if (period <= 0) return values.map(() => null)
  const out: Array<number | null> = new Array(values.length).fill(null)
  const alpha = 2 / (period + 1)
  let prev: number | null = null
  for (let i = 0; i < values.length; i += 1) {
    const v = values[i]
    if (typeof v !== 'number' || !Number.isFinite(v)) {
      out[i] = prev
      continue
    }
    prev = prev === null ? v : alpha * v + (1 - alpha) * prev
    out[i] = prev
  }
  return out
}

function makeClientId(prefix: string) {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
}

function axisShortLabel(axis: TimeseriesAxis) {
  return axis === 'y2' ? 'RHS' : 'LHS'
}

function axisLongLabel(axis: TimeseriesAxis) {
  return axis === 'y2' ? 'Right Axis' : 'Left Axis'
}

function sanitizeFormulaName(raw: string, fallback: string) {
  const txt = raw.trim()
  return txt || fallback
}

function normalizeFormulaWeight(raw: unknown) {
  const num = Number(raw)
  return Number.isFinite(num) ? num : 0
}

function formatFormulaWeight(weight: number) {
  const abs = Math.abs(weight)
  const magnitude = Number.isInteger(abs) ? abs.toFixed(0) : abs.toFixed(4)
  return `${weight >= 0 ? '+' : '-'}${magnitude}`
}

function formatFormulaExpression(legs: TimeseriesFormulaLeg[]) {
  if (!legs.length) return '--'
  return legs
    .map((leg, idx) => {
      const token = `${formatFormulaWeight(leg.weight)} * ${leg.cusip || '?'}`
      return idx === 0 ? token.replace(/^\+/, '') : token
    })
    .join(' ')
}

function parseCtTenorFromOi(oi: string | null | undefined): number | null {
  if (!oi) return null
  const match = String(oi).match(/(\d{1,2})/)
  if (!match) return null
  const tenor = Number(match[1])
  if (!Number.isFinite(tenor) || tenor <= 0) return null
  return Math.trunc(tenor)
}

function parseCtTenorFromToken(token: string): number | null {
  const match = String(token || '')
    .trim()
    .toUpperCase()
    .match(/^CT(\d{1,2})$/)
  if (!match) return null
  const tenor = Number(match[1])
  if (!Number.isFinite(tenor) || tenor <= 0) return null
  return Math.trunc(tenor)
}

function makeCtSelectedBond(tenorYears: number): UstsRvSelectedBond {
  return {
    cusip: `CT${tenorYears}`,
    ust_label: `Constant Maturity ${tenorYears}Y`,
    oi: `${tenorYears}-Year`,
    rank: 0,
    sourceCusip: null,
    isConstantMaturity: true
  }
}

function makeCusipSelectedBond(cusip: string): UstsRvSelectedBond {
  return {
    cusip,
    ust_label: null,
    oi: null,
    rank: null,
    sourceCusip: null,
    isConstantMaturity: false
  }
}

function isSupportedSpreadToken(token: string) {
  return parseCtTenorFromToken(token) !== null || CUSIP_TOKEN_RE.test(token)
}

function normalizeSpreadLegs(
  legs: Array<{ cusip: unknown; weight: unknown }>
): TimeseriesFormulaLeg[] {
  return legs
    .map((leg) => ({
      cusip: String(leg.cusip ?? '').trim().toUpperCase(),
      weight: normalizeFormulaWeight(leg.weight)
    }))
    .filter(
      (leg) =>
        Boolean(leg.cusip) && Number.isFinite(leg.weight) && isSupportedSpreadToken(leg.cusip)
    )
}

function normalizeSavedQuickSpreadPreset(
  candidate: unknown,
  fallbackId: string
): TimeseriesQuickSpreadPreset | null {
  if (!candidate || typeof candidate !== 'object') return null
  const raw = candidate as Partial<TimeseriesQuickSpreadPreset>
  const rawLegs = Array.isArray(raw.legs) ? raw.legs : []
  const legs = normalizeSpreadLegs(rawLegs)
  if (legs.length < 2) return null
  if (legs.every((leg) => Math.abs(leg.weight) < 1e-12)) return null
  const name = sanitizeFormulaName(String(raw.name ?? ''), '').trim()
  if (!name) return null
  const description = String(raw.description ?? '').trim() || formatFormulaExpression(legs)
  return {
    id: String(raw.id ?? '').trim() || fallbackId,
    name,
    description,
    yaxis: raw.yaxis === 'y' ? 'y' : 'y2',
    scaleBy100: typeof raw.scaleBy100 === 'boolean' ? raw.scaleBy100 : true,
    legs
  }
}

function makeUniqueQuickSpreadName(
  baseName: string,
  existing: TimeseriesQuickSpreadPreset[]
) {
  const normalized = baseName.trim() || 'Saved Spread'
  const normalizedKey = normalized.toLowerCase()
  const names = new Set(existing.map((preset) => preset.name.trim().toLowerCase()))
  if (!names.has(normalizedKey)) return normalized
  let suffix = 2
  while (names.has(`${normalized.toLowerCase()} (${suffix})`)) suffix += 1
  return `${normalized} (${suffix})`
}

function makeUniqueFormulaName(
  baseName: string,
  existing: TimeseriesFormulaConfig[]
) {
  const normalized = baseName.trim() || 'Formula'
  const names = new Set(existing.map((config) => config.name))
  if (!names.has(normalized)) return normalized
  let suffix = 2
  while (names.has(`${normalized} (${suffix})`)) suffix += 1
  return `${normalized} (${suffix})`
}

function buildFormulaSeries(
  config: TimeseriesFormulaConfig,
  seriesMap: Map<string, UstsRvTimeseriesSeries>
): TimeseriesFormulaSeries | null {
  const legs = config.legs.filter(
    (leg) => Boolean(leg.cusip) && Number.isFinite(leg.weight)
  )
  if (legs.length < 2) return null

  const legValueMaps: Array<{ leg: TimeseriesFormulaLeg; values: Map<string, number> }> = []
  const allDates = new Set<string>()
  for (const leg of legs) {
    const baseSeries = seriesMap.get(leg.cusip)
    if (!baseSeries) return null
    const values = new Map<string, number>()
    for (const point of baseSeries.points) {
      const num = Number(point.value)
      if (!Number.isFinite(num)) continue
      values.set(point.asOf, num)
      allDates.add(point.asOf)
    }
    legValueMaps.push({ leg, values })
  }

  const dates = Array.from(allDates).sort((a, b) => a.localeCompare(b))
  const scaleFactor = config.scaleBy100 ? 100 : 1
  if (!dates.length) {
    return {
      id: config.id,
      name: config.name,
      yaxis: config.yaxis,
      scaleBy100: config.scaleBy100,
      expression: formatFormulaExpression(legs),
      points: [],
      nonNullCount: 0
    }
  }

  let nonNullCount = 0
  const points = dates.map((asOf) => {
    let sum = 0
    for (const legItem of legValueMaps) {
      const v = legItem.values.get(asOf)
      if (v === undefined) {
        return { asOf, value: null }
      }
      sum += legItem.leg.weight * v
    }
    nonNullCount += 1
    return { asOf, value: sum * scaleFactor }
  })

  return {
    id: config.id,
    name: config.name,
    yaxis: config.yaxis,
    scaleBy100: config.scaleBy100,
    expression: formatFormulaExpression(legs),
    points,
    nonNullCount
  }
}

function makePlotlyMutableTargetEvent(event: any) {
  if (!event || typeof event !== 'object') return event
  let hasTargetOverride = false
  let targetOverride: any = undefined
  return new Proxy(event, {
    get(target, prop) {
      if (prop === 'target' && hasTargetOverride) return targetOverride
      const value = Reflect.get(target, prop)
      return typeof value === 'function' ? value.bind(target) : value
    },
    set(target, prop, value) {
      if (prop === 'target') {
        hasTargetOverride = true
        targetOverride = value
        return true
      }
      try {
        return Reflect.set(target, prop, value)
      } catch {
        return true
      }
    }
  })
}

function patchPlotlyHoverLayerHandlers(plotContainer: any) {
  const hoverLayerNode = plotContainer?._fullLayout?._hoverlayer?.node?.()
  if (!hoverLayerNode) return

  const patchHandler = (handlerKey: 'onmousemove' | 'onclick') => {
    const current = hoverLayerNode[handlerKey]
    if (typeof current !== 'function') return
    if (current.__ustsRvTargetMutablePatchApplied) return

    const wrapped = function patchedPlotlyHoverHandler(this: any, event: any) {
      return current.call(this, makePlotlyMutableTargetEvent(event))
    }
    wrapped.__ustsRvTargetMutablePatchApplied = true
    hoverLayerNode[handlerKey] = wrapped
  }

  patchHandler('onmousemove')
  patchHandler('onclick')
}

function PlotlyFigure({ data, layout, config, onViewportChange, onPointClick }: PlotlyFigureProps) {
  const rootRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    let disposed = false
    let plotly: any = null
    const container = rootRef.current

    const run = async () => {
      const plotlyModule = await import('plotly.js-dist-min')
      plotly = plotlyModule.default ?? plotlyModule
      if (disposed || !container) return
      await plotly.react(container, data, layout, config)
      patchPlotlyHoverLayerHandlers(container)
      if (onViewportChange) {
        onViewportChange(extractViewportFromFullLayout((container as any)._fullLayout))
      }

      const relayoutHandler = () => {
        if (!onViewportChange) return
        onViewportChange(extractViewportFromFullLayout((container as any)._fullLayout))
      }

      const clickHandler = (evt: any) => {
        if (!onPointClick) return
        const firstPoint = evt?.points?.[0]
        const customData = firstPoint?.customdata
        if (!Array.isArray(customData) || !customData.length) return
        const cusip = String(customData[0] ?? '').trim().toUpperCase()
        if (!cusip) return
        const ustLabel = customData.length > 1 ? String(customData[1] ?? '') : ''
        const oi = customData.length > 2 ? String(customData[2] ?? '') : ''
        const rankRaw = customData.length > 3 ? Number(customData[3]) : Number.NaN
        const rank = Number.isFinite(rankRaw) ? Math.trunc(rankRaw) : null
        onPointClick({
          cusip,
          ust_label: ustLabel || null,
          oi: oi || null,
          rank,
          sourceCusip: cusip,
          isConstantMaturity: false
        })
      }

      ;(container as any).on?.('plotly_relayout', relayoutHandler)
      ;(container as any).on?.('plotly_doubleclick', relayoutHandler)
      ;(container as any).on?.('plotly_click', clickHandler)

      ;(container as any).__ustsRvRelayoutHandler = relayoutHandler
      ;(container as any).__ustsRvClickHandler = clickHandler
    }

    run().catch((err) => {
      console.error('plotly render error', err)
    })

    return () => {
      disposed = true
      const relayoutHandler = (container as any)?.__ustsRvRelayoutHandler
      const clickHandler = (container as any)?.__ustsRvClickHandler
      if (container && relayoutHandler) {
        ;(container as any).removeListener?.('plotly_relayout', relayoutHandler)
        ;(container as any).removeListener?.('plotly_doubleclick', relayoutHandler)
        ;(container as any).__ustsRvRelayoutHandler = undefined
      }
      if (container && clickHandler) {
        ;(container as any).removeListener?.('plotly_click', clickHandler)
        ;(container as any).__ustsRvClickHandler = undefined
      }
      if (plotly && container) {
        try {
          plotly.purge(container)
        } catch {
          // no-op
        }
      }
    }
  }, [data, layout, config, onViewportChange, onPointClick])

  return <div ref={rootRef} className="h-[780px] w-full" />
}

export default function UstsRvDashboard() {
  const [asOf, setAsOf] = useState(todayIsoDate())
  const [minTtm, setMinTtm] = useState(1)
  const [xColumn, setXColumn] = useState<UstsRvXColumn>('ttm')
  const [valueColumn, setValueColumn] = useState<UstsRvValueColumn>('ytm')
  const [selectedPresetIds, setSelectedPresetIds] = useState<string[]>(DEFAULT_PRESET_IDS)
  const [showSplinePresets, setShowSplinePresets] = useState(false)
  const [snapshot, setSnapshot] = useState<UstsRvSnapshotResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [lastRefresh, setLastRefresh] = useState<string | null>(null)
  const [selectedBonds, setSelectedBonds] = useState<UstsRvSelectedBond[]>([])
  const [timeseries, setTimeseries] = useState<UstsRvTimeseriesResponse | null>(null)
  const [timeseriesLoading, setTimeseriesLoading] = useState(false)
  const [timeseriesError, setTimeseriesError] = useState<string | null>(null)
  const [timeseriesLookbackDays, setTimeseriesLookbackDays] = useState(365 * 5)
  const [timeseriesTechnicals, setTimeseriesTechnicals] = useState<TimeseriesTechnicals>({
    sma20: false,
    sma50: false,
    ema20: false,
    ema50: false
  })
  const [timeseriesRightAxisCusips, setTimeseriesRightAxisCusips] = useState<string[]>([])
  const [timeseriesHiddenCusips, setTimeseriesHiddenCusips] = useState<string[]>([])
  const [formulaConfigs, setFormulaConfigs] = useState<TimeseriesFormulaConfig[]>([])
  const [formulaDraftName, setFormulaDraftName] = useState('')
  const [formulaDraftAxis, setFormulaDraftAxis] = useState<TimeseriesAxis>('y2')
  const [formulaDraftScaleBy100, setFormulaDraftScaleBy100] = useState(true)
  const [formulaDraftLegs, setFormulaDraftLegs] = useState<TimeseriesFormulaLegDraft[]>([
    { id: makeClientId('formula-leg'), cusip: '', weight: 1 },
    { id: makeClientId('formula-leg'), cusip: '', weight: -1 }
  ])
  const [formulaError, setFormulaError] = useState<string | null>(null)
  const [showFormulaBuilder, setShowFormulaBuilder] = useState(true)
  const [savedQuickSpreadPresets, setSavedQuickSpreadPresets] = useState<
    TimeseriesQuickSpreadPreset[]
  >([])
  const [didLoadSavedQuickSpreadPresets, setDidLoadSavedQuickSpreadPresets] =
    useState(false)
  const [viewport, setViewport] = useState<PlotViewport>({
    xRange: null,
    yRange: null,
    autoX: true,
    autoY: true
  })

  const didInit = useRef(false)

  const handleViewportChange = useCallback((nextViewport: PlotViewport) => {
    setViewport((current) => {
      const sameXRange =
        current.xRange?.[0] === nextViewport.xRange?.[0] &&
        current.xRange?.[1] === nextViewport.xRange?.[1]
      const sameYRange =
        current.yRange?.[0] === nextViewport.yRange?.[0] &&
        current.yRange?.[1] === nextViewport.yRange?.[1]
      if (
        sameXRange &&
        sameYRange &&
        current.autoX === nextViewport.autoX &&
        current.autoY === nextViewport.autoY
      ) {
        return current
      }
      return nextViewport
    })
  }, [])

  const availablePresets = useMemo(
    () => SPLINE_PRESETS.filter((preset) => preset.config.valueColumn === valueColumn),
    [valueColumn]
  )

  const selectedPresetConfigs = useMemo(() => {
    const selected = new Set(selectedPresetIds)
    return availablePresets
      .filter((preset) => selected.has(preset.id))
      .map((preset) => preset.config)
  }, [selectedPresetIds, availablePresets])

  useEffect(() => {
    const availableIds = new Set(availablePresets.map((preset) => preset.id))
    setSelectedPresetIds((current) => {
      const filtered = current.filter((id) => availableIds.has(id))
      if (filtered.length) return filtered
      const firstAvailable = availablePresets[0]?.id
      return firstAvailable ? [firstAvailable] : []
    })
  }, [availablePresets])

  const buildRequest = useCallback((): UstsRvSnapshotRequest => {
    return {
      asOf: asOf || undefined,
      minTtm,
      xColumn,
      includeValues: [valueColumn],
      splineConfigs: selectedPresetConfigs
    }
  }, [asOf, minTtm, xColumn, valueColumn, selectedPresetConfigs])

  const fetchSnapshot = useCallback(async (requestPayload: UstsRvSnapshotRequest) => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch('/api/usts-rv/snapshot', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(requestPayload)
      })
      const data = await res.json()
      if (!res.ok) {
        throw new Error(data?.error || 'Failed to load UST RV snapshot')
      }
      setSnapshot(data as UstsRvSnapshotResponse)
      setViewport({ xRange: null, yRange: null, autoX: true, autoY: true })
      setLastRefresh(new Date().toISOString())
    } catch (err: any) {
      setError(err?.message || 'Failed to load UST RV snapshot')
    } finally {
      setLoading(false)
    }
  }, [])

  const refresh = useCallback(() => {
    void fetchSnapshot(buildRequest())
  }, [fetchSnapshot, buildRequest])

  useEffect(() => {
    if (didInit.current) return
    didInit.current = true
    refresh()
  }, [refresh])

  const toggleSplinePreset = (presetId: string) => {
    setSelectedPresetIds((current) => {
      if (current.includes(presetId)) {
        return current.filter((id) => id !== presetId)
      }
      return [...current, presetId]
    })
  }

  const resetSplinePresets = () =>
    setSelectedPresetIds(availablePresets.slice(0, 2).map((preset) => preset.id))
  const clearSplinePresets = () => setSelectedPresetIds([])

  const handleScatterPointClick = useCallback((bond: UstsRvSelectedBond) => {
    const ctTenor = bond.rank === 0 ? parseCtTenorFromOi(bond.oi) : null
    const selectedBond: UstsRvSelectedBond =
      ctTenor !== null
        ? {
            cusip: `CT${ctTenor}`,
            ust_label: `Constant Maturity ${ctTenor}Y`,
            oi: bond.oi,
            rank: 0,
            sourceCusip: bond.cusip,
            isConstantMaturity: true
          }
        : {
            ...bond,
            sourceCusip: bond.cusip,
            isConstantMaturity: false
          }

    setSelectedBonds((current) => {
      if (current.some((item) => item.cusip === selectedBond.cusip)) return current
      return [...current, selectedBond]
    })
  }, [])

  const removeSelectedBond = (cusip: string) => {
    setSelectedBonds((current) => current.filter((bond) => bond.cusip !== cusip))
  }

  const clearSelectedBonds = () => setSelectedBonds([])

  const selectedBondCusips = useMemo(
    () => selectedBonds.map((bond) => bond.cusip),
    [selectedBonds]
  )

  useEffect(() => {
    if (typeof window === 'undefined') {
      setDidLoadSavedQuickSpreadPresets(true)
      return
    }
    try {
      const stored = window.localStorage.getItem(SAVED_YTM_QUICK_SPREADS_STORAGE_KEY)
      if (!stored) {
        setSavedQuickSpreadPresets([])
        return
      }
      const parsed = JSON.parse(stored)
      const rawItems = Array.isArray(parsed) ? parsed : []
      const loaded: TimeseriesQuickSpreadPreset[] = []
      for (let idx = 0; idx < rawItems.length; idx += 1) {
        const normalized = normalizeSavedQuickSpreadPreset(rawItems[idx], `saved-${idx + 1}`)
        if (!normalized) continue
        const safeId = normalized.id.startsWith('saved-')
          ? normalized.id
          : `saved-${idx + 1}`
        const safeName = makeUniqueQuickSpreadName(normalized.name, [
          ...YTM_QUICK_SPREAD_PRESETS,
          ...loaded
        ])
        loaded.push({ ...normalized, id: safeId, name: safeName })
      }
      setSavedQuickSpreadPresets(loaded)
    } catch {
      setSavedQuickSpreadPresets([])
    } finally {
      setDidLoadSavedQuickSpreadPresets(true)
    }
  }, [])

  useEffect(() => {
    if (!didLoadSavedQuickSpreadPresets || typeof window === 'undefined') return
    try {
      window.localStorage.setItem(
        SAVED_YTM_QUICK_SPREADS_STORAGE_KEY,
        JSON.stringify(savedQuickSpreadPresets)
      )
    } catch {
      // no-op
    }
  }, [savedQuickSpreadPresets, didLoadSavedQuickSpreadPresets])

  const allQuickSpreadPresets = useMemo(
    () => [...YTM_QUICK_SPREAD_PRESETS, ...savedQuickSpreadPresets],
    [savedQuickSpreadPresets]
  )

  const savedQuickSpreadIds = useMemo(
    () => new Set(savedQuickSpreadPresets.map((preset) => preset.id)),
    [savedQuickSpreadPresets]
  )

  useEffect(() => {
    const selectedSet = new Set(selectedBondCusips)
    const firstCusip = selectedBondCusips[0] ?? ''

    setTimeseriesRightAxisCusips((current) =>
      current.filter((cusip) => selectedSet.has(cusip))
    )
    setTimeseriesHiddenCusips((current) =>
      current.filter((cusip) => selectedSet.has(cusip))
    )

    setFormulaConfigs((current) =>
      current
        .map((config) => ({
          ...config,
          legs: config.legs.filter((leg) => selectedSet.has(leg.cusip))
        }))
        .filter((config) => config.legs.length >= 2)
    )

    setFormulaDraftLegs((current) =>
      current.map((leg) => {
        if (!leg.cusip || selectedSet.has(leg.cusip)) return leg
        return { ...leg, cusip: firstCusip }
      })
    )
  }, [selectedBondCusips])

  const toggleTimeseriesTechnical = (key: keyof TimeseriesTechnicals) => {
    setTimeseriesTechnicals((current) => ({ ...current, [key]: !current[key] }))
  }

  const toggleSeriesAxis = (cusip: string) => {
    setTimeseriesRightAxisCusips((current) => {
      if (current.includes(cusip)) {
        return current.filter((item) => item !== cusip)
      }
      return [...current, cusip]
    })
  }

  const toggleSeriesVisibility = (cusip: string) => {
    setTimeseriesHiddenCusips((current) => {
      if (current.includes(cusip)) {
        return current.filter((item) => item !== cusip)
      }
      return [...current, cusip]
    })
  }

  const updateFormulaDraftLeg = (
    legId: string,
    update: Partial<Pick<TimeseriesFormulaLegDraft, 'cusip' | 'weight'>>
  ) => {
    setFormulaDraftLegs((current) =>
      current.map((leg) => (leg.id === legId ? { ...leg, ...update } : leg))
    )
  }

  const addFormulaDraftLeg = () => {
    setFormulaDraftLegs((current) => [
      ...current,
      {
        id: makeClientId('formula-leg'),
        cusip: selectedBondCusips[0] ?? '',
        weight: 0
      }
    ])
  }

  const removeFormulaDraftLeg = (legId: string) => {
    setFormulaDraftLegs((current) => {
      if (current.length <= 2) return current
      return current.filter((leg) => leg.id !== legId)
    })
  }

  const resetFormulaDraft = () => {
    setFormulaDraftName('')
    setFormulaDraftAxis('y2')
    setFormulaDraftScaleBy100(true)
    setFormulaDraftLegs([
      { id: makeClientId('formula-leg'), cusip: selectedBondCusips[0] ?? '', weight: 1 },
      { id: makeClientId('formula-leg'), cusip: selectedBondCusips[1] ?? '', weight: -1 }
    ])
    setFormulaError(null)
  }

  const loadCurveTemplate = () => {
    if (selectedBondCusips.length < 2) {
      setFormulaError('Curve template needs at least 2 selected bonds.')
      return
    }
    const [front, back] = selectedBondCusips
    setFormulaDraftName((current) => current || `Curve ${front}-${back}`)
    setFormulaDraftLegs([
      { id: makeClientId('formula-leg'), cusip: front, weight: 1 },
      { id: makeClientId('formula-leg'), cusip: back, weight: -1 }
    ])
    setFormulaError(null)
  }

  const loadFlyTemplate = () => {
    if (selectedBondCusips.length < 3) {
      setFormulaError('Fly template needs at least 3 selected bonds.')
      return
    }
    const [leftWing, belly, rightWing] = selectedBondCusips
    setFormulaDraftName((current) => current || `Fly ${leftWing}-${belly}-${rightWing}`)
    setFormulaDraftLegs([
      { id: makeClientId('formula-leg'), cusip: leftWing, weight: 1 },
      { id: makeClientId('formula-leg'), cusip: belly, weight: -2 },
      { id: makeClientId('formula-leg'), cusip: rightWing, weight: 1 }
    ])
    setFormulaError(null)
  }

  const addFormulaSeries = () => {
    const selectedSet = new Set(selectedBondCusips)
    const normalizedLegs: TimeseriesFormulaLeg[] = normalizeSpreadLegs(
      formulaDraftLegs.map((leg) => ({ cusip: leg.cusip, weight: leg.weight }))
    )
      .filter((leg) => leg.cusip && selectedSet.has(leg.cusip))

    if (normalizedLegs.length < 2) {
      setFormulaError('At least two valid formula legs are required.')
      return
    }
    if (normalizedLegs.every((leg) => Math.abs(leg.weight) < 1e-12)) {
      setFormulaError('Formula cannot have all-zero weights.')
      return
    }

    const fallback = `Formula ${formulaConfigs.length + 1}`
    setFormulaConfigs((current) => [
      ...current,
      {
        id: makeClientId('formula'),
        name: sanitizeFormulaName(formulaDraftName, fallback),
        yaxis: formulaDraftAxis,
        scaleBy100: formulaDraftScaleBy100,
        legs: normalizedLegs
      }
    ])
    setFormulaError(null)
  }

  const saveFormulaDraftAsQuickSpread = () => {
    const normalizedLegs = normalizeSpreadLegs(
      formulaDraftLegs.map((leg) => ({ cusip: leg.cusip, weight: leg.weight }))
    )
    if (normalizedLegs.length < 2) {
      setFormulaError('Save Spread requires at least two valid CT/CUSIP legs.')
      return
    }
    if (normalizedLegs.every((leg) => Math.abs(leg.weight) < 1e-12)) {
      setFormulaError('Save Spread rejected all-zero weights.')
      return
    }

    setSavedQuickSpreadPresets((current) => {
      const fallback = `Saved Spread ${current.length + 1}`
      const requestedName = sanitizeFormulaName(formulaDraftName, fallback)
      const name = makeUniqueQuickSpreadName(requestedName, [
        ...YTM_QUICK_SPREAD_PRESETS,
        ...current
      ])
      return [
        ...current,
        {
          id: makeClientId('saved-quick-spread'),
          name,
          description: formatFormulaExpression(normalizedLegs),
          yaxis: formulaDraftAxis,
          scaleBy100: formulaDraftScaleBy100,
          legs: normalizedLegs
        }
      ]
    })
    setFormulaError(null)
  }

  const quickAddSpreadPreset = (preset: TimeseriesQuickSpreadPreset) => {
    const normalizedLegs = normalizeSpreadLegs(preset.legs)

    if (normalizedLegs.length < 2) {
      setFormulaError(`Quick spread '${preset.name}' is not configured with valid legs.`)
      return
    }

    setSelectedBonds((current) => {
      const byCusip = new Map(current.map((bond) => [bond.cusip, bond]))
      for (const leg of normalizedLegs) {
        if (byCusip.has(leg.cusip)) continue
        const ctTenor = parseCtTenorFromToken(leg.cusip)
        if (ctTenor !== null) {
          byCusip.set(leg.cusip, makeCtSelectedBond(ctTenor))
          continue
        }
        if (CUSIP_TOKEN_RE.test(leg.cusip)) {
          byCusip.set(leg.cusip, makeCusipSelectedBond(leg.cusip))
        }
      }
      return Array.from(byCusip.values())
    })

    const quickLegCusips = normalizedLegs.map((leg) => leg.cusip)
    const quickLegSet = new Set(quickLegCusips)
    setTimeseriesHiddenCusips((current) => {
      const hidden = new Set(current)
      for (const cusip of quickLegCusips) hidden.add(cusip)
      return Array.from(hidden)
    })
    setTimeseriesRightAxisCusips((current) =>
      current.filter((cusip) => !quickLegSet.has(cusip))
    )

    setFormulaConfigs((current) => [
      ...current,
      {
        id: makeClientId(`formula-${preset.id}`),
        name: makeUniqueFormulaName(preset.name, current),
        yaxis: 'y2',
        scaleBy100:
          typeof preset.scaleBy100 === 'boolean'
            ? preset.scaleBy100
            : formulaDraftScaleBy100,
        legs: normalizedLegs
      }
    ])
    setFormulaError(null)
  }

  const removeFormulaSeries = (formulaId: string) => {
    setFormulaConfigs((current) => current.filter((formula) => formula.id !== formulaId))
  }

  const formulaDraftExpression = useMemo(
    () =>
      formatFormulaExpression(
        formulaDraftLegs
          .map((leg) => ({
            cusip: String(leg.cusip || '').trim().toUpperCase(),
            weight: normalizeFormulaWeight(leg.weight)
          }))
          .filter((leg) => Boolean(leg.cusip))
      ),
    [formulaDraftLegs]
  )

  const fetchTimeseries = useCallback(
    async (payload: UstsRvTimeseriesRequest) => {
      setTimeseriesLoading(true)
      setTimeseriesError(null)
      try {
        const res = await fetch('/api/usts-rv/timeseries', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        })
        const data = await res.json()
        if (!res.ok) {
          throw new Error(data?.error || 'Failed to load UST RV timeseries')
        }
        setTimeseries(data as UstsRvTimeseriesResponse)
      } catch (err: any) {
        setTimeseriesError(err?.message || 'Failed to load UST RV timeseries')
      } finally {
        setTimeseriesLoading(false)
      }
    },
    []
  )

  useEffect(() => {
    if (!selectedBonds.length) {
      setTimeseries(null)
      setTimeseriesError(null)
      return
    }

    void fetchTimeseries({
      asOf: snapshot?.asOf || asOf,
      curveName: snapshot?.curveName,
      valueColumn,
      cusips: selectedBonds.map((bond) => bond.cusip),
      lookbackDays: timeseriesLookbackDays
    })
  }, [
    selectedBonds,
    valueColumn,
    snapshot?.asOf,
    snapshot?.curveName,
    asOf,
    timeseriesLookbackDays,
    fetchTimeseries
  ])

  const timeseriesFormulaSeries = useMemo(() => {
    if (!timeseries || !formulaConfigs.length) return []
    const seriesMap = new Map<string, UstsRvTimeseriesSeries>()
    for (const series of timeseries.series ?? []) {
      seriesMap.set(series.cusip, series)
    }
    return formulaConfigs
      .map((config) => buildFormulaSeries(config, seriesMap))
      .filter((series): series is TimeseriesFormulaSeries => Boolean(series))
  }, [timeseries, formulaConfigs])

  const formulaWarnings = useMemo(() => {
    if (!formulaConfigs.length) return []
    const builtById = new Map(timeseriesFormulaSeries.map((series) => [series.id, series]))
    const warnings: string[] = []
    for (const config of formulaConfigs) {
      const built = builtById.get(config.id)
      if (!built) {
        warnings.push(
          `Formula '${config.name}' was skipped because one or more source series is unavailable.`
        )
      } else if (built.nonNullCount === 0) {
        warnings.push(
          `Formula '${config.name}' has no overlapping dates across all selected legs.`
        )
      }
    }
    return warnings
  }, [formulaConfigs, timeseriesFormulaSeries])

  const traces = useMemo(() => {
    if (!snapshot) return []

    const points = snapshot.points ?? []
    const nextTraces: any[] = []
    const oiLabels = Array.from(
      new Set(points.map((point) => point.oi ?? 'Unknown'))
    )
    const oiColorMap = buildOiColorMap(oiLabels)
    const legendShown = new Set<string>()

    const symbol = VALUE_SYMBOLS[valueColumn] ?? 'circle'
    const filteredByValue = points.filter((point) => {
      const x = point[xColumn]
      const y = point[valueColumn]
      return (
        typeof x === 'number' &&
        Number.isFinite(x) &&
        typeof y === 'number' &&
        Number.isFinite(y)
      )
    })
    if (filteredByValue.length) {
      const pointsByOi = new Map<string, typeof filteredByValue>()
      for (const point of filteredByValue) {
        const oiLabel = point.oi ?? 'Unknown'
        const bucket = pointsByOi.get(oiLabel)
        if (bucket) bucket.push(point)
        else pointsByOi.set(oiLabel, [point])
      }

      for (const oiLabel of sortOiLabels(Array.from(pointsByOi.keys()))) {
        const oiPoints = pointsByOi.get(oiLabel) ?? []
        if (!oiPoints.length) continue
        const oiColor = oiColorMap.get(oiLabel) ?? '#38bdf8'
        const showLegend = !legendShown.has(oiLabel)
        if (showLegend) legendShown.add(oiLabel)

        nextTraces.push({
          type: 'scattergl',
          mode: 'markers',
          name: oiLabel,
          legendgroup: oiLabel,
          showlegend: showLegend,
          x: oiPoints.map((point) => point[xColumn]),
          y: oiPoints.map((point) => point[valueColumn]),
          customdata: oiPoints.map((point) => [
            point.cusip,
            point.ust_label ?? '--',
            oiLabel,
            point.rank ?? '--',
            point.ttm ?? '--',
            point.mdur ?? '--',
            point.market_timestamp ?? '--',
            valueColumn.toUpperCase()
          ]),
          marker: {
            color: oiColor,
            symbol,
            size: 8,
            opacity: 0.84,
            line: {
              color: '#0f172a',
              width: 1
            }
          },
          hovertemplate:
            'CUSIP %{customdata[0]}<br>' +
            'Label %{customdata[1]}<br>' +
            'OI %{customdata[2]}<br>' +
            'Rank %{customdata[3]}<br>' +
            'TTM %{customdata[4]}<br>' +
            'MDur %{customdata[5]}<br>' +
            '%{customdata[7]} %{y:.4f}<br>' +
            'Market TS %{customdata[6]}<extra></extra>'
        })

        const otrPoints = oiPoints.filter((point) => point.rank === 0)
        if (otrPoints.length) {
          nextTraces.push({
            type: 'scattergl',
            mode: 'markers',
            name: `OTR ${oiLabel}`,
            legendgroup: oiLabel,
            showlegend: false,
            x: otrPoints.map((point) => point[xColumn]),
            y: otrPoints.map((point) => point[valueColumn]),
            customdata: otrPoints.map((point) => [
              point.cusip,
              point.ust_label ?? '--',
              oiLabel,
              point.rank ?? '--',
              point.ttm ?? '--',
              point.mdur ?? '--',
              valueColumn.toUpperCase()
            ]),
            marker: {
              color: oiColor,
              symbol,
              size: 14,
              opacity: 1,
              line: {
                color: '#f8fafc',
                width: 3
              }
            },
            hovertemplate:
              'ON-THE-RUN<br>' +
              'CUSIP %{customdata[0]}<br>' +
              'Label %{customdata[1]}<br>' +
              'OI %{customdata[2]}<br>' +
              'Rank %{customdata[3]}<br>' +
              'TTM %{customdata[4]}<br>' +
              'MDur %{customdata[5]}<br>' +
              '%{customdata[6]} %{y:.4f}<extra></extra>'
          })
        }
      }
    }

    for (const spline of snapshot.splineSeries ?? []) {
      if (spline.error || !spline.x?.length || !spline.y?.length) continue
      nextTraces.push({
        type: 'scatter',
        mode: 'lines',
        name: `Spline: ${spline.name}`,
        x: spline.x,
        y: spline.y,
        line: {
          color: spline.color || '#ef4444',
          width: spline.lineWidth || 2,
          dash: spline.method === 'loess' ? 'solid' : 'dot'
        },
        hovertemplate:
          `${spline.name}<br>x %{x:.3f}<br>y %{y:.4f}<extra></extra>`
      })
    }

    return nextTraces
  }, [snapshot, valueColumn, xColumn])

  const layout = useMemo(
    () => ({
      template: 'plotly_dark',
      paper_bgcolor: 'rgba(2, 6, 23, 0)',
      plot_bgcolor: 'rgba(2, 6, 23, 0.65)',
      autosize: true,
      margin: { t: 64, r: 24, b: 56, l: 72 },
      title: `UST RV Snapshot: ${snapshot?.asOf ?? asOf}`,
      hovermode: 'closest',
      legend: {
        orientation: 'h',
        x: 0,
        y: 1.1,
        bgcolor: 'rgba(15, 23, 42, 0.65)',
        title: { text: 'OI' }
      },
      xaxis: {
        title: xColumn === 'ttm' ? 'Time To Maturity (Years)' : 'Modified Duration',
        showspikes: true,
        spikesnap: 'cursor',
        spikemode: 'across',
        spikecolor: '#f8fafc',
        spikethickness: 0.55,
        gridcolor: 'rgba(148, 163, 184, 0.15)'
      },
      yaxis: {
        title: 'Value',
        showspikes: true,
        spikesnap: 'cursor',
        spikecolor: '#f8fafc',
        spikethickness: 0.55,
        gridcolor: 'rgba(148, 163, 184, 0.15)'
      },
      uirevision: 'usts-rv'
    }),
    [snapshot?.asOf, asOf, xColumn]
  )

  const config = useMemo(
    () => ({
      responsive: true,
      displaylogo: false,
      modeBarButtonsToAdd: [
        'drawline',
        'drawopenpath',
        'drawclosedpath',
        'drawcircle',
        'drawrect',
        'eraseshape'
      ]
    }),
    []
  )

  const splineIssues = useMemo(
    () => (snapshot?.splineSeries ?? []).filter((series) => Boolean(series.error)),
    [snapshot?.splineSeries]
  )

  const timeseriesTraces = useMemo(() => {
    if (!timeseries) return []

    const out: any[] = []
    const hiddenCusips = new Set(timeseriesHiddenCusips)
    const addTechnicals = ({
      x,
      values,
      traceName,
      color,
      yaxis
    }: {
      x: string[]
      values: Array<number | null>
      traceName: string
      color: string
      yaxis: TimeseriesAxis
    }) => {
      if (timeseriesTechnicals.sma20) {
        out.push({
          type: 'scatter',
          mode: 'lines',
          name: `${traceName} SMA20`,
          x,
          y: computeSma(values, 20),
          yaxis,
          line: { color, width: 1.35, dash: 'dot' },
          hovertemplate: `${traceName} SMA20 %{y:.4f}<br>Date %{x}<extra></extra>`
        })
      }
      if (timeseriesTechnicals.sma50) {
        out.push({
          type: 'scatter',
          mode: 'lines',
          name: `${traceName} SMA50`,
          x,
          y: computeSma(values, 50),
          yaxis,
          line: { color, width: 1.35, dash: 'dash' },
          hovertemplate: `${traceName} SMA50 %{y:.4f}<br>Date %{x}<extra></extra>`
        })
      }
      if (timeseriesTechnicals.ema20) {
        out.push({
          type: 'scatter',
          mode: 'lines',
          name: `${traceName} EMA20`,
          x,
          y: computeEma(values, 20),
          yaxis,
          line: { color, width: 1.25, dash: 'longdash' },
          hovertemplate: `${traceName} EMA20 %{y:.4f}<br>Date %{x}<extra></extra>`
        })
      }
      if (timeseriesTechnicals.ema50) {
        out.push({
          type: 'scatter',
          mode: 'lines',
          name: `${traceName} EMA50`,
          x,
          y: computeEma(values, 50),
          yaxis,
          line: { color, width: 1.25, dash: 'longdashdot' },
          hovertemplate: `${traceName} EMA50 %{y:.4f}<br>Date %{x}<extra></extra>`
        })
      }
    }

    for (let idx = 0; idx < (timeseries.series ?? []).length; idx += 1) {
      const series = timeseries.series[idx]
      if (hiddenCusips.has(series.cusip)) continue
      const baseColor = TIMESERIES_LINE_PALETTE[idx % TIMESERIES_LINE_PALETTE.length]
      const yaxis: TimeseriesAxis = timeseriesRightAxisCusips.includes(series.cusip)
        ? 'y2'
        : 'y'
      const x = series.points.map((point) => point.asOf)
      const y = series.points.map((point) => point.value)
      const baseName = `${series.cusip}${series.ust_label ? ` (${series.ust_label})` : ''}`

      out.push({
        type: 'scatter',
        mode: 'lines+markers',
        name: baseName,
        x,
        y,
        yaxis,
        line: {
          color: baseColor,
          width: 2.2
        },
        marker: {
          size: 4,
          color: baseColor
        },
        hovertemplate:
          `CUSIP ${series.cusip}<br>` +
          `Axis ${axisShortLabel(yaxis)}<br>` +
          `${valueColumn.toUpperCase()} %{y:.4f}<br>` +
          'Date %{x}<extra></extra>'
      })

      if (!series.points.length) continue

      const values = series.points.map((point) =>
        typeof point.value === 'number' && Number.isFinite(point.value)
          ? point.value
          : null
      )
      addTechnicals({
        x,
        values,
        traceName: series.cusip,
        color: baseColor,
        yaxis
      })
    }

    for (let idx = 0; idx < timeseriesFormulaSeries.length; idx += 1) {
      const formula = timeseriesFormulaSeries[idx]
      const color = FORMULA_LINE_PALETTE[idx % FORMULA_LINE_PALETTE.length]
      const x = formula.points.map((point) => point.asOf)
      const y = formula.points.map((point) => point.value)
      const values = formula.points.map((point) =>
        typeof point.value === 'number' && Number.isFinite(point.value)
          ? point.value
          : null
      )

      out.push({
        type: 'scatter',
        mode: 'lines+markers',
        name: `Formula: ${formula.name}`,
        x,
        y,
        yaxis: formula.yaxis,
        line: { color, width: 2.4 },
        marker: { color, size: 3 },
        hovertemplate:
          `${formula.name}<br>` +
          `Expr ${formula.expression}<br>` +
          `${formula.scaleBy100 ? 'Scale x100<br>' : ''}` +
          `Axis ${axisShortLabel(formula.yaxis)}<br>` +
          `${valueColumn.toUpperCase()} %{y:.4f}<br>` +
          'Date %{x}<extra></extra>'
      })

      addTechnicals({
        x,
        values,
        traceName: `${formula.name}`,
        color,
        yaxis: formula.yaxis
      })
    }

    return out
  }, [
    timeseries,
    timeseriesTechnicals,
    valueColumn,
    timeseriesRightAxisCusips,
    timeseriesHiddenCusips,
    timeseriesFormulaSeries
  ])

  const hasTimeseriesSecondaryAxis = useMemo(
    () => timeseriesTraces.some((trace) => trace?.yaxis === 'y2'),
    [timeseriesTraces]
  )

  const timeseriesLayout = useMemo(
    () => ({
      template: 'plotly_dark',
      paper_bgcolor: 'rgba(2, 6, 23, 0)',
      plot_bgcolor: 'rgba(2, 6, 23, 0.65)',
      autosize: true,
      margin: { t: 52, r: 24, b: 54, l: 72 },
      title: `${valueColumn.toUpperCase()} Bond Timeseries`,
      hovermode: 'x unified',
      legend: {
        orientation: 'h',
        x: 0,
        y: 1.15,
        bgcolor: 'rgba(15, 23, 42, 0.65)'
      },
      xaxis: {
        title: 'As Of Date',
        type: 'date',
        showspikes: true,
        spikesnap: 'cursor',
        spikemode: 'across',
        spikecolor: '#f8fafc',
        spikethickness: 0.55,
        gridcolor: 'rgba(148, 163, 184, 0.15)'
      },
      yaxis: {
        title: hasTimeseriesSecondaryAxis
          ? `${valueColumn.toUpperCase()} (LHS)`
          : valueColumn.toUpperCase(),
        showspikes: true,
        spikesnap: 'cursor',
        spikecolor: '#f8fafc',
        spikethickness: 0.55,
        gridcolor: 'rgba(148, 163, 184, 0.15)'
      },
      ...(hasTimeseriesSecondaryAxis
        ? {
            yaxis2: {
              title: `${valueColumn.toUpperCase()} (RHS)`,
              overlaying: 'y',
              side: 'right',
              showgrid: false,
              zeroline: false,
              showspikes: true,
              spikesnap: 'cursor',
              spikecolor: '#f8fafc',
              spikethickness: 0.55
            }
          }
        : {}),
      uirevision: `usts-rv-timeseries-${valueColumn}-${hasTimeseriesSecondaryAxis ? 'dual' : 'single'}`
    }),
    [valueColumn, hasTimeseriesSecondaryAxis]
  )

  const timeseriesConfig = useMemo(
    () => ({
      responsive: true,
      displaylogo: false,
      editable: true,
      modeBarButtonsToAdd: [
        'drawline',
        'drawopenpath',
        'drawclosedpath',
        'drawcircle',
        'drawrect',
        'eraseshape'
      ]
    }),
    []
  )

  const tableRows = useMemo(() => {
    if (!snapshot) return []
    const xRange = viewport.xRange
    const yRange = viewport.yRange

    return snapshot.points
      .filter((row) => {
        const xVal = row[xColumn]
        if (typeof xVal !== 'number' || !Number.isFinite(xVal)) return false
        if (xRange && (xVal < xRange[0] || xVal > xRange[1])) return false

        const yVal = row[valueColumn]
        if (typeof yVal !== 'number' || !Number.isFinite(yVal)) return false
        if (!yRange) return true
        return yVal >= yRange[0] && yVal <= yRange[1]
      })
      .slice()
      .sort((a, b) => {
        const ax = (a[xColumn] as number) ?? 0
        const bx = (b[xColumn] as number) ?? 0
        if (ax !== bx) return ax - bx
        return (a.oi ?? '').localeCompare(b.oi ?? '')
      })
  }, [snapshot, viewport, xColumn, valueColumn])

  const warnings = snapshot?.meta?.warnings ?? []
  const timeseriesWarnings = [...(timeseries?.meta?.warnings ?? []), ...formulaWarnings]

  return (
    <div className="space-y-6">
      <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-6 shadow-xl">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight text-white">
              UST Relative Value Explorer
            </h1>
            <p className="text-sm text-slate-400">
              Database-backed UST RV scatter with selectable pre-built spline sets.
            </p>
          </div>
          <div className="text-xs text-slate-400">
            <div>As Of: {snapshot?.asOf ?? '--'}</div>
            <div>Points: {snapshot?.meta?.pointCount ?? '--'}</div>
            <div>Visible In Plot: {tableRows.length}</div>
            <div>Last Refresh: {formatTimestamp(lastRefresh)}</div>
          </div>
        </div>

        <div className="mt-6 grid gap-4 lg:grid-cols-4">
          <label className="text-xs text-slate-400">
            As Of Date
            <input
              type="date"
              value={asOf}
              onChange={(e) => setAsOf(e.target.value)}
              className="mt-2 w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-200"
            />
          </label>
          <label className="text-xs text-slate-400">
            X Axis
            <select
              value={xColumn}
              onChange={(e) => setXColumn(e.target.value as UstsRvXColumn)}
              className="mt-2 w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-200"
            >
              {X_OPTIONS.map((opt) => (
                <option key={opt.key} value={opt.key}>
                  {opt.label}
                </option>
              ))}
            </select>
          </label>
          <label className="text-xs text-slate-400">
            Min TTM
            <input
              type="number"
              step="0.25"
              value={minTtm}
              onChange={(e) => setMinTtm(Number(e.target.value))}
              className="mt-2 w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-200"
            />
          </label>
          <div className="flex items-end">
            <button
              onClick={refresh}
              disabled={loading}
              className="w-full rounded-md bg-amber-400 px-4 py-2 text-sm font-semibold text-slate-900 disabled:opacity-60"
            >
              {loading ? 'Loading...' : 'Refresh Plot'}
            </button>
          </div>
        </div>

        <div className="mt-5">
          <div className="text-xs uppercase tracking-wide text-slate-400">
            Value Series
          </div>
          <div className="mt-2 flex flex-wrap gap-4">
            {VALUE_OPTIONS.map((opt) => (
              <label key={opt.key} className="flex items-center gap-2 text-sm text-slate-200">
                <input
                  type="radio"
                  name="ust-rv-value-series"
                  checked={valueColumn === opt.key}
                  onChange={() => setValueColumn(opt.key)}
                />
                {opt.label}
              </label>
            ))}
          </div>
        </div>

        <div className="mt-6 rounded-xl border border-slate-800 bg-slate-950/70 p-4">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-slate-200">Pre-Built Spline Presets</h2>
            <div className="flex items-center gap-3">
              <div className="text-xs text-slate-400">
                {selectedPresetConfigs.length} selected / {availablePresets.length} available
              </div>
              <button
                onClick={() => setShowSplinePresets((current) => !current)}
                className="rounded-md border border-slate-600 px-2 py-1 text-xs text-slate-200 hover:border-slate-400"
              >
                {showSplinePresets ? 'Collapse' : 'Expand'}
              </button>
            </div>
          </div>
          {showSplinePresets && (
            <>
              <p className="mt-2 text-xs text-slate-400">
                Presets are fixed recipes (method/degree/knots/LOESS params) sourced from
                the DB snapshot only. Shown presets match the selected Value Series.
              </p>
              <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                {availablePresets.map((preset) => {
                  const isSelected = selectedPresetIds.includes(preset.id)
                  const cfg = preset.config
                  const methodDetails =
                    cfg.method === 'bspline'
                      ? `B-Spline d=${cfg.degree ?? 2}${
                          cfg.knots?.length ? ` | knots ${cfg.knots.join(', ')}` : ''
                        }`
                      : `LOESS frac=${cfg.frac ?? 0.25}, it=${cfg.it ?? 50}`

                  return (
                    <label
                      key={preset.id}
                      className={`cursor-pointer rounded-lg border p-3 transition ${
                        isSelected
                          ? 'border-amber-500/70 bg-amber-900/10'
                          : 'border-slate-800 bg-slate-900/70 hover:border-slate-600'
                      }`}
                    >
                      <div className="flex items-start gap-3">
                        <input
                          type="checkbox"
                          checked={isSelected}
                          onChange={() => toggleSplinePreset(preset.id)}
                          className="mt-0.5"
                        />
                        <div className="min-w-0">
                          <div className="flex flex-wrap items-center gap-2">
                            <div className="text-sm font-medium text-slate-100">{preset.name}</div>
                            <span className="rounded bg-slate-800 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-slate-300">
                              {cfg.valueColumn.replace('_', ' ')}
                            </span>
                          </div>
                          <div className="mt-1 text-xs text-slate-400">{preset.description}</div>
                          <div className="mt-1 text-[11px] text-slate-500">{methodDetails}</div>
                        </div>
                      </div>
                    </label>
                  )
                })}
              </div>
              <div className="mt-4 flex flex-wrap gap-2">
                <button
                  onClick={resetSplinePresets}
                  className="rounded-md border border-slate-600 px-3 py-1 text-xs text-slate-200 hover:border-slate-400"
                >
                  Reset Defaults
                </button>
                <button
                  onClick={clearSplinePresets}
                  className="rounded-md border border-slate-700 px-3 py-1 text-xs text-slate-300 hover:border-slate-500"
                >
                  Clear All
                </button>
              </div>
            </>
          )}
        </div>

        {!!warnings.length && (
          <div className="mt-4 rounded-md border border-amber-800 bg-amber-950/40 p-3 text-xs text-amber-200">
            {warnings.map((warn) => (
              <div key={warn}>{warn}</div>
            ))}
          </div>
        )}

        {!!splineIssues.length && (
          <div className="mt-3 rounded-md border border-rose-800 bg-rose-950/40 p-3 text-xs text-rose-200">
            {splineIssues.map((issue) => (
              <div key={issue.id}>
                {issue.name}: {issue.error}
              </div>
            ))}
          </div>
        )}

        {error && (
          <div className="mt-3 rounded-md border border-rose-800 bg-rose-950/40 p-3 text-xs text-rose-200">
            {error}
          </div>
        )}
      </div>

      <div className="rounded-2xl border border-slate-800 bg-slate-950/60 p-4">
        {!loading && traces.length === 0 && (
          <div className="p-4 text-sm text-slate-400">
            No data points for the selected values/x-axis.
          </div>
        )}
        {loading ? (
          <div className="p-4 text-sm text-slate-400">Loading chart...</div>
        ) : (
          <PlotlyFigure
            data={traces}
            layout={layout}
            config={config}
            onViewportChange={handleViewportChange}
            onPointClick={handleScatterPointClick}
          />
        )}
      </div>

      <div className="rounded-2xl border border-slate-800 bg-slate-950/60 p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold text-slate-200">
              {valueColumn.toUpperCase()} Timeseries (Click Bonds In Scatter To Add)
            </h2>
            <p className="mt-1 text-xs text-slate-500">
              Supports multi-series overlays, per-series left/right axis assignment, and
              weighted formula spreads (curves/flies).
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <label className="text-xs text-slate-400">
              Lookback Days
              <input
                type="number"
                min={30}
                step={30}
                value={timeseriesLookbackDays}
                onChange={(e) => setTimeseriesLookbackDays(Number(e.target.value))}
                className="ml-2 w-24 rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-200"
              />
            </label>
            <button
              onClick={clearSelectedBonds}
              className="rounded-md border border-slate-600 px-3 py-1 text-xs text-slate-200 hover:border-slate-400"
            >
              Clear Bonds
            </button>
          </div>
        </div>

        <div className="mt-3 flex flex-wrap gap-2">
          {selectedBonds.map((bond) => (
            <div
              key={bond.cusip}
              className="inline-flex items-center gap-2 rounded border border-slate-700 bg-slate-900/70 px-2 py-1 text-xs text-slate-200"
            >
              <span>{bond.cusip}</span>
              {bond.isConstantMaturity && (
                <span className="rounded bg-cyan-900/40 px-1 py-0.5 text-[10px] text-cyan-200">
                  CT
                </span>
              )}
              {bond.ust_label && <span className="text-slate-400">{bond.ust_label}</span>}
              {bond.isConstantMaturity && bond.sourceCusip && (
                <span className="text-[10px] text-slate-500">from {bond.sourceCusip}</span>
              )}
              <button
                onClick={() => toggleSeriesVisibility(bond.cusip)}
                className={`rounded border px-1 text-[10px] ${
                  timeseriesHiddenCusips.includes(bond.cusip)
                    ? 'border-amber-500/70 text-amber-300'
                    : 'border-slate-600 text-slate-300'
                }`}
              >
                {timeseriesHiddenCusips.includes(bond.cusip) ? 'OFF' : 'ON'}
              </button>
              <button
                onClick={() => toggleSeriesAxis(bond.cusip)}
                className={`rounded border px-1 text-[10px] ${
                  timeseriesRightAxisCusips.includes(bond.cusip)
                    ? 'border-cyan-500/70 text-cyan-300'
                    : 'border-slate-600 text-slate-300'
                }`}
              >
                {timeseriesRightAxisCusips.includes(bond.cusip) ? 'RHS' : 'LHS'}
              </button>
              <button
                onClick={() => removeSelectedBond(bond.cusip)}
                className="rounded border border-slate-600 px-1 text-[10px] text-slate-300 hover:border-slate-400"
              >
                x
              </button>
            </div>
          ))}
          {selectedBonds.length === 0 && (
            <div className="text-xs text-slate-500">No bonds selected yet.</div>
          )}
        </div>

        <div className="mt-4 rounded-lg border border-slate-800 bg-slate-900/65 p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="text-xs font-semibold uppercase tracking-wide text-slate-300">
              Custom Formula Builder
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <button
                onClick={() => setShowFormulaBuilder((current) => !current)}
                className="rounded border border-slate-600 px-2 py-1 text-[11px] text-slate-200 hover:border-slate-400"
              >
                {showFormulaBuilder ? 'Collapse' : 'Expand'}
              </button>
              <button
                onClick={loadCurveTemplate}
                className="rounded border border-slate-600 px-2 py-1 text-[11px] text-slate-200 hover:border-slate-400"
              >
                Load Curve +1/-1
              </button>
              <button
                onClick={loadFlyTemplate}
                className="rounded border border-slate-600 px-2 py-1 text-[11px] text-slate-200 hover:border-slate-400"
              >
                Load Fly +1/-2/+1
              </button>
            </div>
          </div>
          {showFormulaBuilder && (
            <>
              <p className="mt-2 text-[11px] text-slate-400">
                Build weighted combinations from selected bonds. Weights can be risk-adjusted,
                e.g. +1 / -2.35 / +1.
              </p>

              <div className="mt-3 rounded border border-slate-700/70 bg-slate-950/60 p-2">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-300">
                    Quick Add Spreads
                  </div>
                  <div className="text-[10px] text-slate-500">
                    Built-in {YTM_QUICK_SPREAD_PRESETS.length} | Saved{' '}
                    {savedQuickSpreadPresets.length}
                  </div>
                </div>
                <div className="mt-2 flex flex-wrap gap-2">
                  {allQuickSpreadPresets.map((preset) => {
                    const isSaved = savedQuickSpreadIds.has(preset.id)
                    return (
                      <button
                        key={preset.id}
                        onClick={() => quickAddSpreadPreset(preset)}
                        title={preset.description}
                        className={`rounded border px-2 py-1 text-[11px] ${
                          isSaved
                            ? 'border-emerald-600/70 text-emerald-200 hover:border-emerald-400'
                            : 'border-cyan-600/70 text-cyan-200 hover:border-cyan-400'
                        }`}
                      >
                        {preset.name}
                        {isSaved ? ' (Saved)' : ''}
                      </button>
                    )
                  })}
                </div>
                <div className="mt-1 text-[10px] text-slate-500">
                  Adds required CT/CUSIP series, hides leg series (OFF), and plots the spread on
                  RHS.
                </div>
              </div>

              <div className="mt-3 grid gap-3 lg:grid-cols-3">
                <label className="text-[11px] text-slate-400">
                  Formula Name
                  <input
                    type="text"
                    value={formulaDraftName}
                    onChange={(e) => setFormulaDraftName(e.target.value)}
                    placeholder={`Formula ${formulaConfigs.length + 1}`}
                    className="mt-1 w-full rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-200"
                  />
                </label>
                <label className="text-[11px] text-slate-400">
                  Output Axis
                  <select
                    value={formulaDraftAxis}
                    onChange={(e) => setFormulaDraftAxis(e.target.value as TimeseriesAxis)}
                    className="mt-1 w-full rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-200"
                  >
                    <option value="y">Left Axis (LHS)</option>
                    <option value="y2">Right Axis (RHS)</option>
                  </select>
                </label>
                <div className="flex items-end gap-2">
                  <label className="mb-0.5 inline-flex items-center gap-1 text-[11px] text-slate-300">
                    <input
                      type="checkbox"
                      checked={formulaDraftScaleBy100}
                      onChange={(e) => setFormulaDraftScaleBy100(e.target.checked)}
                    />
                    x100
                  </label>
                  <button
                    onClick={addFormulaSeries}
                    className="rounded-md bg-cyan-500/90 px-3 py-1.5 text-xs font-semibold text-slate-950 hover:bg-cyan-400"
                  >
                    Add Formula
                  </button>
                  <button
                    onClick={saveFormulaDraftAsQuickSpread}
                    className="rounded-md border border-emerald-600/70 px-3 py-1.5 text-xs text-emerald-200 hover:border-emerald-400"
                  >
                    Save Spread
                  </button>
                  <button
                    onClick={resetFormulaDraft}
                    className="rounded-md border border-slate-600 px-3 py-1.5 text-xs text-slate-200 hover:border-slate-400"
                  >
                    Reset
                  </button>
                </div>
              </div>

              <div className="mt-3 space-y-2">
                {formulaDraftLegs.map((leg, idx) => (
                  <div
                    key={leg.id}
                    className="grid gap-2 md:grid-cols-[minmax(0,1fr)_120px_60px]"
                  >
                    <label className="text-[11px] text-slate-400">
                      Leg {idx + 1}
                      <select
                        value={leg.cusip}
                        onChange={(e) => updateFormulaDraftLeg(leg.id, { cusip: e.target.value })}
                        className="mt-1 w-full rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-200"
                      >
                        <option value="">Select bond</option>
                        {selectedBonds.map((bond) => (
                          <option key={bond.cusip} value={bond.cusip}>
                            {bond.cusip}
                            {bond.ust_label ? ` (${bond.ust_label})` : ''}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className="text-[11px] text-slate-400">
                      Weight
                      <input
                        type="number"
                        step="0.01"
                        value={leg.weight}
                        onChange={(e) =>
                          updateFormulaDraftLeg(leg.id, {
                            weight: normalizeFormulaWeight(e.target.value)
                          })
                        }
                        className="mt-1 w-full rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-200"
                      />
                    </label>
                    <div className="flex items-end">
                      <button
                        onClick={() => removeFormulaDraftLeg(leg.id)}
                        disabled={formulaDraftLegs.length <= 2}
                        className="w-full rounded border border-slate-700 px-2 py-1 text-[11px] text-slate-300 disabled:opacity-40"
                      >
                        Remove
                      </button>
                    </div>
                  </div>
                ))}
              </div>

              <div className="mt-2 flex flex-wrap items-center gap-2">
                <button
                  onClick={addFormulaDraftLeg}
                  className="rounded border border-slate-600 px-2 py-1 text-[11px] text-slate-200 hover:border-slate-400"
                >
                  Add Leg
                </button>
                <div className="text-[11px] text-slate-400">
                  Draft: {formulaDraftExpression}
                  {formulaDraftScaleBy100 ? ' | x100' : ''}
                </div>
              </div>

              {formulaError && (
                <div className="mt-2 rounded border border-rose-800 bg-rose-950/40 px-2 py-1 text-xs text-rose-200">
                  {formulaError}
                </div>
              )}

              {!!formulaConfigs.length && (
                <div className="mt-3 space-y-2">
                  {formulaConfigs.map((formula) => (
                    <div
                      key={formula.id}
                      className="flex flex-wrap items-center justify-between gap-2 rounded border border-slate-700 bg-slate-950/70 px-2 py-1.5"
                    >
                      <div className="min-w-0">
                        <div className="text-xs font-medium text-slate-200">{formula.name}</div>
                        <div className="text-[11px] text-slate-400">
                          {formatFormulaExpression(formula.legs)} | {axisLongLabel(formula.yaxis)}
                          {formula.scaleBy100 ? ' | x100' : ''}
                        </div>
                      </div>
                      <button
                        onClick={() => removeFormulaSeries(formula.id)}
                        className="rounded border border-slate-600 px-2 py-1 text-[11px] text-slate-300 hover:border-slate-400"
                      >
                        Remove
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-4 text-xs text-slate-300">
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={timeseriesTechnicals.sma20}
              onChange={() => toggleTimeseriesTechnical('sma20')}
            />
            SMA 20
          </label>
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={timeseriesTechnicals.sma50}
              onChange={() => toggleTimeseriesTechnical('sma50')}
            />
            SMA 50
          </label>
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={timeseriesTechnicals.ema20}
              onChange={() => toggleTimeseriesTechnical('ema20')}
            />
            EMA 20
          </label>
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={timeseriesTechnicals.ema50}
              onChange={() => toggleTimeseriesTechnical('ema50')}
            />
            EMA 50
          </label>
        </div>

        {!!timeseriesWarnings.length && (
          <div className="mt-3 rounded-md border border-amber-800 bg-amber-950/40 p-3 text-xs text-amber-200">
            {timeseriesWarnings.map((warn) => (
              <div key={warn}>{warn}</div>
            ))}
          </div>
        )}

        {timeseriesError && (
          <div className="mt-3 rounded-md border border-rose-800 bg-rose-950/40 p-3 text-xs text-rose-200">
            {timeseriesError}
          </div>
        )}

        {timeseriesLoading ? (
          <div className="mt-3 p-4 text-sm text-slate-400">Loading timeseries...</div>
        ) : timeseriesTraces.length > 0 ? (
          <div className="mt-3">
            <PlotlyFigure
              data={timeseriesTraces}
              layout={timeseriesLayout}
              config={timeseriesConfig}
            />
          </div>
        ) : (
          <div className="mt-3 p-4 text-sm text-slate-500">
            Click one or more bonds in the scatter plot to display a historical timeseries.
          </div>
        )}
      </div>

      <div className="rounded-2xl border border-slate-800 bg-slate-950/60 p-4">
        <h2 className="text-sm font-semibold text-slate-200">
          Snapshot Preview ({tableRows.length} bonds in current viewport)
        </h2>
        <p className="mt-1 text-xs text-slate-500">
          Table is synchronized to the current plot viewport. Zoom or pan to filter rows.
        </p>
        <div className="mt-3 overflow-x-auto">
          <table className="min-w-full text-left text-xs text-slate-300">
            <thead className="text-slate-400">
              <tr>
                <th className="px-2 py-1">CUSIP</th>
                <th className="px-2 py-1">Label</th>
                <th className="px-2 py-1">OI</th>
                <th className="px-2 py-1">Rank</th>
                <th className="px-2 py-1">TTM</th>
                <th className="px-2 py-1">MMSS</th>
                <th className="px-2 py-1">YTM</th>
                <th className="px-2 py-1">Clean Px</th>
              </tr>
            </thead>
            <tbody>
              {tableRows.map((row) => (
                <tr
                  key={row.cusip}
                  className={`border-t border-slate-800 ${
                    row.rank === 0 ? 'font-semibold text-white' : ''
                  }`}
                >
                  <td className="px-2 py-1">{row.cusip}</td>
                  <td className="px-2 py-1">{row.ust_label ?? '--'}</td>
                  <td className="px-2 py-1">{row.oi ?? '--'}</td>
                  <td className="px-2 py-1">{row.rank ?? '--'}</td>
                  <td className="px-2 py-1">
                    {typeof row.ttm === 'number' ? row.ttm.toFixed(3) : '--'}
                  </td>
                  <td className="px-2 py-1">
                    {typeof row.mmss === 'number' ? row.mmss.toFixed(3) : '--'}
                  </td>
                  <td className="px-2 py-1">
                    {typeof row.ytm === 'number' ? row.ytm.toFixed(3) : '--'}
                  </td>
                  <td className="px-2 py-1">
                    {typeof row.clean_price === 'number'
                      ? row.clean_price.toFixed(3)
                      : '--'}
                  </td>
                </tr>
              ))}
              {tableRows.length === 0 && (
                <tr>
                  <td colSpan={8} className="px-2 py-3 text-slate-500">
                    No bonds in current viewport.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
