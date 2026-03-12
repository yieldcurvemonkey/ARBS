import type {
  ComparisonSnapshotRow,
  SeriesConfig,
  SeriesStats,
  TimeRange,
  TimeseriesPoint,
  TimeseriesResponse,
  TimeseriesAxis,
  UstfTimeseriesMultiResponse,
  UstfTimeseriesSeriesPoint,
  UstfTimeseriesSeries,
} from './types'
import {
  STANDARD_PAIRS,
  SWAPTION_EXPIRIES,
  SWAPTION_TAILS,
  TIMESERIES_DELTA_BUCKETS,
  TIMESERIES_STRIKE_OFFSET_BUCKETS,
  USTF_EXPIRIES,
  USTF_PRODUCTS,
} from './constants'

const SNAPSHOT_DATE_FORMATTER = new Intl.DateTimeFormat('en-US', {
  timeZone: 'UTC',
  year: '2-digit',
  month: 'short',
  day: '2-digit',
})
const DAY_IN_MS = 24 * 60 * 60 * 1000

export type TimeseriesFormulaLeg = {
  seriesId: string
  weight: number
}

export type TimeseriesFormulaConfig = {
  id: string
  name: string
  yaxis: TimeseriesAxis
  scaleBy100: boolean
  legs: TimeseriesFormulaLeg[]
}

export type TimeseriesFormulaSeries = {
  id: string
  name: string
  yaxis: TimeseriesAxis
  scaleBy100: boolean
  expression: string
  points: Array<{ asOf: string; value: number | null }>
  nonNullCount: number
}

export type TimeseriesTechnicalStudyKind =
  | 'sma'
  | 'ema'
  | 'bollinger_mid'
  | 'bollinger_upper'
  | 'bollinger_lower'
  | 'rolling_zscore'
  | 'realized_vol'
  | 'momentum'
  | 'rate_of_change'

export type TimeseriesTechnicalStudyConfig = {
  id: string
  sourceSeriesId: string
  kind: TimeseriesTechnicalStudyKind
  window: number
}

export type TimeseriesTechnicalStudyAxisMode = 'overlay' | 'oscillator'

export type TimeseriesTechnicalStudySeries = {
  id: string
  sourceSeriesId: string
  kind: TimeseriesTechnicalStudyKind
  window: number
  label: string
  shortLabel: string
  axisMode: TimeseriesTechnicalStudyAxisMode
  points: Array<{ asOf: string; value: number | null }>
  latest: number | null
  latestDate: string | null
  nonNullCount: number
}

export type TimeseriesHeadlineStats = {
  latest: number | null
  min: number | null
  max: number | null
  latestDate: string | null
  change1d: number | null
  change5d: number | null
  vsSma20: number | null
  zScore20: number | null
  realizedVol20: number | null
  rangePercentile: number | null
}

export type TimeseriesSeriesSearchOption = {
  id: string
  label: string
  subtitle: string
  bucket: 'Listed' | 'OTC'
  config: SeriesConfig
  aliases: string[]
  isCommon: boolean
}

export type ParsedTimeseriesFormulaCommand = {
  formulaKind: 'spread' | 'fly'
  name: string
  description: string
  series: SeriesConfig[]
  legs: TimeseriesFormulaLeg[]
}

type NormalizedSeriesVolMetric = NonNullable<SeriesConfig['volMetric']>

const DEFAULT_SERIES_VOL_METRIC: NormalizedSeriesVolMetric = { kind: 'atm' }

function capitalizeWord(value: string): string {
  return value ? `${value[0].toUpperCase()}${value.slice(1)}` : value
}

export function getSeriesVolMetric(config: SeriesConfig): NormalizedSeriesVolMetric {
  return config.volMetric ?? DEFAULT_SERIES_VOL_METRIC
}

function formatSeriesBaseLabel(config: SeriesConfig): string {
  if (config.type === 'ustf') {
    return `${config.expiry} ${config.product ?? 'USTF'}`
  }

  return `${config.expiry}x${config.tail ?? 'OTC'}`
}

function formatMetricLabel(config: SeriesConfig, metric: NormalizedSeriesVolMetric): string {
  if (metric.kind === 'atm') {
    return config.type === 'ustf' ? 'ATM' : 'Swpn'
  }

  if (metric.kind === 'delta_otm') {
    return `${metric.delta}D ${capitalizeWord(metric.side)}${config.type === 'swaption' ? ' Swpn' : ''}`
  }

  return `${metric.offsetBps}bp ${capitalizeWord(metric.side)}${config.type === 'swaption' ? ' Swpn' : ''}`
}

function buildSeriesSearchSubtitle(config: SeriesConfig): string {
  const metric = getSeriesVolMetric(config)
  if (config.type === 'ustf') {
    if (metric.kind === 'delta_otm') return 'Listed delta-based OTM implied vol'
    if (metric.kind === 'strike_offset_otm') return 'Listed strike-offset OTM implied vol'
    return 'Listed future implied vol'
  }

  if (metric.kind === 'delta_otm') return 'OTC delta-based OTM implied vol'
  if (metric.kind === 'strike_offset_otm') return 'OTC strike-offset OTM implied vol'
  return 'OTC swaption implied vol'
}

export function findLatestComparablePoint(points: TimeseriesPoint[]): TimeseriesPoint | null {
  for (let index = points.length - 1; index >= 0; index -= 1) {
    const point = points[index]
    if (point.series1 !== null && point.series2 !== null && point.spread !== null) {
      return point
    }
  }

  return null
}

export function buildComparisonSnapshotRow(
  pairLabel: string,
  data: TimeseriesResponse
): ComparisonSnapshotRow {
  const latestPoint = findLatestComparablePoint(data.points)

  return {
    pairLabel,
    asOfDate: latestPoint?.date ?? null,
    updatedAt: null,
    listedLabel: data.series1Label,
    otcLabel: data.series2Label ?? '--',
    listedVol: latestPoint?.series1 ?? null,
    otcVol: latestPoint?.series2 ?? null,
    spread: latestPoint?.spread ?? null,
    spreadZScore: data.stats.spread?.zScore ?? null,
  }
}

export function formatVol(value: number | null, decimals = 1): string {
  if (value === null || !Number.isFinite(value)) {
    return '--'
  }

  return value.toFixed(decimals)
}

export function formatSignedNumber(value: number | null, decimals = 1): string {
  if (value === null || !Number.isFinite(value)) {
    return '--'
  }

  const formatted = value.toFixed(decimals)
  return value > 0 ? `+${formatted}` : formatted
}

export function formatSnapshotDate(value: string | null): string {
  if (!value) {
    return '--'
  }

  const parsed =
    /^\d{4}-\d{2}-\d{2}$/.test(value)
      ? new Date(`${value}T00:00:00Z`)
      : new Date(value)
  if (Number.isNaN(parsed.getTime())) {
    return value
  }

  return SNAPSHOT_DATE_FORMATTER.format(parsed).replace(',', '').toUpperCase()
}

export function getLatestSnapshotDate(rows: ComparisonSnapshotRow[]): string | null {
  return (
    rows
      .map((row) => row.asOfDate)
      .filter((value): value is string => Boolean(value))
      .sort()
      .at(-1) ?? null
  )
}

export function formatSeriesConfigLabel(config: SeriesConfig): string {
  const metric = getSeriesVolMetric(config)
  const base = formatSeriesBaseLabel(config)
  const suffix = formatMetricLabel(config, metric)
  return `${base} ${suffix}`
}

export function getSeriesConfigKey(config: SeriesConfig): string {
  const metric = getSeriesVolMetric(config)
  const base =
    config.type === 'ustf'
      ? `ustf:${config.product ?? 'unknown'}:${config.expiry}`
      : `swaption:${config.tail ?? 'unknown'}:${config.expiry}`

  if (metric.kind === 'atm') {
    return base
  }

  if (metric.kind === 'delta_otm') {
    return `${base}:delta:${metric.side}:${metric.delta}`
  }

  return `${base}:offset:${metric.side}:${metric.offsetBps}`
}

export function formatFormulaWeight(weight: number): string {
  const abs = Math.abs(weight)
  const magnitude = Number.isInteger(abs) ? abs.toFixed(0) : abs.toFixed(4)
  return `${weight >= 0 ? '+' : '-'}${magnitude}`
}

export function formatFormulaExpression(legs: TimeseriesFormulaLeg[]): string {
  if (!legs.length) {
    return '--'
  }

  return legs
    .map((leg, index) => {
      const token = `${formatFormulaWeight(leg.weight)} * ${leg.seriesId || '?'}`
      return index === 0 ? token.replace(/^\+/, '') : token
    })
    .join(' ')
}

export function normalizeFormulaWeight(value: unknown): number {
  const normalized = Number(value)
  return Number.isFinite(normalized) ? normalized : 0
}

export function normalizeFormulaLegs(
  legs: Array<{ seriesId: unknown; weight: unknown }>
): TimeseriesFormulaLeg[] {
  const combined = new Map<string, number>()

  for (const leg of legs) {
    const seriesId = String(leg.seriesId ?? '').trim()
    const weight = normalizeFormulaWeight(leg.weight)
    if (!seriesId || !Number.isFinite(weight)) {
      continue
    }

    combined.set(seriesId, (combined.get(seriesId) ?? 0) + weight)
  }

  return Array.from(combined.entries())
    .filter(([, weight]) => Math.abs(weight) > 1e-12)
    .map(([seriesId, weight]) => ({ seriesId, weight }))
}

export function buildFormulaSeries(
  config: TimeseriesFormulaConfig,
  seriesMap: Map<string, UstfTimeseriesSeries>
): TimeseriesFormulaSeries | null {
  const legs = normalizeFormulaLegs(config.legs)
  if (legs.length < 2) {
    return null
  }

  const legValueMaps: Array<{ leg: TimeseriesFormulaLeg; values: Map<string, number> }> = []
  const allDates = new Set<string>()

  for (const leg of legs) {
    const baseSeries = seriesMap.get(leg.seriesId)
    if (!baseSeries) {
      return null
    }

    const values = new Map<string, number>()
    for (const point of baseSeries.points) {
      const numericValue = Number(point.value)
      if (!Number.isFinite(numericValue)) {
        continue
      }

      values.set(point.asOf, numericValue)
      allDates.add(point.asOf)
    }

    legValueMaps.push({ leg, values })
  }

  const dates = Array.from(allDates).sort((left, right) => left.localeCompare(right))
  const scaleFactor = config.scaleBy100 ? 100 : 1

  if (!dates.length) {
    return {
      id: config.id,
      name: config.name,
      yaxis: config.yaxis,
      scaleBy100: config.scaleBy100,
      expression: formatFormulaExpression(legs),
      points: [],
      nonNullCount: 0,
    }
  }

  let nonNullCount = 0
  const points = dates.map((asOf) => {
    let sum = 0

    for (const legItem of legValueMaps) {
      const value = legItem.values.get(asOf)
      if (value === undefined) {
        return { asOf, value: null }
      }

      sum += legItem.leg.weight * value
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
    nonNullCount,
  }
}

type NumericSeriesPoint = {
  index: number
  asOf: string
  value: number
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}

function toNumericSeriesPoints(points: UstfTimeseriesSeriesPoint[]): NumericSeriesPoint[] {
  return points.flatMap((point, index) =>
    isFiniteNumber(point.value) ? [{ index, asOf: point.asOf, value: point.value }] : []
  )
}

function computeMean(values: number[]): number {
  return values.reduce((sum, value) => sum + value, 0) / values.length
}

function computeStdev(values: number[]): number {
  if (!values.length) return 0
  const mean = computeMean(values)
  const variance =
    values.reduce((sum, value) => sum + (value - mean) ** 2, 0) / values.length
  return Math.sqrt(variance)
}

function computeLatestRollingZScore(values: number[], window: number): number | null {
  if (values.length < window) return null
  const slice = values.slice(-window)
  const mean = computeMean(slice)
  const stdev = computeStdev(slice)
  if (stdev <= 1e-12) return null
  return (slice[slice.length - 1] - mean) / stdev
}

function computeLatestRealizedVol(values: number[], window: number): number | null {
  if (values.length < window + 1) return null
  const slice = values.slice(-(window + 1))
  const diffs = slice.slice(1).map((value, index) => value - slice[index])
  return computeStdev(diffs) * Math.sqrt(252)
}

function finalizeTechnicalStudySeries(
  config: TimeseriesTechnicalStudyConfig,
  points: Array<{ asOf: string; value: number | null }>
): TimeseriesTechnicalStudySeries {
  const latestPoint = [...points]
    .reverse()
    .find((point) => isFiniteNumber(point.value))
  const normalizedWindow = Math.max(2, Math.round(config.window))

  return {
    id: config.id,
    sourceSeriesId: config.sourceSeriesId,
    kind: config.kind,
    window: normalizedWindow,
    label: formatTechnicalStudyLabel(config.kind, normalizedWindow),
    shortLabel: formatTechnicalStudyShortLabel(config.kind, normalizedWindow),
    axisMode: getTimeseriesTechnicalStudyAxisMode(config.kind),
    points,
    latest: latestPoint?.value ?? null,
    latestDate: latestPoint?.asOf ?? null,
    nonNullCount: points.filter((point) => isFiniteNumber(point.value)).length,
  }
}

export function formatTechnicalStudyLabel(
  kind: TimeseriesTechnicalStudyKind,
  window: number
): string {
  const normalizedWindow = Math.max(2, Math.round(window))

  switch (kind) {
    case 'sma':
      return `Simple moving average ${normalizedWindow}`
    case 'ema':
      return `Exponential moving average ${normalizedWindow}`
    case 'bollinger_mid':
      return `Bollinger mid ${normalizedWindow}`
    case 'bollinger_upper':
      return `Bollinger +2σ ${normalizedWindow}`
    case 'bollinger_lower':
      return `Bollinger -2σ ${normalizedWindow}`
    case 'rolling_zscore':
      return `Rolling z-score ${normalizedWindow}`
    case 'realized_vol':
      return `Realized vol ${normalizedWindow}`
    case 'momentum':
      return `Momentum ${normalizedWindow}`
    case 'rate_of_change':
      return `Rate of change ${normalizedWindow}`
  }
}

export function formatTechnicalStudyShortLabel(
  kind: TimeseriesTechnicalStudyKind,
  window: number
): string {
  const normalizedWindow = Math.max(2, Math.round(window))

  switch (kind) {
    case 'sma':
      return `SMA ${normalizedWindow}`
    case 'ema':
      return `EMA ${normalizedWindow}`
    case 'bollinger_mid':
      return `Boll Mid ${normalizedWindow}`
    case 'bollinger_upper':
      return `Boll +2σ ${normalizedWindow}`
    case 'bollinger_lower':
      return `Boll -2σ ${normalizedWindow}`
    case 'rolling_zscore':
      return `Z ${normalizedWindow}`
    case 'realized_vol':
      return `RV ${normalizedWindow}`
    case 'momentum':
      return `Mom ${normalizedWindow}`
    case 'rate_of_change':
      return `ROC ${normalizedWindow}`
  }
}

export function getTimeseriesTechnicalStudyAxisMode(
  kind: TimeseriesTechnicalStudyKind
): TimeseriesTechnicalStudyAxisMode {
  switch (kind) {
    case 'sma':
    case 'ema':
    case 'bollinger_mid':
    case 'bollinger_upper':
    case 'bollinger_lower':
      return 'overlay'
    case 'rolling_zscore':
    case 'realized_vol':
    case 'momentum':
    case 'rate_of_change':
      return 'oscillator'
  }
}

export function buildTechnicalStudySeries(
  config: TimeseriesTechnicalStudyConfig,
  baseSeries: UstfTimeseriesSeries
): TimeseriesTechnicalStudySeries {
  const normalizedWindow = Math.max(2, Math.round(config.window))
  const validPoints = toNumericSeriesPoints(baseSeries.points)
  const derivedPoints = baseSeries.points.map((point) => ({ asOf: point.asOf, value: null as number | null }))

  if (!validPoints.length) {
    return finalizeTechnicalStudySeries(config, derivedPoints)
  }

  const validValues = validPoints.map((point) => point.value)

  if (config.kind === 'ema') {
    const multiplier = 2 / (normalizedWindow + 1)
    let previousEma: number | null = null

    for (let index = 0; index < validPoints.length; index += 1) {
      if (index + 1 < normalizedWindow) continue

      if (previousEma === null) {
        previousEma = computeMean(validValues.slice(index + 1 - normalizedWindow, index + 1))
      } else {
        previousEma = (validValues[index] - previousEma) * multiplier + previousEma
      }

      derivedPoints[validPoints[index].index] = {
        asOf: validPoints[index].asOf,
        value: previousEma,
      }
    }

    return finalizeTechnicalStudySeries(config, derivedPoints)
  }

  for (let index = 0; index < validPoints.length; index += 1) {
    const point = validPoints[index]
    const levelWindow =
      index + 1 >= normalizedWindow
        ? validValues.slice(index + 1 - normalizedWindow, index + 1)
        : null

    if (config.kind === 'sma' && levelWindow) {
      derivedPoints[point.index] = { asOf: point.asOf, value: computeMean(levelWindow) }
      continue
    }

    if ((config.kind === 'bollinger_mid' || config.kind === 'bollinger_upper' || config.kind === 'bollinger_lower') && levelWindow) {
      const mean = computeMean(levelWindow)
      const stdev = computeStdev(levelWindow)
      const offset =
        config.kind === 'bollinger_mid' ? 0 : config.kind === 'bollinger_upper' ? 2 * stdev : -2 * stdev

      derivedPoints[point.index] = { asOf: point.asOf, value: mean + offset }
      continue
    }

    if (config.kind === 'rolling_zscore' && levelWindow) {
      const mean = computeMean(levelWindow)
      const stdev = computeStdev(levelWindow)
      derivedPoints[point.index] = {
        asOf: point.asOf,
        value: stdev > 1e-12 ? (point.value - mean) / stdev : null,
      }
      continue
    }

    if (config.kind === 'realized_vol' && index >= normalizedWindow) {
      const trailingValues = validValues.slice(index - normalizedWindow, index + 1)
      const diffs = trailingValues.slice(1).map((value, diffIndex) => value - trailingValues[diffIndex])
      derivedPoints[point.index] = {
        asOf: point.asOf,
        value: computeStdev(diffs) * Math.sqrt(252),
      }
      continue
    }

    if (config.kind === 'momentum' && index >= normalizedWindow) {
      derivedPoints[point.index] = {
        asOf: point.asOf,
        value: point.value - validValues[index - normalizedWindow],
      }
      continue
    }

    if (config.kind === 'rate_of_change' && index >= normalizedWindow) {
      const priorValue = validValues[index - normalizedWindow]
      derivedPoints[point.index] = {
        asOf: point.asOf,
        value: Math.abs(priorValue) > 1e-12 ? ((point.value / priorValue) - 1) * 100 : null,
      }
    }
  }

  return finalizeTechnicalStudySeries(config, derivedPoints)
}

export function computeTimeseriesHeadlineStats(
  points: UstfTimeseriesSeriesPoint[]
): TimeseriesHeadlineStats {
  const validPoints = toNumericSeriesPoints(points)
  const values = validPoints.map((point) => point.value)
  const latestPoint = validPoints[validPoints.length - 1]
  const latest = latestPoint?.value ?? null
  const min = values.length ? Math.min(...values) : null
  const max = values.length ? Math.max(...values) : null

  return {
    latest,
    min,
    max,
    latestDate: latestPoint?.asOf ?? null,
    change1d: values.length >= 2 ? latest! - values[values.length - 2] : null,
    change5d: values.length >= 6 ? latest! - values[values.length - 6] : null,
    vsSma20: values.length >= 20 ? latest! - computeMean(values.slice(-20)) : null,
    zScore20: computeLatestRollingZScore(values, 20),
    realizedVol20: computeLatestRealizedVol(values, 20),
    rangePercentile:
      latest === null || min === null || max === null
        ? null
        : max - min <= 1e-12
          ? 50
          : ((latest - min) / (max - min)) * 100,
  }
}

function normalizeSearchText(value: string): string {
  return value
    .toUpperCase()
    .replace(/SWAPTION/g, 'OTC')
    .replace(/FUTURES?/g, 'USTF')
    .replace(/[^A-Z0-9]+/g, '')
}

function uniqueStrings(values: string[]): string[] {
  return Array.from(new Set(values.map((value) => value.trim()).filter(Boolean)))
}

function scoreNormalizedQuery(query: string, candidate: string): number {
  if (!query || !candidate) return -1
  if (query === candidate) return 1200 - candidate.length
  if (candidate.startsWith(query)) return 900 - (candidate.length - query.length)

  const includesAt = candidate.indexOf(query)
  if (includesAt >= 0) {
    return 700 - includesAt * 4 - (candidate.length - query.length)
  }

  let queryIndex = 0
  let score = 0
  let streak = 0

  for (let candidateIndex = 0; candidateIndex < candidate.length; candidateIndex += 1) {
    if (candidate[candidateIndex] === query[queryIndex]) {
      queryIndex += 1
      streak += 1
      score += 14 + streak * 6
      if (queryIndex === query.length) {
        return 360 + score - candidate.length
      }
    } else {
      streak = 0
    }
  }

  return -1
}

function scoreSeriesSearchOption(
  query: string,
  option: TimeseriesSeriesSearchOption
): number {
  const normalizedQuery = normalizeSearchText(query)
  if (!normalizedQuery) {
    return option.isCommon ? 100 : 10
  }

  const texts = [option.label, option.subtitle, ...option.aliases]
  const bestScore = texts.reduce((currentBest, text) => {
    return Math.max(currentBest, scoreNormalizedQuery(normalizedQuery, normalizeSearchText(text)))
  }, -1)

  if (bestScore < 0) return -1
  return bestScore + (option.isCommon ? 35 : 0)
}

function buildSeriesAliases(config: SeriesConfig): string[] {
  const metric = getSeriesVolMetric(config)
  if (config.type === 'ustf') {
    const product = config.product ?? 'USTF'
    const baseAliases = [
      `${config.expiry} ${product}`,
      `${product} ${config.expiry}`,
      `${config.expiry}${product}`,
      `${product}${config.expiry}`,
      `USTF ${product} ${config.expiry}`,
    ]

    if (metric.kind === 'atm') {
      return uniqueStrings([
        ...baseAliases,
        `${config.expiry} ${product} ATM`,
        `${product} ATM ${config.expiry}`,
      ])
    }

    if (metric.kind === 'delta_otm') {
      const sideLabel = capitalizeWord(metric.side)
      const sideCode = metric.side === 'call' ? 'C' : 'P'
      return uniqueStrings([
        ...baseAliases.flatMap((alias) => [
          `${alias} ${metric.delta}D ${sideLabel}`,
          `${alias} ${sideLabel} ${metric.delta}D`,
          `${alias} ${metric.delta}D${sideCode}`,
        ]),
        `${product}${config.expiry}${metric.delta}D${sideCode}`,
        `${config.expiry} ${product} OTM ${metric.delta}D ${sideLabel}`,
      ])
    }

    const sideLabel = capitalizeWord(metric.side)
    const sideCode = metric.side === 'call' ? 'C' : 'P'
    return uniqueStrings([
      ...baseAliases.flatMap((alias) => [
        `${alias} ${metric.offsetBps}BP ${sideLabel}`,
        `${alias} ${sideLabel} ${metric.offsetBps}BP`,
        `${alias} ${metric.offsetBps}BP${sideCode}`,
      ]),
      `${product}${config.expiry}${metric.offsetBps}BP${sideCode}`,
      `${config.expiry} ${product} OTM ${metric.offsetBps}BP ${sideLabel}`,
    ])
  }

  const tail = config.tail ?? 'OTC'
  const baseAliases = [
    `${config.expiry}x${tail}`,
    `${config.expiry} ${tail}`,
    `${tail} ${config.expiry}`,
    `${config.expiry}${tail}`,
    `${tail}${config.expiry}`,
    `OTC ${config.expiry} ${tail}`,
    `SWAPTION ${config.expiry} ${tail}`,
  ]

  if (metric.kind === 'atm') {
    return uniqueStrings(baseAliases)
  }

  if (metric.kind === 'delta_otm') {
    const sideLabel = capitalizeWord(metric.side)
    const sideCode = metric.side === 'payer' ? 'P' : 'R'
    return uniqueStrings([
      ...baseAliases.flatMap((alias) => [
        `${alias} ${metric.delta}D ${sideLabel}`,
        `${alias} ${sideLabel} ${metric.delta}D`,
        `${alias} ${metric.delta}D${sideCode}`,
      ]),
      `${config.expiry}x${tail}${metric.delta}D${sideCode}`,
      `${config.expiry}x${tail} OTM ${metric.delta}D ${sideLabel}`,
    ])
  }

  const sideLabel = capitalizeWord(metric.side)
  const sideCode = metric.side === 'payer' ? 'P' : 'R'
  return uniqueStrings([
    ...baseAliases.flatMap((alias) => [
      `${alias} ${metric.offsetBps}BP ${sideLabel}`,
      `${alias} ${sideLabel} ${metric.offsetBps}BP`,
      `${alias} ${metric.offsetBps}BP${sideCode}`,
    ]),
    `${config.expiry}x${tail}${metric.offsetBps}BP${sideCode}`,
    `${config.expiry}x${tail} OTM ${metric.offsetBps}BP ${sideLabel}`,
  ])
}

function buildMetricSeriesConfigs(baseConfig: SeriesConfig): SeriesConfig[] {
  const configs: SeriesConfig[] = [baseConfig]

  if (baseConfig.type === 'ustf') {
    for (const delta of TIMESERIES_DELTA_BUCKETS) {
      configs.push({ ...baseConfig, volMetric: { kind: 'delta_otm', side: 'call', delta } })
      configs.push({ ...baseConfig, volMetric: { kind: 'delta_otm', side: 'put', delta } })
    }
    for (const offsetBps of TIMESERIES_STRIKE_OFFSET_BUCKETS) {
      configs.push({
        ...baseConfig,
        volMetric: { kind: 'strike_offset_otm', side: 'call', offsetBps },
      })
      configs.push({
        ...baseConfig,
        volMetric: { kind: 'strike_offset_otm', side: 'put', offsetBps },
      })
    }
    return configs
  }

  for (const delta of TIMESERIES_DELTA_BUCKETS) {
    configs.push({ ...baseConfig, volMetric: { kind: 'delta_otm', side: 'payer', delta } })
    configs.push({ ...baseConfig, volMetric: { kind: 'delta_otm', side: 'receiver', delta } })
  }
  for (const offsetBps of TIMESERIES_STRIKE_OFFSET_BUCKETS) {
    configs.push({
      ...baseConfig,
      volMetric: { kind: 'strike_offset_otm', side: 'payer', offsetBps },
    })
    configs.push({
      ...baseConfig,
      volMetric: { kind: 'strike_offset_otm', side: 'receiver', offsetBps },
    })
  }

  return configs
}

export function buildTimeseriesSeriesSearchOptions(): TimeseriesSeriesSearchOption[] {
  const commonIds = new Set(
    STANDARD_PAIRS.flatMap((pair) => [
      getSeriesConfigKey(pair.series1),
      getSeriesConfigKey(pair.series2),
    ])
  )

  const listedOptions: TimeseriesSeriesSearchOption[] = USTF_EXPIRIES.flatMap((expiry) =>
    USTF_PRODUCTS.flatMap((product) =>
      buildMetricSeriesConfigs({ type: 'ustf', product, expiry }).map((config) => ({
        id: getSeriesConfigKey(config),
        label: formatSeriesConfigLabel(config),
        subtitle: buildSeriesSearchSubtitle(config),
        bucket: 'Listed' as const,
        config,
        aliases: buildSeriesAliases(config),
        isCommon:
          getSeriesVolMetric(config).kind === 'atm' &&
          (commonIds.has(getSeriesConfigKey(config)) || expiry === '1M'),
      }))
    )
  )

  const otcOptions: TimeseriesSeriesSearchOption[] = SWAPTION_EXPIRIES.flatMap((expiry) =>
    SWAPTION_TAILS.flatMap((tail) =>
      buildMetricSeriesConfigs({ type: 'swaption', tail, expiry }).map((config) => ({
        id: getSeriesConfigKey(config),
        label: formatSeriesConfigLabel(config),
        subtitle: buildSeriesSearchSubtitle(config),
        bucket: 'OTC' as const,
        config,
        aliases: buildSeriesAliases(config),
        isCommon:
          getSeriesVolMetric(config).kind === 'atm' &&
          (commonIds.has(getSeriesConfigKey(config)) || expiry === '1M'),
      }))
    )
  )

  return [...listedOptions, ...otcOptions]
}

export function searchTimeseriesSeriesOptions(
  query: string,
  options: TimeseriesSeriesSearchOption[],
  limit = 8
): TimeseriesSeriesSearchOption[] {
  return options
    .map((option) => ({ option, score: scoreSeriesSearchOption(query, option) }))
    .filter(({ score }) => score >= 0)
    .sort((left, right) => {
      if (right.score !== left.score) return right.score - left.score
      return left.option.label.localeCompare(right.option.label)
    })
    .slice(0, limit)
    .map(({ option }) => option)
}

function resolveSeriesSearchToken(
  token: string,
  options: TimeseriesSeriesSearchOption[]
): TimeseriesSeriesSearchOption | null {
  const normalizedToken = normalizeSearchText(token)
  if (!normalizedToken) return null

  const exactMatches = options.filter((option) =>
    [option.label, ...option.aliases].some(
      (candidate) => normalizeSearchText(candidate) === normalizedToken
    )
  )

  if (exactMatches.length === 1) {
    return exactMatches[0]
  }

  const ranked = options
    .map((option) => ({ option, score: scoreSeriesSearchOption(token, option) }))
    .filter(({ score }) => score >= 0)
    .sort((left, right) => right.score - left.score)

  const best = ranked[0]
  const second = ranked[1]

  if (!best || best.score < 260) {
    return null
  }

  if (second && best.score - second.score < 70) {
    return null
  }

  return best.option
}

function splitSpreadCommandBody(value: string): string[] {
  const separators = [/\s+(?:VS|VERSUS|OVER)\s+/i, /\s*\/\s*/, /\s*-\s*/]

  for (const separator of separators) {
    const parts = value
      .split(separator)
      .map((part) => part.trim())
      .filter(Boolean)
    if (parts.length === 2) {
      return parts
    }
  }

  return []
}

function splitFlyCommandBody(value: string): string[] {
  const separators = [/\s*\/\s*/, /\s*>\s*/, /\s*,\s*/, /\s*-\s*/]

  for (const separator of separators) {
    const parts = value
      .split(separator)
      .map((part) => part.trim())
      .filter(Boolean)
    if (parts.length === 3) {
      return parts
    }
  }

  return []
}

export function parseTimeseriesFormulaCommand(
  query: string,
  options: TimeseriesSeriesSearchOption[]
): ParsedTimeseriesFormulaCommand | null {
  const trimmed = query.trim()
  if (!trimmed) return null

  let formulaKind: ParsedTimeseriesFormulaCommand['formulaKind'] | null = null
  let parts: string[] = []

  if (/^SPREAD\s+/i.test(trimmed)) {
    formulaKind = 'spread'
    parts = splitSpreadCommandBody(trimmed.replace(/^SPREAD\s+/i, ''))
  } else if (/^FLY\s+/i.test(trimmed)) {
    formulaKind = 'fly'
    parts = splitFlyCommandBody(trimmed.replace(/^FLY\s+/i, ''))
  } else {
    parts = splitFlyCommandBody(trimmed)
    if (parts.length === 3) {
      formulaKind = 'fly'
    } else {
      parts = splitSpreadCommandBody(trimmed)
      if (parts.length === 2) {
        formulaKind = 'spread'
      }
    }
  }

  if (!formulaKind) {
    return null
  }

  const resolved = parts.map((part) => resolveSeriesSearchToken(part, options))
  if (resolved.some((value) => value === null)) {
    return null
  }

  const matches = resolved.filter(
    (value): value is TimeseriesSeriesSearchOption => value !== null
  )
  const labels = matches.map((match) => match.label)

  if (formulaKind === 'spread') {
    return {
      formulaKind,
      name: `${labels[0]} vs ${labels[1]}`,
      description: `${labels[0]} - ${labels[1]}`,
      series: matches.map((match) => match.config),
      legs: [
        { seriesId: matches[0].id, weight: 1 },
        { seriesId: matches[1].id, weight: -1 },
      ],
    }
  }

  return {
    formulaKind,
    name: `${labels[0]} / ${labels[1]} / ${labels[2]} fly`,
    description: `${labels[0]} - 2 * ${labels[1]} + ${labels[2]}`,
    series: matches.map((match) => match.config),
    legs: [
      { seriesId: matches[0].id, weight: 1 },
      { seriesId: matches[1].id, weight: -2 },
      { seriesId: matches[2].id, weight: 1 },
    ],
  }
}

export function getTimeseriesWindowBounds(
  response: UstfTimeseriesMultiResponse | null
): { startDate: string | null; endDate: string | null } {
  if (!response) {
    return { startDate: null, endDate: null }
  }

  return {
    startDate: response.startDate,
    endDate: response.endDate,
  }
}

function parseIsoDate(value: string): Date | null {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    return null
  }

  const parsed = new Date(`${value}T00:00:00Z`)
  return Number.isNaN(parsed.getTime()) ? null : parsed
}

function dayDiff(startDate: string, endDate: string): number | null {
  const start = parseIsoDate(startDate)
  const end = parseIsoDate(endDate)
  if (!start || !end) {
    return null
  }

  return Math.round((end.getTime() - start.getTime()) / DAY_IN_MS)
}

function getRangeLookbackDays(range: TimeRange): number {
  switch (range) {
    case '1M':
      return 31
    case '3M':
      return 92
    case '6M':
      return 183
    case '1Y':
      return 366
    case 'ALL':
      return 3650
  }
}

export function shiftIsoDate(dateIso: string, days: number): string {
  const parsed = parseIsoDate(dateIso)
  if (!parsed) return dateIso

  parsed.setUTCDate(parsed.getUTCDate() + days)
  return parsed.toISOString().slice(0, 10)
}

export function computeSeriesStats(values: Array<number | null>): SeriesStats {
  const clean = values.filter((value): value is number => value !== null && Number.isFinite(value))
  if (!clean.length) {
    return {
      latest: null,
      mean: null,
      min: null,
      max: null,
      stdev: null,
      zScore: null,
      count: 0,
    }
  }

  const latest = clean[clean.length - 1]
  const mean = clean.reduce((sum, value) => sum + value, 0) / clean.length
  const min = Math.min(...clean)
  const max = Math.max(...clean)
  const variance =
    clean.reduce((sum, value) => sum + (value - mean) ** 2, 0) / clean.length
  const stdev = Math.sqrt(variance)

  return {
    latest,
    mean,
    min,
    max,
    stdev,
    zScore: stdev > 1e-12 ? (latest - mean) / stdev : null,
    count: clean.length,
  }
}

export function getTimeseriesHistoricalWindow(params: {
  currentStartDate: string | null
  range: TimeRange
  initialStartDate?: string
  initialEndDate?: string
}): { startDate: string; endDate: string } | null {
  if (!params.currentStartDate) {
    return null
  }

  const customSpanDays =
    params.initialStartDate && params.initialEndDate
      ? dayDiff(params.initialStartDate, params.initialEndDate)
      : null
  const lookbackDays = Math.max(
    30,
    Math.min(
      3650,
      customSpanDays !== null && customSpanDays >= 0
        ? customSpanDays + 1
        : getRangeLookbackDays(params.range)
    )
  )

  return {
    startDate: shiftIsoDate(params.currentStartDate, -lookbackDays),
    endDate: shiftIsoDate(params.currentStartDate, -1),
  }
}

export function shouldPrefetchHistoricalTimeseries(params: {
  loadedStartDate: string | null
  viewportStartDate: string | null
  viewportEndDate: string | null
  hasMoreHistorical: boolean
  loadingHistorical: boolean
}): boolean {
  if (
    !params.hasMoreHistorical ||
    params.loadingHistorical ||
    !params.loadedStartDate ||
    !params.viewportStartDate ||
    !params.viewportEndDate
  ) {
    return false
  }

  const daysFromLoadedStart = dayDiff(params.loadedStartDate, params.viewportStartDate)
  const visibleWindowDays = dayDiff(params.viewportStartDate, params.viewportEndDate)

  if (daysFromLoadedStart === null || visibleWindowDays === null) {
    return false
  }

  if (daysFromLoadedStart <= 0) {
    return true
  }

  const prefetchThresholdDays = Math.max(
    7,
    Math.min(45, Math.ceil(Math.max(visibleWindowDays, 1) * 0.25))
  )

  return daysFromLoadedStart <= prefetchThresholdDays
}

function mergeSeriesPoints(
  existingPoints: UstfTimeseriesSeriesPoint[],
  incomingPoints: UstfTimeseriesSeriesPoint[]
): UstfTimeseriesSeriesPoint[] {
  if (!incomingPoints.length) {
    return existingPoints
  }

  const mergedByDate = new Map(existingPoints.map((point) => [point.asOf, point]))

  for (const point of incomingPoints) {
    mergedByDate.set(point.asOf, point)
  }

  const mergedPoints = Array.from(mergedByDate.values()).sort((left, right) =>
    left.asOf.localeCompare(right.asOf)
  )

  if (
    mergedPoints.length === existingPoints.length &&
    mergedPoints.every(
      (point, index) =>
        point.asOf === existingPoints[index]?.asOf &&
        point.value === existingPoints[index]?.value
    )
  ) {
    return existingPoints
  }

  return mergedPoints
}

export function mergeTimeseriesCollection(
  current: UstfTimeseriesMultiResponse,
  incoming: UstfTimeseriesMultiResponse
): UstfTimeseriesMultiResponse {
  const incomingById = new Map(incoming.series.map((series) => [series.id, series]))
  const seenSeriesIds = new Set<string>()
  let didChange = false

  const mergedSeries = current.series.map((series) => {
    seenSeriesIds.add(series.id)
    const nextSeries = incomingById.get(series.id)
    if (!nextSeries) {
      return series
    }

    const mergedPoints = mergeSeriesPoints(series.points, nextSeries.points)
    if (mergedPoints === series.points) {
      return series
    }

    didChange = true
    return {
      ...series,
      points: mergedPoints,
      stats: computeSeriesStats(mergedPoints.map((point) => point.value)),
    }
  })

  for (const nextSeries of incoming.series) {
    if (seenSeriesIds.has(nextSeries.id)) {
      continue
    }

    didChange = true
    mergedSeries.push({
      ...nextSeries,
      stats: computeSeriesStats(nextSeries.points.map((point) => point.value)),
    })
  }

  const allDates = mergedSeries.flatMap((series) => series.points.map((point) => point.asOf)).sort()
  const startDate = allDates[0] ?? null
  const endDate = allDates.at(-1) ?? null

  if (
    !didChange &&
    current.startDate === startDate &&
    current.endDate === endDate &&
    current.asOfDate === endDate
  ) {
    return current
  }

  return {
    ...current,
    startDate,
    endDate,
    asOfDate: endDate,
    series: mergedSeries,
  }
}
