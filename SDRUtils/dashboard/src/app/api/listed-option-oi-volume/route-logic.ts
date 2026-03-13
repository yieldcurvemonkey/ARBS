import type {
  ListedOptionContractReferenceMode,
  ListedOptionLabelNamespace,
  ListedOptionMetricField,
  ListedOptionRange,
  ListedOptionRowAxis,
  ListedOptionSeriesConfig,
} from '@/features/listed-option-oi-volume/types'

const METRIC_FIELDS: ListedOptionMetricField[] = [
  'open_interest',
  'volume',
  'open_interest_change',
  'volume_change',
]
const LABEL_NAMESPACES: ListedOptionLabelNamespace[] = ['BBG', 'Globex', 'Barchart']
const CONTRACT_VIEWS: ListedOptionContractReferenceMode[] = ['explicit', 'constant_maturity']
const ROW_AXES: ListedOptionRowAxis[] = ['strike', 'delta', 'bps_offset']
const RANGES: ListedOptionRange[] = ['1M', '3M', '6M', '1Y', 'ALL']

type ParseResult<T> =
  | { ok: true; value: T }
  | { ok: false; error: string }

export type SnapshotRouteParams = {
  requestedDate?: string
  field: ListedOptionMetricField
  periodBusinessDays: number
  labelNamespace: ListedOptionLabelNamespace
  contractView: ListedOptionContractReferenceMode
  rowAxis: ListedOptionRowAxis
  productFamily?: 'UST' | 'STIR'
  productRoots?: string[]
}

export type TimeseriesRouteParams = {
  series: ListedOptionSeriesConfig[]
  range: ListedOptionRange
  startDate?: string
  endDate?: string
  periodBusinessDays: number
}

function parsePositiveInt(value: string | null | undefined, fallback: number) {
  if (!value) return fallback
  const parsed = Number(value)
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null
}

function parseOptionalDate(value: string | null | undefined) {
  if (!value) return undefined
  const token = value.trim()
  if (!token) return undefined
  return /^\d{4}-\d{2}-\d{2}$/.test(token) ? token : null
}

export function parseSnapshotRouteParams(searchParams: URLSearchParams): ParseResult<SnapshotRouteParams> {
  const field = (searchParams.get('field') ?? 'open_interest_change') as ListedOptionMetricField
  if (!METRIC_FIELDS.includes(field)) {
    return { ok: false, error: `Unsupported field: ${field}` }
  }

  const labelNamespace = (searchParams.get('labelNamespace') ?? 'Globex') as ListedOptionLabelNamespace
  if (!LABEL_NAMESPACES.includes(labelNamespace)) {
    return { ok: false, error: `Unsupported label namespace: ${labelNamespace}` }
  }

  const contractView = (searchParams.get('contractView') ?? 'explicit') as ListedOptionContractReferenceMode
  if (!CONTRACT_VIEWS.includes(contractView)) {
    return { ok: false, error: `Unsupported contract view: ${contractView}` }
  }

  const rowAxis = (searchParams.get('rowAxis') ?? 'strike') as ListedOptionRowAxis
  if (!ROW_AXES.includes(rowAxis)) {
    return { ok: false, error: `Unsupported row axis: ${rowAxis}` }
  }

  const requestedDate = parseOptionalDate(searchParams.get('date'))
  if (requestedDate === null) {
    return { ok: false, error: 'Date must be formatted as YYYY-MM-DD.' }
  }

  const periodBusinessDays = parsePositiveInt(searchParams.get('periodBusinessDays'), 1)
  if (periodBusinessDays === null) {
    return { ok: false, error: 'periodBusinessDays must be a positive integer.' }
  }

  const productFamily = searchParams.get('productFamily')
  if (productFamily && productFamily !== 'UST' && productFamily !== 'STIR') {
    return { ok: false, error: `Unsupported product family: ${productFamily}` }
  }

  const productRoots = (searchParams.get('productRoots') ?? '')
    .split(',')
    .map((value) => value.trim().toUpperCase())
    .filter(Boolean)

  return {
    ok: true,
    value: {
      requestedDate,
      field,
      periodBusinessDays,
      labelNamespace,
      contractView,
      rowAxis,
      productFamily: productFamily ? (productFamily as 'UST' | 'STIR') : undefined,
      productRoots: productRoots.length ? productRoots : undefined,
    },
  }
}

function isSeriesConfig(value: unknown): value is ListedOptionSeriesConfig {
  if (!value || typeof value !== 'object') return false
  const candidate = value as Record<string, unknown>
  return (
    typeof candidate.metricField === 'string' &&
    typeof candidate.productRoot === 'string' &&
    typeof candidate.contractReferenceMode === 'string' &&
    typeof candidate.selectorType === 'string' &&
    typeof candidate.side === 'string'
  )
}

export function parseTimeseriesRouteParams(body: unknown): ParseResult<TimeseriesRouteParams> {
  const payload = body && typeof body === 'object' ? (body as Record<string, unknown>) : {}
  const range = (payload.range ?? '6M') as ListedOptionRange
  if (!RANGES.includes(range)) {
    return { ok: false, error: `Unsupported range: ${range}` }
  }

  const startDate = parseOptionalDate(
    typeof payload.startDate === 'string' ? payload.startDate : undefined
  )
  if (startDate === null) {
    return { ok: false, error: 'startDate must be formatted as YYYY-MM-DD.' }
  }

  const endDate = parseOptionalDate(
    typeof payload.endDate === 'string' ? payload.endDate : undefined
  )
  if (endDate === null) {
    return { ok: false, error: 'endDate must be formatted as YYYY-MM-DD.' }
  }

  if (startDate && endDate && startDate > endDate) {
    return { ok: false, error: 'startDate must be on or before endDate.' }
  }

  const periodBusinessDays = parsePositiveInt(
    typeof payload.periodBusinessDays === 'number' || typeof payload.periodBusinessDays === 'string'
      ? String(payload.periodBusinessDays)
      : undefined,
    1
  )
  if (periodBusinessDays === null) {
    return { ok: false, error: 'periodBusinessDays must be a positive integer.' }
  }

  const rawSeries = Array.isArray(payload.series) ? payload.series : []
  const series = rawSeries.filter(isSeriesConfig)

  return {
    ok: true,
    value: {
      series,
      range,
      startDate: startDate ?? undefined,
      endDate: endDate ?? undefined,
      periodBusinessDays,
    },
  }
}
