import type {
  ListedOptionDerivedFormulaSeries,
  ListedOptionMetricField,
  ListedOptionRange,
  ListedOptionSearchOption,
  ListedOptionSeriesConfig,
  ListedOptionSeriesStats,
  ListedOptionSnapshotRow,
  ListedOptionSnapshotResponse,
  ListedOptionTimeseriesFormulaConfig,
  ListedOptionTimeseriesFormulaLeg,
  ListedOptionTimeseriesMultiResponse,
  ListedOptionTimeseriesPoint,
  ListedOptionTimeseriesSeries,
} from './types'

function normalizeText(value: string) {
  return value.toUpperCase().replace(/[^A-Z0-9]+/g, '')
}

function parseNumericValue(value: number | string | null | undefined): number | null {
  if (value === null || value === undefined || value === '') return null
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

function parseOptionalNumericInput(value: string | null | undefined): number | null {
  if (value === null || value === undefined) return null
  const token = String(value).trim()
  if (!token) return null
  const parsed = Number(token)
  return Number.isFinite(parsed) ? parsed : null
}

function sideLabel(side: ListedOptionSeriesConfig['side']) {
  switch (side) {
    case 'C':
      return 'Call'
    case 'P':
      return 'Put'
    case 'S':
      return 'Straddle'
  }
}

export function metricFieldLabel(field: ListedOptionMetricField) {
  switch (field) {
    case 'open_interest':
      return 'Open interest'
    case 'volume':
      return 'Volume'
    case 'open_interest_change':
      return 'Open interest change'
    case 'volume_change':
      return 'Volume change'
  }
}

export function metricFieldShortLabel(field: ListedOptionMetricField) {
  switch (field) {
    case 'open_interest':
      return 'OI'
    case 'volume':
      return 'Vol'
    case 'open_interest_change':
      return 'dOI'
    case 'volume_change':
      return 'dVol'
  }
}

export function rangeToInterval(range: ListedOptionRange) {
  switch (range) {
    case '1M':
      return '1 month'
    case '3M':
      return '3 months'
    case '6M':
      return '6 months'
    case '1Y':
      return '1 year'
    case 'ALL':
      return '10 years'
  }
}

export function formatNumber(value: number | null, decimals = 0) {
  if (value === null || !Number.isFinite(value)) return '--'
  return value.toLocaleString('en-US', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })
}

export function filterSnapshotRowsByAxisRange(
  rows: ListedOptionSnapshotRow[],
  topValue: string,
  bottomValue: string
) {
  const top = parseOptionalNumericInput(topValue)
  const bottom = parseOptionalNumericInput(bottomValue)
  const hasTop = top !== null
  const hasBottom = bottom !== null

  if (!hasTop && !hasBottom) {
    return rows
  }

  return rows.filter((row) => {
    if (row.axisValue === null) return true
    const upper = hasTop && hasBottom ? Math.max(top, bottom) : hasTop ? top : Number.POSITIVE_INFINITY
    const lower = hasTop && hasBottom ? Math.min(top, bottom) : hasBottom ? bottom : Number.NEGATIVE_INFINITY
    return row.axisValue <= upper && row.axisValue >= lower
  })
}

export function formatSignedNumber(value: number | null, decimals = 0) {
  if (value === null || !Number.isFinite(value)) return '--'
  const prefix = value > 0 ? '+' : ''
  return `${prefix}${formatNumber(value, decimals)}`
}

export function formatSnapshotDate(value: string | null) {
  if (!value) return '--'
  const parsed = new Date(`${value.slice(0, 10)}T12:00:00Z`)
  if (Number.isNaN(parsed.getTime())) return value
  return parsed.toLocaleDateString('en-US', {
    month: 'short',
    day: '2-digit',
    year: '2-digit',
    timeZone: 'UTC',
  }).toUpperCase()
}

export function getSeriesConfigKey(config: ListedOptionSeriesConfig) {
  const selectorToken =
    config.selectorType === 'explicit_symbol'
      ? `symbol:${String(config.rawSymbolFallback ?? config.selectorValue ?? '').toUpperCase()}`
      : `${config.selectorType}:${String(config.selectorValue ?? '').toUpperCase()}`
  const contractToken =
    config.contractReferenceMode === 'constant_maturity'
      ? `cm:${config.productRoot}:${config.constantMaturityRank ?? ''}`
      : `contract:${String(config.explicitContract ?? '').toUpperCase()}`

  return [
    config.metricField,
    config.productFamily ?? '',
    config.productRoot,
    contractToken,
    selectorToken,
    config.side,
  ].join(':')
}

export function formatSeriesConfigLabel(config: ListedOptionSeriesConfig) {
  const metric = metricFieldShortLabel(config.metricField)
  const base =
    config.contractReferenceMode === 'constant_maturity'
      ? `${config.productRoot} CM${config.constantMaturityRank ?? '?'}`
      : config.explicitContract || config.productRoot

  if (config.selectorType === 'explicit_symbol') {
    return `${String(config.rawSymbolFallback ?? base)} ${metric}`.trim()
  }

  const selectorValue = parseNumericValue(config.selectorValue)
  if (config.selectorType === 'strike') {
    const strikeLabel =
      selectorValue === null ? String(config.selectorValue ?? '--') : formatNumber(selectorValue, 3)
    return `${base} ${strikeLabel} ${sideLabel(config.side)} ${metric}`
  }

  if (config.selectorType === 'delta') {
    const deltaLabel =
      selectorValue === null ? String(config.selectorValue ?? '--') : formatNumber(selectorValue, 0)
    return `${base} ${deltaLabel}D ${sideLabel(config.side)} ${metric}`
  }

  const bpsLabel =
    selectorValue === null ? String(config.selectorValue ?? '--') : formatNumber(selectorValue, 2)
  return `${base} ${bpsLabel}bp ${sideLabel(config.side)} ${metric}`
}

export function computeSeriesStats(values: Array<number | null>): ListedOptionSeriesStats {
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

  const latest = clean[clean.length - 1] ?? null
  const mean = clean.reduce((sum, value) => sum + value, 0) / clean.length
  const min = Math.min(...clean)
  const max = Math.max(...clean)
  const variance = clean.reduce((sum, value) => sum + (value - mean) ** 2, 0) / clean.length
  const stdev = Math.sqrt(variance)

  return {
    latest,
    mean,
    min,
    max,
    stdev,
    zScore: latest !== null && stdev > 1e-12 ? (latest - mean) / stdev : null,
    count: clean.length,
  }
}

export function normalizeFormulaWeight(value: number | string) {
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return 0
  return Math.round(parsed * 10_000) / 10_000
}

export function normalizeFormulaLegs(legs: ListedOptionTimeseriesFormulaLeg[]) {
  const grouped = new Map<string, number>()

  for (const leg of legs) {
    const seriesId = String(leg.seriesId || '').trim()
    if (!seriesId) continue
    const nextWeight = normalizeFormulaWeight(leg.weight)
    if (Math.abs(nextWeight) < 1e-12) continue
    grouped.set(seriesId, normalizeFormulaWeight((grouped.get(seriesId) ?? 0) + nextWeight))
  }

  return Array.from(grouped.entries())
    .filter(([, weight]) => Math.abs(weight) > 1e-12)
    .map(([seriesId, weight]) => ({ seriesId, weight }))
}

export function buildFormulaSeries(
  config: ListedOptionTimeseriesFormulaConfig,
  seriesMap: Map<string, ListedOptionTimeseriesSeries>
): ListedOptionDerivedFormulaSeries | null {
  const legs = normalizeFormulaLegs(config.legs)
  if (legs.length < 2) return null

  const sourceSeries = legs
    .map((leg) => ({ leg, series: seriesMap.get(leg.seriesId) }))
    .filter(
      (entry): entry is { leg: ListedOptionTimeseriesFormulaLeg; series: ListedOptionTimeseriesSeries } =>
        Boolean(entry.series)
    )

  if (sourceSeries.length !== legs.length) {
    return null
  }

  const dates = Array.from(
    new Set(sourceSeries.flatMap((entry) => entry.series.points.map((point) => point.asOf)))
  ).sort()

  const points: ListedOptionTimeseriesPoint[] = dates.map((asOf) => {
    let hasNull = false
    let value = 0

    for (const entry of sourceSeries) {
      const point = entry.series.points.find((candidate) => candidate.asOf === asOf)
      if (!point || point.value === null) {
        hasNull = true
        break
      }
      value += point.value * entry.leg.weight
    }

    const scaledValue = hasNull ? null : config.scaleBy100 ? value * 100 : value
    return { asOf, value: scaledValue }
  })

  const expression = legs
    .map((leg) => `${leg.weight} * ${leg.seriesId}`)
    .join(' ')

  return {
    id: config.id,
    name: config.name,
    yaxis: config.yaxis,
    scaleBy100: config.scaleBy100,
    expression,
    nonNullCount: points.filter((point) => point.value !== null).length,
    points,
  }
}

export function mergeTimeseriesCollection(
  current: ListedOptionTimeseriesMultiResponse,
  incoming: ListedOptionTimeseriesMultiResponse
): ListedOptionTimeseriesMultiResponse {
  const mergedSeries = current.series.map((series) => {
    const incomingSeries = incoming.series.find((candidate) => candidate.id === series.id)
    if (!incomingSeries) return series

    const mergedPoints = [...incomingSeries.points, ...series.points].sort((a, b) =>
      a.asOf.localeCompare(b.asOf)
    )
    const dedupedPoints = mergedPoints.filter(
      (point, index) =>
        index === 0 || mergedPoints[index - 1]?.asOf !== point.asOf
    )

    return {
      ...series,
      points: dedupedPoints,
      stats: computeSeriesStats(dedupedPoints.map((point) => point.value)),
    }
  })

  return {
    startDate: [incoming.startDate, current.startDate].filter(Boolean).sort()[0] ?? null,
    endDate: [incoming.endDate, current.endDate].filter(Boolean).sort().at(-1) ?? null,
    asOfDate: [incoming.asOfDate, current.asOfDate].filter(Boolean).sort().at(-1) ?? null,
    warnings: current.warnings,
    series: mergedSeries,
  }
}

function shiftDate(dateKey: string, days: number) {
  const parsed = new Date(`${dateKey}T00:00:00Z`)
  if (Number.isNaN(parsed.getTime())) return dateKey
  parsed.setUTCDate(parsed.getUTCDate() + days)
  return parsed.toISOString().slice(0, 10)
}

export function getTimeseriesHistoricalWindow(params: {
  currentStartDate: string
  range: ListedOptionRange
  initialStartDate?: string
  initialEndDate?: string
}) {
  const endDate = shiftDate(params.currentStartDate, -1)

  if (params.initialStartDate && params.initialEndDate) {
    const spanDays = Math.max(
      1,
      Math.round(
        (Date.parse(`${params.initialEndDate}T00:00:00Z`) -
          Date.parse(`${params.initialStartDate}T00:00:00Z`)) /
          86_400_000
      )
    )
    return {
      startDate: shiftDate(endDate, -spanDays),
      endDate,
    }
  }

  const lookbackDays =
    params.range === '1M'
      ? 30
      : params.range === '3M'
        ? 92
        : params.range === '6M'
          ? 184
          : params.range === '1Y'
            ? 366
            : 730

  return {
    startDate: shiftDate(endDate, -lookbackDays),
    endDate,
  }
}

export function shouldPrefetchHistoricalTimeseries(params: {
  loadedStartDate: string | null
  viewportStartDate: string | null
  viewportEndDate: string | null
  hasMoreHistorical: boolean
  loadingHistorical: boolean
}) {
  if (
    !params.loadedStartDate ||
    !params.viewportStartDate ||
    !params.viewportEndDate ||
    !params.hasMoreHistorical ||
    params.loadingHistorical
  ) {
    return false
  }

  const loadedStart = Date.parse(`${params.loadedStartDate}T00:00:00Z`)
  const viewportStart = Date.parse(`${params.viewportStartDate}T00:00:00Z`)
  const viewportEnd = Date.parse(`${params.viewportEndDate}T00:00:00Z`)

  if (!Number.isFinite(loadedStart) || !Number.isFinite(viewportStart) || !Number.isFinite(viewportEnd)) {
    return false
  }

  const loadedSpan = Math.max(viewportEnd - loadedStart, 86_400_000)
  return viewportStart - loadedStart <= loadedSpan * 0.2
}

export function buildSearchOptionsFromSnapshot(
  snapshot: ListedOptionSnapshotResponse | null
): ListedOptionSearchOption[] {
  if (!snapshot) return []

  const options = new Map<string, ListedOptionSearchOption>()

  for (const row of snapshot.rows) {
    for (const contractGroup of snapshot.contractGroups) {
      const cellBucket = row.cells[contractGroup.id]
      if (!cellBucket) continue

      for (const cell of [cellBucket.call, cellBucket.put]) {
        if (!cell?.chartSeries) continue
        const id = getSeriesConfigKey(cell.chartSeries)
        const label = formatSeriesConfigLabel(cell.chartSeries)
        const aliases = [
          label,
          contractGroup.displayLabel,
          cell.explicitOptionSymbol ?? '',
          cell.chartSeries.rawSymbolFallback ?? '',
          cell.chartSeries.explicitContract ?? '',
          `${contractGroup.productRoot} ${row.rowLabel} ${sideLabel(cell.chartSeries.side)}`,
        ].filter(Boolean)

        const bucket =
          cell.chartSeries.selectorType === 'explicit_symbol'
            ? 'explicit'
            : cell.chartSeries.selectorType === 'delta'
              ? 'delta'
              : cell.chartSeries.selectorType === 'bps_offset'
                ? 'offset'
                : cell.chartSeries.contractReferenceMode === 'constant_maturity'
                  ? 'cm'
                  : 'explicit'

        options.set(id, {
          id,
          label,
          subtitle: `${contractGroup.displayLabel} | ${row.rowLabel}`,
          bucket,
          config: cell.chartSeries,
          aliases,
        })
      }
    }
  }

  return Array.from(options.values())
}

export function searchTimeseriesSeriesOptions(
  query: string,
  options: ListedOptionSearchOption[],
  limit = 12
) {
  const normalizedQuery = normalizeText(query)
  if (!normalizedQuery) {
    return options.slice(0, limit)
  }

  return options
    .map((option) => {
      const haystacks = [option.label, option.subtitle, ...option.aliases]
      const normalizedHaystacks = haystacks.map((value) => normalizeText(value))
      const score = normalizedHaystacks.reduce((best, candidate) => {
        if (!candidate) return best
        if (candidate === normalizedQuery) return Math.max(best, 1000)
        if (candidate.startsWith(normalizedQuery)) return Math.max(best, 750 - candidate.length)
        if (candidate.includes(normalizedQuery)) return Math.max(best, 500 - candidate.length)
        return best
      }, -1)

      return { option, score }
    })
    .filter((entry) => entry.score >= 0)
    .sort((a, b) => b.score - a.score || a.option.label.localeCompare(b.option.label))
    .slice(0, limit)
    .map((entry) => entry.option)
}

function pickBestSeriesMatch(query: string, options: ListedOptionSearchOption[]) {
  return searchTimeseriesSeriesOptions(query, options, 1)[0] ?? null
}

export function parseTimeseriesFormulaCommand(
  query: string,
  options: ListedOptionSearchOption[]
):
  | {
      formulaKind: 'spread' | 'fly'
      name: string
      description: string
      series: ListedOptionSeriesConfig[]
      legs: ListedOptionTimeseriesFormulaLeg[]
    }
  | null {
  const trimmed = query.trim()
  if (!trimmed) return null

  const spreadMatch = trimmed.match(/^(?:spread\s+)?(.+?)\s+(?:VS|\/)\s+(.+)$/i)
  if (spreadMatch) {
    const left = pickBestSeriesMatch(spreadMatch[1] ?? '', options)
    const right = pickBestSeriesMatch(spreadMatch[2] ?? '', options)
    if (!left || !right) return null
    return {
      formulaKind: 'spread',
      name: `${left.label} vs ${right.label}`,
      description: `${left.label} - ${right.label}`,
      series: [left.config, right.config],
      legs: [
        { seriesId: left.id, weight: 1 },
        { seriesId: right.id, weight: -1 },
      ],
    }
  }

  const flyMatch = trimmed.match(/^(?:fly\s+)?(.+?)\s*\/\s*(.+?)\s*\/\s*(.+)$/i)
  if (!flyMatch) return null

  const leg1 = pickBestSeriesMatch(flyMatch[1] ?? '', options)
  const leg2 = pickBestSeriesMatch(flyMatch[2] ?? '', options)
  const leg3 = pickBestSeriesMatch(flyMatch[3] ?? '', options)
  if (!leg1 || !leg2 || !leg3) return null

  return {
    formulaKind: 'fly',
    name: `${leg1.label} / ${leg2.label} / ${leg3.label} fly`,
    description: `${leg1.label} - 2 * ${leg2.label} + ${leg3.label}`,
    series: [leg1.config, leg2.config, leg3.config],
    legs: [
      { seriesId: leg1.id, weight: 1 },
      { seriesId: leg2.id, weight: -2 },
      { seriesId: leg3.id, weight: 1 },
    ],
  }
}
