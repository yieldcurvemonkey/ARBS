import { useEffect, useMemo, useState } from 'react'
import { QuadrantDivergenceChart } from './QuadrantDivergenceChart'
import { QuadrantHistorySummary } from './QuadrantHistorySummary'
import { QuadrantRegimeStrip } from './QuadrantRegimeStrip'
import {
  QuadrantTimeseries,
  QuadrantTimeseriesDatum,
  QuadrantTimeseriesFormatters,
  QuadrantTimeseriesMetric,
} from './QuadrantTimeseries'
import { QuadrantTimeseriesGrid } from './QuadrantTimeseriesGrid'
import { useQuadrantHistory } from './quadrantHistory.hooks'
import type {
  HistoryAggregation,
  HistoryLookback,
  HistoryMetricKey,
  HistoryViewMode,
  QuadrantConfig,
  QuadrantDayAggregate,
  VolGridQuadrant,
} from './quadrantHistory.types'
import {
  aggregateToMonthly,
  aggregateToWeekly,
  computePremiumShares,
  computeRollingAverage,
  ensureNormalizedDay,
  ensureSortedDays,
} from './quadrantHistory.utils'

export type VolGridFlowHistoryFormatters = {
  formatNotional: (value: number | null | undefined) => string
  formatSignedNotional: (value: number | null | undefined) => string
  formatRate: (value: number | null | undefined, decimals?: number) => string
  formatCount: (value: number | null | undefined) => string
}

export type VolGridFlowHistoryProps = {
  lookback: HistoryLookback
  platform: 'combined' | 'idb' | 'custy'
  quadrantConfig: QuadrantConfig
  todayData: QuadrantDayAggregate | null
  onDateSelect?: (date: string) => void
  formatters: VolGridFlowHistoryFormatters
  excludeLargeCustyNotional: boolean
  onExcludeLargeCustyNotionalChange: (next: boolean) => void
}

const QUADRANTS: VolGridQuadrant[] = ['ULC', 'URC', 'LLC', 'LRC']

const METRIC_DEFINITIONS: QuadrantTimeseriesMetric[] = [
  {
    key: 'netNotional',
    label: 'Net Notional',
    yAxisLabel: 'Net notional (mm)',
    chartType: 'area',
  },
  {
    key: 'grossNotional',
    label: 'Gross Notional',
    yAxisLabel: 'Gross notional (mm)',
    chartType: 'bar',
  },
  {
    key: 'tradeCount',
    label: 'Trade Count',
    yAxisLabel: 'Trades',
    chartType: 'bar',
  },
  {
    key: 'totalPremium',
    label: 'Total Premium',
    yAxisLabel: 'Premium (mm)',
    chartType: 'bar',
  },
  {
    key: 'netGrossRatio',
    label: 'Net/Gross',
    yAxisLabel: 'Net/Gross',
    chartType: 'line',
  },
  {
    key: 'premiumShare',
    label: 'Premium Share',
    yAxisLabel: '% of grid premium',
    chartType: 'stackedArea',
  },
  {
    key: 'custyShare',
    label: 'Custy Share',
    yAxisLabel: 'Custy share (%)',
    chartType: 'line',
  },
  {
    key: 'pace',
    label: 'Activity vs 20d Avg',
    yAxisLabel: 'Activity (x 20d avg)',
    chartType: 'line',
  },
]

const defaultAggregationForLookback = (lookback: HistoryLookback): HistoryAggregation => {
  if (lookback === 'ALL') return 'monthly'
  if (lookback === '6M' || lookback === '1Y') return 'weekly'
  return 'daily'
}

const aggregationOptions = (lookback: HistoryLookback): HistoryAggregation[] => {
  if (lookback === 'ALL') return ['weekly', 'monthly']
  if (lookback === '3M' || lookback === '6M' || lookback === '1Y') {
    return ['daily', 'weekly']
  }
  return ['daily']
}

const formatDateLabelForLookback = (
  date: string,
  lookback: HistoryLookback,
  aggregation: HistoryAggregation,
) => {
  const parsed = new Date(`${date}T00:00:00Z`)
  if (Number.isNaN(parsed.getTime())) return date
  if (aggregation === 'monthly') {
    return parsed.toLocaleDateString('en-US', { month: 'short', year: '2-digit' })
  }
  if (lookback === '1W' || lookback === '1M' || lookback === '3M') {
    return parsed.toLocaleDateString('en-US', { month: 'short', day: '2-digit' })
  }
  return parsed.toLocaleDateString('en-US', { month: 'short', year: '2-digit' })
}

function mergeTodayData(
  days: QuadrantDayAggregate[],
  todayData: QuadrantDayAggregate | null,
): QuadrantDayAggregate[] {
  if (!todayData) return days
  const normalizedToday = ensureNormalizedDay({ ...todayData })
  const map = new Map(days.map((day) => [day.date, day]))
  map.set(todayData.date, normalizedToday)
  return ensureSortedDays(Array.from(map.values()))
}

function mapToChartData(
  days: QuadrantDayAggregate[],
  metricKey: HistoryMetricKey,
  premiumShares: Map<string, Record<VolGridQuadrant, number>>,
  custyShares: Map<string, Record<VolGridQuadrant, number>>,
  paceMap: Map<string, Record<VolGridQuadrant, number | null>>,
  highlightDate?: string | null,
): QuadrantTimeseriesDatum[] {
  return days.map((day) => {
    const values: Record<VolGridQuadrant, number | null> = {
      ULC: 0,
      URC: 0,
      LLC: 0,
      LRC: 0,
    }

    QUADRANTS.forEach((quadrant) => {
      const stats = day.quadrants[quadrant]
      switch (metricKey) {
        case 'netNotional':
          values[quadrant] = stats.netNotional
          break
        case 'grossNotional':
          values[quadrant] = stats.grossNotional
          break
        case 'tradeCount':
          values[quadrant] = stats.tradeCount
          break
        case 'totalPremium':
          values[quadrant] = stats.totalPremium
          break
        case 'netGrossRatio':
          values[quadrant] = stats.netGrossRatio
          break
        case 'premiumShare':
          values[quadrant] = premiumShares.get(day.date)?.[quadrant] ?? 0
          break
        case 'custyShare':
          values[quadrant] = custyShares.get(day.date)?.[quadrant] ?? 0
          break
        case 'pace':
          values[quadrant] = paceMap.get(day.date)?.[quadrant] ?? null
          break
        default:
          values[quadrant] = stats.netNotional
      }
    })

    return {
      date: day.date,
      ULC: values.ULC,
      URC: values.URC,
      LLC: values.LLC,
      LRC: values.LRC,
      raw: day,
      isToday: highlightDate ? day.date === highlightDate : false,
    }
  })
}

function computeCustyShares(days: QuadrantDayAggregate[]): Map<string, Record<VolGridQuadrant, number>> {
  const map = new Map<string, Record<VolGridQuadrant, number>>()
  days.forEach((day) => {
    const shares: Record<VolGridQuadrant, number> = {
      ULC: 0,
      URC: 0,
      LLC: 0,
      LRC: 0,
    }
    QUADRANTS.forEach((quadrant) => {
      const stats = day.quadrants[quadrant]
      const total = stats.custyGross + stats.idbGross
      shares[quadrant] = total > 0 ? (stats.custyGross / total) * 100 : 0
    })
    map.set(day.date, shares)
  })
  return map
}

function computePaceMap(
  days: QuadrantDayAggregate[],
  todayDate?: string | null,
): Map<string, Record<VolGridQuadrant, number | null>> {
  const map = new Map<string, Record<VolGridQuadrant, number | null>>()
  QUADRANTS.forEach((quadrant) => {
    const rolling = computeRollingAverage(days, quadrant, 'grossNotional', 20)
    days.forEach((day, index) => {
      // Exclude today's partial-day data — comparing partial intraday gross
      // against full-day historical averages produces misleadingly low values.
      // The real-time quadrant cells already show time-of-day-normalized pace.
      if (todayDate && day.date === todayDate) {
        const entry = map.get(day.date) ?? { ULC: null, URC: null, LLC: null, LRC: null }
        entry[quadrant] = null
        map.set(day.date, entry)
        return
      }
      const baseline = rolling[index]?.value ?? null
      const pace = baseline && baseline > 0 ? day.quadrants[quadrant].grossNotional / baseline : null
      const entry = map.get(day.date) ?? { ULC: null, URC: null, LLC: null, LRC: null }
      entry[quadrant] = pace
      map.set(day.date, entry)
    })
  })
  return map
}

export function VolGridFlowHistory({
  lookback,
  platform,
  quadrantConfig,
  todayData,
  onDateSelect,
  formatters,
  excludeLargeCustyNotional,
  onExcludeLargeCustyNotionalChange,
}: VolGridFlowHistoryProps) {
  const [metricKey, setMetricKey] = useState<HistoryMetricKey>('netNotional')
  const [viewMode, setViewMode] = useState<HistoryViewMode>('stacked')
  const [aggregation, setAggregation] = useState<HistoryAggregation>(
    defaultAggregationForLookback(lookback),
  )
  const [showRollingAverage, setShowRollingAverage] = useState(false)
  const [showRegimeStrip, setShowRegimeStrip] = useState(true)
  const [showDivergence, setShowDivergence] = useState(true)

  const { data, isLoading, error } = useQuadrantHistory({
    lookback,
    platform,
    quadrantConfig,
    excludeLargeCustyNotional,
  })

  useEffect(() => {
    setAggregation(defaultAggregationForLookback(lookback))
  }, [lookback])

  useEffect(() => {
    if (platform !== 'combined' && metricKey === 'custyShare') {
      setMetricKey('netNotional')
    }
  }, [metricKey, platform])

  const days = useMemo(() => {
    const base = data?.days?.length ? ensureSortedDays(data.days) : []
    return mergeTodayData(base, todayData)
  }, [data?.days, todayData])

  const aggregatedDays = useMemo(() => {
    if (aggregation === 'weekly') return aggregateToWeekly(days)
    if (aggregation === 'monthly') return aggregateToMonthly(days)
    return days
  }, [aggregation, days])

  const highlightDate =
    todayData?.date ?? new Date().toISOString().slice(0, 10)

  const premiumShares = useMemo(() => {
    const shares = computePremiumShares(aggregatedDays)
    return new Map(shares.map((entry) => [entry.date, entry]))
  }, [aggregatedDays])

  const custyShares = useMemo(() => computeCustyShares(aggregatedDays), [aggregatedDays])
  const paceMap = useMemo(() => computePaceMap(aggregatedDays, highlightDate), [aggregatedDays, highlightDate])

  const chartData = useMemo(
    () =>
      mapToChartData(
        aggregatedDays,
        metricKey,
        premiumShares,
        custyShares,
        paceMap,
        highlightDate,
      ),
    [aggregatedDays, custyShares, highlightDate, metricKey, paceMap, premiumShares],
  )

  const metric = METRIC_DEFINITIONS.find((entry) => entry.key === metricKey) ?? METRIC_DEFINITIONS[0]

  const formatDateLabel = (value: string) =>
    formatDateLabelForLookback(value, lookback, aggregation)

  const timeseriesFormatters: QuadrantTimeseriesFormatters = {
    formatNotional: formatters.formatNotional,
    formatSignedNotional: formatters.formatSignedNotional,
    formatRate: formatters.formatRate,
    formatCount: formatters.formatCount,
    formatDateLabel,
  }

  const lookbackLabel = lookback

  const controlsAggregation = aggregationOptions(lookback)

  return (
    <div className="mt-3">
      <div className="flex flex-wrap items-center justify-between gap-3 text-[11px]">
        <div className="flex flex-wrap items-center gap-2">
          <label className="text-[10px] uppercase tracking-wide text-slate-400">Metric</label>
          <select
            value={metricKey}
            onChange={(event) => setMetricKey(event.target.value as HistoryMetricKey)}
            className="rounded border border-slate-700 bg-slate-950 px-2 py-1 text-[11px] text-slate-200"
          >
            {METRIC_DEFINITIONS.filter(
              (entry) => platform === 'combined' || entry.key !== 'custyShare',
            ).map((entry) => (
              <option key={entry.key} value={entry.key}>
                {entry.label}
              </option>
            ))}
          </select>
          <label className="text-[10px] uppercase tracking-wide text-slate-400">View</label>
          <div className="inline-flex overflow-hidden rounded border border-slate-700">
            <button
              type="button"
              onClick={() => setViewMode('stacked')}
              className={`px-2 py-1 text-[10px] font-semibold uppercase tracking-wide transition ${
                viewMode === 'stacked' ? 'bg-slate-700 text-slate-100' : 'text-slate-300 hover:bg-slate-800'
              }`}
            >
              Stacked
            </button>
            <button
              type="button"
              onClick={() => setViewMode('grid')}
              className={`px-2 py-1 text-[10px] font-semibold uppercase tracking-wide transition ${
                viewMode === 'grid' ? 'bg-slate-700 text-slate-100' : 'text-slate-300 hover:bg-slate-800'
              }`}
            >
              Grid
            </button>
          </div>
          {controlsAggregation.length > 1 && (
            <>
              <label className="text-[10px] uppercase tracking-wide text-slate-400">Agg</label>
              <div className="inline-flex overflow-hidden rounded border border-slate-700">
                {controlsAggregation.map((option) => (
                  <button
                    key={option}
                    type="button"
                    onClick={() => setAggregation(option)}
                    className={`px-2 py-1 text-[10px] font-semibold uppercase tracking-wide transition ${
                      aggregation === option
                        ? 'bg-slate-700 text-slate-100'
                        : 'text-slate-300 hover:bg-slate-800'
                    }`}
                  >
                    {option}
                  </button>
                ))}
              </div>
            </>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-3 text-[10px] text-slate-400">
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={excludeLargeCustyNotional}
              onChange={(event) =>
                onExcludeLargeCustyNotionalChange(event.target.checked)
              }
              className="h-3 w-3"
            />
            Remove Comically Large Custy Notional Trade
          </label>
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={showRollingAverage}
              onChange={(event) => setShowRollingAverage(event.target.checked)}
              className="h-3 w-3"
            />
            Show 5d/20d MA
          </label>
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={showRegimeStrip}
              onChange={(event) => setShowRegimeStrip(event.target.checked)}
              className="h-3 w-3"
            />
            Regime strip
          </label>
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={showDivergence}
              onChange={(event) => setShowDivergence(event.target.checked)}
              className="h-3 w-3"
            />
            Divergence
          </label>
        </div>
      </div>

      {isLoading && !chartData.length && (
        <div className="mt-3 text-xs text-slate-400">Loading quadrant history...</div>
      )}
      {error && (
        <div className="mt-3 text-xs text-amber-300">
          {error.message || 'Failed to load quadrant history.'}
        </div>
      )}
      {!isLoading && !error && chartData.length === 0 && (
        <div className="mt-3 text-xs text-slate-400">No quadrant history available.</div>
      )}

      {chartData.length > 0 && (
        <div className="mt-3">
          {viewMode === 'stacked' ? (
            <QuadrantTimeseries
              data={chartData}
              days={aggregatedDays}
              metric={metric}
              formatters={timeseriesFormatters}
              highlightDate={highlightDate}
              showRollingAverage={showRollingAverage}
              onDateSelect={onDateSelect}
            />
          ) : (
            <QuadrantTimeseriesGrid
              data={chartData}
              days={aggregatedDays}
              metric={metric}
              formatters={timeseriesFormatters}
              highlightDate={highlightDate}
              showRollingAverage={showRollingAverage}
              onDateSelect={onDateSelect}
            />
          )}
        </div>
      )}

      {showRegimeStrip && chartData.length > 0 && (
        <QuadrantRegimeStrip days={aggregatedDays} formatDateLabel={formatDateLabel} />
      )}

      {showDivergence && chartData.length > 0 && (
        <QuadrantDivergenceChart
          days={aggregatedDays}
          formatters={formatters}
          highlightDate={highlightDate}
          formatDateLabel={formatDateLabel}
        />
      )}

      {chartData.length > 0 && (
        <QuadrantHistorySummary
          days={aggregatedDays}
          formatters={{
            formatNotional: formatters.formatNotional,
            formatSignedNotional: formatters.formatSignedNotional,
            formatRate: formatters.formatRate,
            formatDateLabel,
          }}
          lookbackLabel={lookbackLabel}
        />
      )}
    </div>
  )
}
