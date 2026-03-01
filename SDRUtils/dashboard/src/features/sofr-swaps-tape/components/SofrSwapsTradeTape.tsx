// ABOUTME: USD swaps trade tape with parity modules and manual linking.
"use client"

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { usePathname, useRouter, useSearchParams } from 'next/navigation'
import { AlertTriangle, ChevronDown, ChevronRight, RefreshCw } from 'lucide-react'
import { FilterMatchMode, FilterOperator } from 'primereact/api'
import { DataTable, DataTableFilterMeta, DataTableSortEvent } from 'primereact/datatable'
import { Column } from 'primereact/column'
import type { VirtualScrollerLazyEvent } from 'primereact/virtualscroller'
import { Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import 'primereact/resources/themes/lara-dark-indigo/theme.css'
import 'primereact/resources/primereact.min.css'
import 'primeicons/primeicons.css'
import {
  COLUMN_DEFS,
  DEFAULT_FLOW_TOLERANCE,
  DEFAULT_FORWARD_BOUNDARY,
  DEFAULT_TENOR_BOUNDARY,
  METRIC_OPTIONS,
  POLL_INTERVAL_MS,
  ROW_ESTIMATE_PX,
  TIMESERIES_METRICS,
  TIMESERIES_VIEWS
} from '../constants'
import type {
  FlowHistoryDay,
  FlowHistoryResponse,
  ManualSwapLinkValidationItem,
  SofrSwapTapeLeg,
  SofrSwapTapeResponse,
  SofrSwapTapeRow,
  TimeseriesMetricKey,
  TimeseriesViewKey
} from '../types'
import { buildFlowGridRows, flattenFlowHistory, formatUsdMillions, getLatestFlowDay } from './flowHistory.utils'
import { buildSequenceClusters } from './sequence.utils'

type TimeseriesPoint = { label: string; value: number; open?: number; high?: number; low?: number; close?: number }

const EMPTY = '--'
const ACTIVE_ACTIONS = new Set(['NEWT-TRAD', 'MODI-TRAD', 'CORR-TRAD'])
const PACKAGE_TONES: Record<string, string> = {
  OUTRIGHT: '!bg-gray-800/50',
  CURVE: '!bg-blue-900/30',
  FLY: '!bg-cyan-900/30',
  MMS: '!bg-emerald-900/30',
  MATCHED_MATURITY: '!bg-amber-900/30',
  INVOICE: '!bg-lime-900/30',
  UNKNOWN: '!bg-slate-800/40'
}
const ACTION_TONES: Record<string, string> = {
  'MODI-TRAD': 'ring-1 ring-sky-500/40',
  'CORR-TRAD': 'ring-1 ring-amber-500/40'
}
const DEFAULT_TEXT_MATCH_MODE = FilterMatchMode.CONTAINS
const DEFAULT_NUMERIC_MATCH_MODE = FilterMatchMode.EQUALS
const TIME_FILTER_MATCH_MODE_OPTIONS = [
  { label: 'Contains', value: FilterMatchMode.CONTAINS },
  { label: 'Equals', value: FilterMatchMode.EQUALS },
  { label: 'Not equals', value: FilterMatchMode.NOT_EQUALS },
  { label: 'Greater than', value: FilterMatchMode.GREATER_THAN },
  { label: 'Greater than or equal', value: FilterMatchMode.GREATER_THAN_OR_EQUAL_TO },
  { label: 'Less than', value: FilterMatchMode.LESS_THAN },
  { label: 'Less than or equal', value: FilterMatchMode.LESS_THAN_OR_EQUAL_TO }
]
const FILTER_FIELDS = ['action', 'package_type', 'time', 'platform', 'notional', 'risk', 'label'] as const
const COLUMN_FILTER_QUERY_KEY = 'columnFilters'
const COLUMN_FILTER_OPERATOR_QUERY_KEY = 'columnFilterOp'
const NUMERIC_FILTER_FIELDS = new Set(['notional', 'risk'])

type FilterConstraint = {
  value?: unknown
  matchMode?: string
}

type ColumnFilterMeta = {
  operator?: string
  constraints?: FilterConstraint[]
  value?: unknown
  matchMode?: string
}

type ColumnFilterPayload = Record<string, ColumnFilterMeta>

const INITIAL_FILTERS: DataTableFilterMeta = {
  action: {
    operator: FilterOperator.AND,
    constraints: [{ value: null, matchMode: DEFAULT_TEXT_MATCH_MODE }]
  },
  package_type: {
    operator: FilterOperator.AND,
    constraints: [{ value: null, matchMode: DEFAULT_TEXT_MATCH_MODE }]
  },
  time: {
    operator: FilterOperator.AND,
    constraints: [{ value: null, matchMode: DEFAULT_TEXT_MATCH_MODE }]
  },
  platform: {
    operator: FilterOperator.AND,
    constraints: [{ value: null, matchMode: DEFAULT_TEXT_MATCH_MODE }]
  },
  notional: {
    operator: FilterOperator.AND,
    constraints: [{ value: null, matchMode: DEFAULT_NUMERIC_MATCH_MODE }]
  },
  risk: {
    operator: FilterOperator.AND,
    constraints: [{ value: null, matchMode: DEFAULT_NUMERIC_MATCH_MODE }]
  },
  label: {
    operator: FilterOperator.AND,
    constraints: [{ value: null, matchMode: DEFAULT_TEXT_MATCH_MODE }]
  }
}

function toNumber(value: unknown) {
  if (typeof value === 'number') return Number.isFinite(value) ? value : 0
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : 0
}

function fmt(value: unknown, digits = 0) {
  const n = toNumber(value)
  return n.toLocaleString('en-US', { maximumFractionDigits: digits, minimumFractionDigits: digits })
}

function fmtTs(value?: string | null) {
  if (!value) return EMPTY
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return value
  return d.toLocaleString('en-US', { timeZone: 'America/New_York', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false })
}

function formatExecutionWindow(start: string, end: string) {
  if (!start) return EMPTY
  const startDate = new Date(start)
  const endDate = end ? new Date(end) : startDate
  const startStr = `${startDate.toLocaleDateString('en-US')} ${startDate.toLocaleTimeString('en-US', {
    hour12: false,
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit'
  })}`
  const endStr = `${endDate.toLocaleTimeString('en-US', {
    hour12: false,
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit'
  })}`
  if (startDate.getTime() === endDate.getTime()) return startStr
  return `${startStr} / ${endStr}`
}

function parseStrictDurationToken(label?: string | null): string | null {
  if (!label) return null
  const normalized = label.trim().toUpperCase()
  return /^\d+(?:\.\d+)?[DWMY]$/.test(normalized) ? normalized : null
}

function toStrictYearToken(value: unknown): string | null {
  const numeric = Number(value)
  if (!Number.isFinite(numeric)) return null
  const normalized = Math.max(0, numeric)
  const rounded = Math.round(normalized * 1000) / 1000
  if (!Number.isFinite(rounded)) return null
  const scalar = Number.isInteger(rounded) ? String(rounded) : String(rounded)
  return `${scalar}Y`
}

function packageTone(packageType?: string | null) {
  if (!packageType) return PACKAGE_TONES.UNKNOWN
  const normalized = packageType.toUpperCase().replace(/[\s-]+/g, '_')
  return PACKAGE_TONES[normalized] || PACKAGE_TONES.UNKNOWN
}

function actionTone(action?: string | null) {
  if (!action) return ''
  return ACTION_TONES[action.toUpperCase()] || ''
}

function isEmptyFilterValue(value: unknown) {
  if (value === null || value === undefined) return true
  if (typeof value === 'string' && value.trim() === '') return true
  if (Array.isArray(value) && value.length === 0) return true
  return false
}

function parseFilterNumber(value: any): number | null {
  if (value === null || value === undefined || value === '') return null
  if (typeof value === 'number') return Number.isNaN(value) ? null : value
  const normalized = String(value).replace(/,/g, '').trim()
  if (!normalized) return null
  const parsed = Number(normalized)
  return Number.isNaN(parsed) ? null : parsed
}

function normalizeFilterConstraintValue(field: string, value: any) {
  if (!NUMERIC_FILTER_FIELDS.has(field)) return value
  if (Array.isArray(value)) {
    return value.map((entry) => {
      const numericValue = parseFilterNumber(entry)
      return numericValue !== null ? numericValue : entry
    })
  }
  const numericValue = parseFilterNumber(value)
  return numericValue !== null ? numericValue : value
}

function parseColumnFilterOperator(value: string | null) {
  return value === FilterOperator.OR ? FilterOperator.OR : FilterOperator.AND
}

function buildColumnFilterPayload(filters: DataTableFilterMeta) {
  const payload: ColumnFilterPayload = {}
  FILTER_FIELDS.forEach((field) => {
    const filterMeta = (filters || {})[field]
    if (!filterMeta) return
    const filterMetaAny = filterMeta as any
    const constraints = Array.isArray(filterMetaAny.constraints)
      ? filterMetaAny.constraints
      : [
          {
            value: filterMetaAny.value,
            matchMode: filterMetaAny.matchMode
          }
        ]
    const activeConstraints = constraints
      .map((constraint: any) => ({
        value: constraint?.value,
        matchMode: constraint?.matchMode
      }))
      .filter((constraint: any) => !isEmptyFilterValue(constraint.value))
    if (!activeConstraints.length) return
    payload[field] = {
      operator: filterMetaAny.operator === FilterOperator.OR ? FilterOperator.OR : FilterOperator.AND,
      constraints: activeConstraints
    }
  })
  return payload
}

function parseColumnFilterPayload(rawValue: string | null): DataTableFilterMeta {
  if (!rawValue) return INITIAL_FILTERS
  let parsed: ColumnFilterPayload | null = null
  try {
    parsed = JSON.parse(rawValue) as ColumnFilterPayload
  } catch {
    return INITIAL_FILTERS
  }
  if (!parsed || typeof parsed !== 'object') return INITIAL_FILTERS

  const nextFilters: DataTableFilterMeta = { ...INITIAL_FILTERS }
  FILTER_FIELDS.forEach((field) => {
    const rawFilter = parsed?.[field]
    if (!rawFilter) return
    const constraints = Array.isArray(rawFilter.constraints)
      ? rawFilter.constraints
      : [
          {
            value: (rawFilter as any).value,
            matchMode: (rawFilter as any).matchMode
          }
        ]
    const normalizedConstraints = constraints
      .map((constraint: any) => ({
        value: normalizeFilterConstraintValue(field, constraint?.value),
        matchMode:
          typeof constraint?.matchMode === 'string'
            ? constraint.matchMode
            : (INITIAL_FILTERS as any)[field]?.constraints?.[0]?.matchMode
      }))
      .filter((constraint: any) => !isEmptyFilterValue(constraint.value))
    if (!normalizedConstraints.length) return
    nextFilters[field] = {
      operator: rawFilter.operator === FilterOperator.OR ? FilterOperator.OR : FilterOperator.AND,
      constraints: normalizedConstraints
    }
  })
  return nextFilters
}

function hasActiveConstraints(filterMeta: any): boolean {
  if (!filterMeta) return false
  const constraints = Array.isArray(filterMeta.constraints)
    ? filterMeta.constraints
    : [
        {
          value: filterMeta.value,
          matchMode: filterMeta.matchMode
        }
      ]
  return constraints.some((constraint: any) => !isEmptyFilterValue(constraint?.value))
}

function formatFilterValue(value: any): string {
  if (Array.isArray(value)) return value.map(String).join(', ')
  return String(value)
}

function formatMatchModeLabel(mode?: string): string {
  switch (mode) {
    case FilterMatchMode.STARTS_WITH:
      return 'starts with'
    case FilterMatchMode.CONTAINS:
      return 'contains'
    case FilterMatchMode.NOT_CONTAINS:
      return 'not contains'
    case FilterMatchMode.ENDS_WITH:
      return 'ends with'
    case FilterMatchMode.EQUALS:
      return 'equals'
    case FilterMatchMode.NOT_EQUALS:
      return 'not equals'
    case FilterMatchMode.LESS_THAN:
      return '<'
    case FilterMatchMode.LESS_THAN_OR_EQUAL_TO:
      return '<='
    case FilterMatchMode.GREATER_THAN:
      return '>'
    case FilterMatchMode.GREATER_THAN_OR_EQUAL_TO:
      return '>='
    case FilterMatchMode.IN:
      return 'in'
    default:
      return 'contains'
  }
}

function buildTimeseriesData(rows: SofrSwapTapeRow[], metric: TimeseriesMetricKey, view: TimeseriesViewKey): TimeseriesPoint[] {
  const points = rows
    .map((row) => {
      const ts = Date.parse(row.execution_start)
      if (!Number.isFinite(ts)) return null
      const notional = Math.abs(toNumber(row.total_notional))
      const risk = Math.abs(toNumber(row.total_risk))
      const fixed = toNumber(row.weighted_fixed_rate)
      const value = metric === 'notional' ? notional : metric === 'risk' ? risk : metric === 'fixed_rate' ? fixed : 1
      return { ts, label: new Date(ts).toISOString().slice(0, 16).replace('T', ' '), value }
    })
    .filter((v): v is NonNullable<typeof v> => Boolean(v))
    .sort((a, b) => a.ts - b.ts)

  if (view === 'INTRADAY') return points

  const grouped = new Map<string, number[]>()
  points.forEach((point) => {
    const day = point.label.slice(0, 10)
    if (!grouped.has(day)) grouped.set(day, [])
    grouped.get(day)?.push(point.value)
  })

  return Array.from(grouped.entries())
    .map(([day, values]) => {
      const total = values.reduce((acc, v) => acc + v, 0)
      const open = values[0] || 0
      const close = values[values.length - 1] || 0
      const high = values.length ? Math.max(...values) : 0
      const low = values.length ? Math.min(...values) : 0
      return {
        label: day,
        value: metric === 'fixed_rate' ? close : total,
        open,
        high,
        low,
        close
      }
    })
    .sort((a, b) => a.label.localeCompare(b.label))
}

export default function SofrSwapsTradeTape() {
  const router = useRouter()
  const pathname = usePathname()
  const searchParams = useSearchParams()
  const [rows, setRows] = useState<SofrSwapTapeRow[]>([])
  const [loading, setLoading] = useState(false)
  const [loadingMore, setLoadingMore] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [hasMore, setHasMore] = useState(false)
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const [filter, setFilter] = useState(searchParams.get('filter') || '')
  const [metricMode, setMetricMode] = useState<'notional' | 'risk'>(
    searchParams.get('metric') === 'risk' ? 'risk' : 'notional'
  )
  const [filters, setFilters] = useState<DataTableFilterMeta>(() =>
    parseColumnFilterPayload(searchParams.get(COLUMN_FILTER_QUERY_KEY))
  )
  const [columnFilterOperator, setColumnFilterOperator] = useState(() =>
    parseColumnFilterOperator(searchParams.get(COLUMN_FILTER_OPERATOR_QUERY_KEY))
  )
  const [sortField, setSortField] = useState<string>('execution_start')
  const [sortOrder, setSortOrder] = useState<1 | -1 | 0>(-1)
  const [selectedRows, setSelectedRows] = useState<SofrSwapTapeRow[]>([])
  const [expandedRows, setExpandedRows] = useState<Record<string, boolean>>({})
  const [manualUser, setManualUser] = useState('analyst')
  const [manualComment, setManualComment] = useState('')
  const [manualReason, setManualReason] = useState('')
  const [manualPackageType, setManualPackageType] = useState('')
  const [manualValidation, setManualValidation] = useState<ManualSwapLinkValidationItem[]>([])
  const [manualError, setManualError] = useState<string | null>(null)
  const [manualBusy, setManualBusy] = useState(false)
  const [timeseriesRows, setTimeseriesRows] = useState<SofrSwapTapeRow[]>([])
  const [timeseriesMetric, setTimeseriesMetric] = useState<TimeseriesMetricKey>('notional')
  const [timeseriesView, setTimeseriesView] = useState<TimeseriesViewKey>('INTRADAY')
  const [flowDays, setFlowDays] = useState<FlowHistoryDay[]>([])
  const [flowStart, setFlowStart] = useState(new Date(Date.now() - 30 * 86_400_000).toISOString().slice(0, 10))
  const [flowEnd, setFlowEnd] = useState(new Date().toISOString().slice(0, 10))
  const [forwardBoundary, setForwardBoundary] = useState(DEFAULT_FORWARD_BOUNDARY)
  const [tenorBoundary, setTenorBoundary] = useState(DEFAULT_TENOR_BOUNDARY)
  const [tolerance, setTolerance] = useState(DEFAULT_FLOW_TOLERANCE)
  const [flowPlatform, setFlowPlatform] = useState('combined')
  const [sequenceGapSeconds, setSequenceGapSeconds] = useState(180)
  const latestExecutionStartRef = useRef<string | null>(null)
  const fetchInFlight = useRef(false)
  const tapeContainerRef = useRef<HTMLDivElement | null>(null)

  const selectedTradeIds = useMemo(() => Array.from(new Set(selectedRows.flatMap((row) => row.legs_json?.map((leg) => leg.trade_id || '') || []).filter(Boolean))), [selectedRows])
  const selectedLinkId = useMemo(() => {
    const ids = Array.from(new Set(selectedRows.map((row) => row.manual_link_id || '').filter(Boolean)))
    return ids.length === 1 ? ids[0] : null
  }, [selectedRows])
  const selectedPackageIdSet = useMemo(() => new Set(selectedRows.map((row) => row.package_id)), [selectedRows])
  const activeSeriesKey = useMemo(() => {
    const row = selectedRows[0] ?? rows[0]
    if (!row) return null
    const forwardToken =
      toStrictYearToken(row.forward_start_years) ||
      parseStrictDurationToken(row.forward_label)
    const tenorToken =
      toStrictYearToken(row.tenor_years) ||
      parseStrictDurationToken(row.tenor_label)
    if (!forwardToken || !tenorToken) return null
    return `${forwardToken}x${tenorToken}`
  }, [rows, selectedRows])
  const columnFilterPayload = useMemo(() => buildColumnFilterPayload(filters), [filters])
  const hasActiveColumnFilters = useMemo(
    () => Object.keys(columnFilterPayload).length > 0,
    [columnFilterPayload]
  )
  const columnFilterPayloadKey = useMemo(
    () => JSON.stringify(columnFilterPayload),
    [columnFilterPayload]
  )

  const fetchTape = useCallback(async (opts?: { cursor?: string; since?: string; replace?: boolean; prepend?: boolean }) => {
    if (fetchInFlight.current) return
    fetchInFlight.current = true
    const { cursor, since, replace = false, prepend = false } = opts || {}
    if (cursor) setLoadingMore(true)
    else setLoading(true)
    try {
      const params = new URLSearchParams({ limit: '200' })
      if (filter) params.set('filter', filter)
      if (hasActiveColumnFilters) {
        params.set(COLUMN_FILTER_QUERY_KEY, columnFilterPayloadKey)
      }
      if (columnFilterOperator === FilterOperator.OR) {
        params.set(COLUMN_FILTER_OPERATOR_QUERY_KEY, columnFilterOperator)
      }
      if (cursor) params.set('cursor', cursor)
      if (since) params.set('since', since)
      const res = await fetch(`/api/usd-swaps-tape?${params.toString()}`)
      const data = (await res.json()) as SofrSwapTapeResponse
      if (!res.ok) throw new Error((data as any)?.error || `Tape fetch failed (${res.status})`)
      setRows((prev) => {
        if (replace) return data.rows || []
        const merged = prepend ? [...(data.rows || []), ...prev] : [...prev, ...(data.rows || [])]
        const seen = new Set<string>()
        return merged.filter((row) => {
          if (seen.has(row.package_id)) return false
          seen.add(row.package_id)
          return true
        })
      })
      setHasMore(Boolean(data.hasMore))
      setNextCursor(data.nextCursor || null)
      latestExecutionStartRef.current = data.latestExecutionStart || latestExecutionStartRef.current
      setError(null)
    } catch (e: any) {
      setError(e?.message || 'Failed to fetch tape')
    } finally {
      setLoading(false)
      setLoadingMore(false)
      fetchInFlight.current = false
    }
  }, [columnFilterOperator, columnFilterPayloadKey, filter, hasActiveColumnFilters])

  const syncUrl = useCallback(() => {
    const params = new URLSearchParams(searchParams.toString())
    if (filter) params.set('filter', filter)
    else params.delete('filter')
    params.set('metric', metricMode)
    if (hasActiveColumnFilters) params.set(COLUMN_FILTER_QUERY_KEY, columnFilterPayloadKey)
    else params.delete(COLUMN_FILTER_QUERY_KEY)
    if (columnFilterOperator === FilterOperator.OR) {
      params.set(COLUMN_FILTER_OPERATOR_QUERY_KEY, columnFilterOperator)
    } else {
      params.delete(COLUMN_FILTER_OPERATOR_QUERY_KEY)
    }
    const query = params.toString()
    router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false })
  }, [
    columnFilterOperator,
    columnFilterPayloadKey,
    filter,
    hasActiveColumnFilters,
    metricMode,
    pathname,
    router,
    searchParams
  ])

  const callManualApi = useCallback(async (method: 'POST' | 'PATCH' | 'DELETE', linkId?: string, validateOnly = false) => {
    setManualBusy(true)
    setManualError(null)
    try {
      const url = linkId ? `/api/usd-swap/links/${linkId}` : '/api/usd-swap/links'
      const body =
        method === 'POST'
          ? { trade_ids: selectedTradeIds, package_type: manualPackageType || null, comment: manualComment || null, link_reason: manualReason || null, user: manualUser, validate_only: validateOnly }
          : method === 'PATCH'
            ? { add_trades: selectedTradeIds, package_type: manualPackageType || undefined, comment: manualComment || undefined, link_reason: manualReason || undefined, user: manualUser }
            : { reason: manualReason || null, user: manualUser }
      const res = await fetch(url, { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
      const data = await res.json()
      if (!res.ok) throw new Error(data?.error || `${method} failed (${res.status})`)
      setManualValidation(data.validation || [])
      if (!validateOnly) await fetchTape({ replace: true })
    } catch (e: any) {
      setManualError(e?.message || 'Manual link request failed')
    } finally {
      setManualBusy(false)
    }
  }, [fetchTape, manualComment, manualPackageType, manualReason, manualUser, selectedTradeIds])

  const fetchTimeseries = useCallback(async () => {
    if (!activeSeriesKey) {
      setTimeseriesRows([])
      return
    }
    const params = new URLSearchParams({ seriesKey: activeSeriesKey })
    const row = selectedRows[0]
    if (row?.package_type) params.set('packageType', row.package_type)
    const res = await fetch(`/api/usd-swaps-tape/timeseries?${params.toString()}`)
    const data = await res.json()
    if (!res.ok) throw new Error(data?.error || `Timeseries fetch failed (${res.status})`)
    setTimeseriesRows(data.rows || [])
  }, [activeSeriesKey, selectedRows])

  const fetchFlow = useCallback(async () => {
    const params = new URLSearchParams({
      start: flowStart,
      end: flowEnd,
      forwardBoundary: String(forwardBoundary),
      tenorBoundary: String(tenorBoundary),
      tolerance: String(tolerance),
      platform: flowPlatform
    })
    const res = await fetch(`/api/usd-swaps-tape/flow-history?${params.toString()}`)
    const data = (await res.json()) as FlowHistoryResponse
    if (!res.ok) throw new Error((data as any)?.error || `Flow fetch failed (${res.status})`)
    setFlowDays(data.days || [])
  }, [flowEnd, flowPlatform, flowStart, forwardBoundary, tenorBoundary, tolerance])

  const shouldAutoPrepend = useCallback(() => {
    const root = tapeContainerRef.current
    if (!root) return true
    const scroller = root.querySelector('.p-datatable-wrapper') as HTMLElement | null
    if (!scroller) return true
    return scroller.scrollTop <= ROW_ESTIMATE_PX * 2
  }, [])

  useEffect(() => {
    syncUrl()
  }, [syncUrl])

  useEffect(() => {
    fetchTape({ replace: true })
  }, [fetchTape])

  useEffect(() => {
    const timer = setInterval(() => {
      if (!latestExecutionStartRef.current) return
      if (!shouldAutoPrepend()) return
      fetchTape({ since: latestExecutionStartRef.current, prepend: true })
    }, POLL_INTERVAL_MS)
    return () => clearInterval(timer)
  }, [fetchTape, shouldAutoPrepend])

  useEffect(() => {
    fetchTimeseries().catch((err) => setError(err.message))
  }, [fetchTimeseries])

  useEffect(() => {
    fetchFlow().catch((err) => setError(err.message))
  }, [fetchFlow])

  const latestFlowDay = useMemo(() => getLatestFlowDay(flowDays), [flowDays])
  const flowGridRows = useMemo(() => buildFlowGridRows(latestFlowDay), [latestFlowDay])
  const flowSeries = useMemo(() => flattenFlowHistory(flowDays), [flowDays])
  const sequenceClusters = useMemo(() => buildSequenceClusters(rows, sequenceGapSeconds), [rows, sequenceGapSeconds])
  const timeseriesData = useMemo(() => buildTimeseriesData(timeseriesRows, timeseriesMetric, timeseriesView), [timeseriesRows, timeseriesMetric, timeseriesView])
  const metricLabel = metricMode === 'risk' ? 'Risk' : 'Notional'
  const metricField = metricMode === 'risk' ? 'total_risk' : 'total_notional'
  const metricFilterField = metricMode === 'risk' ? 'risk' : 'notional'
  const metricColumnKey = metricMode === 'risk' ? 'metric-risk' : 'metric-notional'

  const rowClassName = (row: SofrSwapTapeRow) => {
    const action = (row.event_action || row.legs_json?.[0]?.event_action || '').toUpperCase()
    const isActive = action ? ACTIVE_ACTIONS.has(action) : false
    const isSelected = selectedPackageIdSet.has(row.package_id)
    const isManualLinked = !!row.manual_link_id || !!row.manual_package_id
    const tone = isActive ? packageTone(row.package_type) : '!bg-red-900/70 !text-red-100'
    return [
      'h-10 text-sm !text-gray-200 transition-[filter,box-shadow] hover:brightness-110 hover:shadow-[inset_0_0_0_1px_rgba(148,163,184,0.5)]',
      tone,
      actionTone(action),
      isManualLinked ? 'manual-linked-row' : '',
      isSelected ? 'selected-share-row' : ''
    ].join(' ').trim()
  }

  const toggleRowExpansion = useCallback((row: SofrSwapTapeRow) => {
    if (!row.legs_json || row.legs_json.length === 0) return
    setExpandedRows((previous) => {
      const next = { ...previous }
      if (next[row.package_id]) delete next[row.package_id]
      else next[row.package_id] = true
      return next
    })
  }, [])

  const expanderBody = (row: SofrSwapTapeRow) => {
    const canExpand = (row.legs_json || []).length > 0
    if (!canExpand) return <span className="inline-flex h-6 w-6" />
    const isExpanded = !!expandedRows[row.package_id]
    return (
      <button
        type="button"
        onClick={(event) => {
          event.stopPropagation()
          toggleRowExpansion(row)
        }}
        className="inline-flex h-6 w-6 items-center justify-center rounded border border-gray-700 text-gray-300 hover:border-gray-500 hover:text-gray-100"
        aria-label={isExpanded ? 'Collapse legs' : 'Expand legs'}
      >
        {isExpanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
      </button>
    )
  }

  const buildFilterSummary = useCallback((filterField: string) => {
    const filterMeta = ((filters || {})[filterField] as any) || null
    if (!hasActiveConstraints(filterMeta)) return null
    const constraints = Array.isArray(filterMeta?.constraints)
      ? filterMeta.constraints
      : [
          {
            value: filterMeta?.value,
            matchMode: filterMeta?.matchMode
          }
        ]
    const activeConstraints = constraints.filter(
      (constraint: any) => !isEmptyFilterValue(constraint?.value)
    )
    if (!activeConstraints.length) return null
    const operatorLabel =
      (filterMeta?.operator || FilterOperator.AND) === FilterOperator.OR
        ? 'OR'
        : 'AND'
    return activeConstraints
      .map((constraint: any) => {
        const modeLabel = formatMatchModeLabel(constraint.matchMode)
        const valueLabel = formatFilterValue(constraint.value)
        return `${modeLabel} ${valueLabel}`
      })
      .join(` ${operatorLabel} `)
  }, [filters])

  const renderColumnHeader = useCallback((label: string, filterField?: string) => {
    const summary = filterField ? buildFilterSummary(filterField) : null
    return (
      <div className="flex flex-col gap-0.5">
        <span className="text-[11px] uppercase tracking-wide text-gray-400">
          {label}
        </span>
        {summary ? (
          <span className="truncate text-[10px] text-gray-500">{summary}</span>
        ) : null}
      </div>
    )
  }, [buildFilterSummary])

  const actionBody = (row: SofrSwapTapeRow) => (
    <span className="font-mono text-xs text-gray-100">{row.event_action || row.legs_json?.[0]?.event_action || EMPTY}</span>
  )

  const packageBody = (row: SofrSwapTapeRow) => (
    <div className="flex items-center gap-2">
      <span className="inline-flex items-center gap-2 rounded-full border border-gray-500/40 bg-gray-700 px-2 py-1 text-[11px] font-semibold text-gray-100">
        {row.package_type || 'N/A'}
        {row.package_indicator ? <AlertTriangle className="h-3 w-3 text-amber-300" /> : null}
      </span>
      {(row.manual_link_id || row.manual_package_id) ? (
        <span className="inline-flex items-center gap-1 rounded-full border border-amber-500/50 bg-amber-500/10 px-2 py-0.5 text-[10px] uppercase tracking-wide text-amber-200">
          Manual
          {row.manual_package_id ? <span className="text-amber-100/80">{row.manual_package_id}</span> : null}
        </span>
      ) : null}
    </div>
  )

  const timeBody = (row: SofrSwapTapeRow) => (
    <span className="text-xs text-gray-300">{formatExecutionWindow(row.execution_start, row.execution_end)}</span>
  )

  const platformBody = (row: SofrSwapTapeRow) => (
    <span className="text-xs text-gray-300 truncate">{row.platform_identifier || EMPTY}</span>
  )

  const metricBody = (row: SofrSwapTapeRow) => (
    <span className="font-mono text-xs text-gray-200">
      {fmt(metricMode === 'notional' ? Math.abs(toNumber(row.total_notional)) : Math.abs(toNumber(row.total_risk)))}
    </span>
  )

  const labelBody = (row: SofrSwapTapeRow) => (
    <div className="flex items-center gap-2">
      <span className="font-mono text-xs text-gray-200">{`${row.forward_label || 'spot'} x ${row.tenor_label || EMPTY}`}</span>
      {row.manual_package_id ? <span className="rounded bg-emerald-900/70 px-1 text-[10px] text-emerald-100">{row.manual_package_id}</span> : null}
    </div>
  )

  const rowExpansionTemplate = (rowData: SofrSwapTapeRow) => (
    <div className="rounded-xl border border-slate-800/80 bg-slate-950/70 px-3 py-2">
      <table className="w-full text-xs">
        <thead>
          <tr className="text-[10px] uppercase tracking-wide text-slate-400">
            <th className="px-1 py-1 text-left">trade_id</th>
            <th className="px-1 py-1 text-left">execution_timestamp</th>
            <th className="px-1 py-1 text-left">tenor_label</th>
            <th className="px-1 py-1 text-left">forward_label</th>
            <th className="px-1 py-1 text-right">notional</th>
            <th className="px-1 py-1 text-right">risk</th>
            <th className="px-1 py-1 text-right">fixed_rate</th>
            <th className="px-1 py-1 text-left">flags</th>
          </tr>
        </thead>
        <tbody>
          {(rowData.legs_json || []).map((leg: SofrSwapTapeLeg, idx) => (
            <tr key={`${leg.trade_id || idx}`} className="border-t border-slate-800/90 text-slate-200">
              <td className="px-1 py-1">{leg.trade_id || EMPTY}</td>
              <td className="px-1 py-1">{fmtTs(leg.execution_timestamp)}</td>
              <td className="px-1 py-1">{leg.tenor_label || EMPTY}</td>
              <td className="px-1 py-1">{leg.forward_label || EMPTY}</td>
              <td className="px-1 py-1 text-right">{fmt(leg.notional)}</td>
              <td className="px-1 py-1 text-right">{fmt(leg.risk)}</td>
              <td className="px-1 py-1 text-right">{fmt(leg.fixed_rate, 5)}</td>
              <td className="px-1 py-1">
                {[leg.is_mac && 'MAC', leg.is_spreadover && 'Spreadover', leg.is_asset_swap && 'AssetSwap', leg.matched_ust_maturity && 'Matched UST'].filter(Boolean).join(', ') || EMPTY}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )

  return (
    <div className="space-y-4">
      {error ? (
        <div className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-3 text-xs text-rose-100">
          <div className="flex items-start gap-2">
            <AlertTriangle className="mt-0.5 h-4 w-4 text-rose-300" />
            <div>{error}</div>
          </div>
        </div>
      ) : null}

      <section className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-2 text-xs text-gray-300">
            <span className="text-[11px] uppercase tracking-wide text-gray-400">Filter Combine</span>
            <div className="inline-flex overflow-hidden rounded border border-gray-700">
              <button
                type="button"
                onClick={() => setColumnFilterOperator(FilterOperator.AND)}
                className={`px-3 py-1 text-[11px] font-semibold uppercase tracking-wide transition ${
                  columnFilterOperator === FilterOperator.AND
                    ? 'bg-gray-700 text-gray-100'
                    : 'text-gray-300 hover:bg-gray-800'
                }`}
              >
                AND
              </button>
              <button
                type="button"
                onClick={() => setColumnFilterOperator(FilterOperator.OR)}
                className={`px-3 py-1 text-[11px] font-semibold uppercase tracking-wide transition ${
                  columnFilterOperator === FilterOperator.OR
                    ? 'bg-gray-700 text-gray-100'
                    : 'text-gray-300 hover:bg-gray-800'
                }`}
              >
                OR
              </button>
            </div>
            <span className="text-[11px] uppercase tracking-wide text-gray-400">Filter</span>
            <input
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              placeholder="Action, package, label..."
              className="min-w-[220px] rounded border border-gray-700 bg-gray-950 px-2 py-1 text-xs text-gray-100"
            />
            <div className="inline-flex overflow-hidden rounded border border-gray-700">
              {METRIC_OPTIONS.map((option) => {
                const selected = metricMode === option.key
                return (
                  <button
                    key={option.key}
                    type="button"
                    onClick={() => setMetricMode(option.key)}
                    className={`px-3 py-1 text-[11px] font-semibold uppercase tracking-wide transition ${
                      selected ? 'bg-gray-700 text-gray-100' : 'text-gray-300 hover:bg-gray-800'
                    }`}
                  >
                    {option.label}
                  </button>
                )
              })}
            </div>
            <button
              type="button"
              onClick={() => fetchTape({ replace: true })}
              className="inline-flex items-center gap-1 rounded border border-gray-700 px-3 py-1 text-[11px] font-semibold uppercase tracking-wide text-gray-200 transition hover:border-gray-500 hover:bg-gray-800"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />
              Refresh
            </button>
          </div>
          <span className="text-[11px] uppercase tracking-wide text-gray-400">
            {loadingMore ? 'Loading more...' : hasMore ? 'Scroll for more' : 'End of data'}
          </span>
        </div>

        <style jsx global>{`
          .swaption-tape-table .p-datatable-tbody > tr,
          .swaption-tape-table .p-datatable-tbody > tr > td {
            border: none !important;
          }
          .swaption-tape-table
            .p-datatable-tbody
            > tr.manual-linked-row
            > td {
            background-color: rgba(245, 158, 11, 0.18) !important;
          }
          .swaption-tape-table
            .p-datatable-tbody
            > tr.selected-share-row
            > td {
            box-shadow:
              inset 0 1px 0 rgba(125, 211, 252, 0.4),
              inset 0 -1px 0 rgba(125, 211, 252, 0.4) !important;
          }
          .swaption-tape-table
            .p-datatable-tbody
            > tr.selected-share-row
            > td:first-child {
            box-shadow:
              inset 1px 0 0 rgba(125, 211, 252, 0.4),
              inset 0 1px 0 rgba(125, 211, 252, 0.4),
              inset 0 -1px 0 rgba(125, 211, 252, 0.4) !important;
          }
          .swaption-tape-table
            .p-datatable-tbody
            > tr.selected-share-row
            > td:last-child {
            box-shadow:
              inset -1px 0 0 rgba(125, 211, 252, 0.4),
              inset 0 1px 0 rgba(125, 211, 252, 0.4),
              inset 0 -1px 0 rgba(125, 211, 252, 0.4) !important;
          }
        `}</style>

        <div ref={tapeContainerRef}>
          <DataTable
            value={rows}
            dataKey="package_id"
            loading={loading}
            selection={selectedRows}
            onSelectionChange={(e) =>
              setSelectedRows(Array.isArray(e.value) ? (e.value as SofrSwapTapeRow[]) : [])
            }
            selectionMode="multiple"
            metaKeySelection={false}
            expandedRows={expandedRows}
            rowExpansionTemplate={rowExpansionTemplate}
            filters={filters}
            filterDisplay="menu"
            onFilter={(e) => setFilters(e.filters as DataTableFilterMeta)}
            scrollable
            scrollHeight="520px"
            virtualScrollerOptions={{
              itemSize: ROW_ESTIMATE_PX,
              lazy: true,
              onLazyLoad: (e: VirtualScrollerLazyEvent) => {
                const last = typeof e.last === 'number' ? e.last : 0
                if (!loadingMore && hasMore && nextCursor && last >= rows.length - 20) {
                  fetchTape({ cursor: nextCursor })
                }
              }
            }}
            resizableColumns
            columnResizeMode="fit"
            rowClassName={rowClassName}
            rowHover
            pt={
              {
                bodyCell: {
                  className: 'py-1 px-2 text-xs !border-0',
                  style: { backgroundColor: 'transparent' }
                }
              } as any
            }
            className="swaption-tape-table rounded-2xl border border-gray-800 bg-gradient-to-b from-gray-950 to-gray-900 shadow-inner text-gray-200"
            size="small"
            sortMode="single"
            sortField={sortField}
            sortOrder={sortOrder}
            onSort={(e: DataTableSortEvent) => {
              setSortField((e.sortField as string) || '')
              setSortOrder((e.sortOrder as 1 | -1 | 0) ?? 0)
            }}
          >
            <Column selectionMode="multiple" style={{ width: 44 }} />
            <Column body={expanderBody} style={{ width: 48 }} />
            <Column
              field="event_action"
              header={renderColumnHeader(COLUMN_DEFS[0].label, 'action')}
              body={actionBody}
              filter
              filterField="action"
              style={{ width: COLUMN_DEFS[0].width }}
              sortable
            />
            <Column
              field="package_type"
              header={renderColumnHeader(COLUMN_DEFS[1].label, 'package_type')}
              body={packageBody}
              filter
              filterField="package_type"
              style={{ width: COLUMN_DEFS[1].width }}
              sortable
            />
            <Column
              field="execution_start"
              header={renderColumnHeader(COLUMN_DEFS[2].label, 'time')}
              body={timeBody}
              filter
              filterField="time"
              filterMatchModeOptions={TIME_FILTER_MATCH_MODE_OPTIONS}
              style={{ width: COLUMN_DEFS[2].width }}
              sortable
            />
            <Column
              field="platform_identifier"
              header={renderColumnHeader(COLUMN_DEFS[3].label, 'platform')}
              body={platformBody}
              filter
              filterField="platform"
              style={{ width: COLUMN_DEFS[3].width }}
              sortable
            />
            <Column
              key={metricColumnKey}
              field={metricField}
              header={renderColumnHeader(metricLabel, metricFilterField)}
              body={metricBody}
              filter
              filterField={metricFilterField}
              dataType="numeric"
              style={{ width: COLUMN_DEFS[4].width }}
              sortable
            />
            <Column
              field="tenor_label"
              header={renderColumnHeader(COLUMN_DEFS[5].label, 'label')}
              body={labelBody}
              filter
              filterField="label"
              style={{ width: COLUMN_DEFS[5].width }}
              sortable
            />
          </DataTable>
        </div>

        {loading ? (
          <div className="flex items-center gap-2 text-sm text-gray-300">
            <RefreshCw className="h-4 w-4 animate-spin" />
            Loading trade tape...
          </div>
        ) : null}
        {loadingMore ? <div className="text-sm text-gray-400">Loading more packages...</div> : null}
      </section>

      <section className="rounded-2xl border border-gray-800 bg-gradient-to-b from-gray-950 to-gray-900 p-3 shadow-inner">
        <div className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-gray-300">Manual Links</div>
        <div className="mb-2 flex flex-wrap gap-2">
          <input value={manualUser} onChange={(e) => setManualUser(e.target.value)} placeholder="user" className="rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs" />
          <input value={manualPackageType} onChange={(e) => setManualPackageType(e.target.value)} placeholder="package type" className="rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs" />
          <input value={manualReason} onChange={(e) => setManualReason(e.target.value)} placeholder="reason" className="rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs" />
          <input value={manualComment} onChange={(e) => setManualComment(e.target.value)} placeholder="comment" className="rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs min-w-[220px]" />
          <button disabled={manualBusy || selectedTradeIds.length < 2} onClick={() => callManualApi('POST', undefined, true)} className="rounded border border-slate-600 px-2 py-1 text-xs disabled:opacity-40">Validate ({selectedTradeIds.length})</button>
          <button disabled={manualBusy || selectedTradeIds.length < 2} onClick={() => callManualApi('POST')} className="rounded border border-emerald-600 px-2 py-1 text-xs disabled:opacity-40">Create</button>
          <button disabled={manualBusy || !selectedLinkId || selectedTradeIds.length < 2} onClick={() => callManualApi('PATCH', selectedLinkId || undefined)} className="rounded border border-amber-600 px-2 py-1 text-xs disabled:opacity-40">Update</button>
          <button disabled={manualBusy || !selectedLinkId} onClick={() => callManualApi('DELETE', selectedLinkId || undefined)} className="rounded border border-rose-600 px-2 py-1 text-xs disabled:opacity-40">Deactivate</button>
        </div>
        {manualError ? <div className="text-xs text-rose-300">{manualError}</div> : null}
        {manualValidation.length ? <div className="text-xs text-slate-300">{manualValidation.map((item) => `${item.status}:${item.label}`).join(' | ')}</div> : null}
      </section>

      <section className="rounded-2xl border border-gray-800 bg-gradient-to-b from-gray-950 to-gray-900 p-3 shadow-inner">
        <div className="mb-2 flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wide text-gray-300">
          <span>Timeseries</span>
          <select value={timeseriesMetric} onChange={(e) => setTimeseriesMetric(e.target.value as TimeseriesMetricKey)} className="rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs">{TIMESERIES_METRICS.map((m) => <option key={m.key} value={m.key}>{m.label}</option>)}</select>
          <select value={timeseriesView} onChange={(e) => setTimeseriesView(e.target.value as TimeseriesViewKey)} className="rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs">{TIMESERIES_VIEWS.map((v) => <option key={v.key} value={v.key}>{v.label}</option>)}</select>
          <button onClick={() => fetchTimeseries().catch((err) => setError(err.message))} className="rounded border border-slate-600 px-2 py-1 text-xs">Reload</button>
          <span className="text-xs text-slate-400">{activeSeriesKey || 'Select a row for series'}</span>
        </div>
        <div className="h-64">
          <ResponsiveContainer width="100%" height="100%">
            {timeseriesMetric === 'trade_count' ? (
              <BarChart data={timeseriesData}><CartesianGrid strokeDasharray="3 3" stroke="#334155" /><XAxis dataKey="label" stroke="#94a3b8" tick={{ fontSize: 11 }} /><YAxis stroke="#94a3b8" tick={{ fontSize: 11 }} /><Tooltip /><Bar dataKey="value" fill="#f97316" /></BarChart>
            ) : (
              <LineChart data={timeseriesData}><CartesianGrid strokeDasharray="3 3" stroke="#334155" /><XAxis dataKey="label" stroke="#94a3b8" tick={{ fontSize: 11 }} /><YAxis stroke="#94a3b8" tick={{ fontSize: 11 }} /><Tooltip /><Line type="monotone" dataKey={timeseriesView === 'DAILY_OHLC' ? 'close' : 'value'} stroke="#38bdf8" dot={false} /></LineChart>
            )}
          </ResponsiveContainer>
        </div>
      </section>

      <section className="rounded-2xl border border-gray-800 bg-gradient-to-b from-gray-950 to-gray-900 p-3 shadow-inner">
        <div className="mb-2 flex flex-wrap items-end gap-2 text-[11px] font-semibold uppercase tracking-wide text-gray-300">
          <span>Flow Grid</span>
          <input type="date" value={flowStart} onChange={(e) => setFlowStart(e.target.value)} className="rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs" />
          <input type="date" value={flowEnd} onChange={(e) => setFlowEnd(e.target.value)} className="rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs" />
          <input type="number" value={forwardBoundary} step="0.25" onChange={(e) => setForwardBoundary(Number(e.target.value) || 0)} className="w-20 rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs" />
          <input type="number" value={tenorBoundary} step="0.25" onChange={(e) => setTenorBoundary(Number(e.target.value) || 0)} className="w-20 rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs" />
          <input type="number" value={tolerance} step="0.05" onChange={(e) => setTolerance(Number(e.target.value) || 0)} className="w-20 rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs" />
          <select value={flowPlatform} onChange={(e) => setFlowPlatform(e.target.value)} className="rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs"><option value="combined">combined</option><option value="idb">idb</option><option value="custy">custy</option></select>
          <button onClick={() => fetchFlow().catch((err) => setError(err.message))} className="rounded border border-slate-600 px-2 py-1 text-xs">Reload</button>
        </div>
        <div className="mb-3 grid gap-2 md:grid-cols-2 xl:grid-cols-4">
          {flowGridRows.map((bucket) => <div key={bucket.bucket} className="rounded border border-slate-700 bg-slate-950 p-2 text-xs"><div>{bucket.label}</div><div>Trades {bucket.tradeCount}</div><div>Notional {formatUsdMillions(bucket.grossNotional)}</div><div>Risk {formatUsdMillions(bucket.grossRisk)}</div><div>IDB {bucket.idbTradeCount} / Custy {bucket.custyTradeCount}</div></div>)}
        </div>
        <div className="h-56">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={flowSeries}><CartesianGrid strokeDasharray="3 3" stroke="#334155" /><XAxis dataKey="date" stroke="#94a3b8" tick={{ fontSize: 11 }} /><YAxis stroke="#94a3b8" tick={{ fontSize: 11 }} /><Tooltip /><Line dataKey="frontShortNotional" stroke="#22c55e" dot={false} /><Line dataKey="frontLongNotional" stroke="#38bdf8" dot={false} /><Line dataKey="forwardShortNotional" stroke="#f59e0b" dot={false} /><Line dataKey="forwardLongNotional" stroke="#f97316" dot={false} /></LineChart>
          </ResponsiveContainer>
        </div>
      </section>

      <section className="rounded-2xl border border-gray-800 bg-gradient-to-b from-gray-950 to-gray-900 p-3 shadow-inner">
        <div className="mb-2 flex items-end gap-2 text-[11px] font-semibold uppercase tracking-wide text-gray-300">
          <span>Sequence Analysis</span>
          <input type="number" value={sequenceGapSeconds} onChange={(e) => setSequenceGapSeconds(Number(e.target.value) || 0)} className="w-24 rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs" />
          <span className="text-xs text-slate-400">{sequenceClusters.length} clusters</span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead><tr className="text-slate-400"><th className="text-left">Cluster</th><th className="text-right">Trades</th><th className="text-right">Pace/min</th><th className="text-right">Gross Notional</th><th className="text-right">Gross Risk</th><th className="text-right">Risk Concentration</th><th className="text-left">Package Mix</th></tr></thead>
            <tbody>
              {sequenceClusters.slice(0, 12).map((cluster) => <tr key={cluster.clusterId} className="border-t border-slate-800"><td>{cluster.clusterId}</td><td className="text-right">{cluster.tradeCount}</td><td className="text-right">{fmt(cluster.paceTradesPerMinute, 2)}</td><td className="text-right">{fmt(cluster.grossNotional)}</td><td className="text-right">{fmt(cluster.grossRisk)}</td><td className="text-right">{fmt(cluster.riskConcentrationPct, 1)}%</td><td>{cluster.packageMix.slice(0, 3).map((entry) => `${entry.packageType}:${entry.count}`).join('  ')}</td></tr>)}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}
