'use client'

import { useEffect, useMemo, useState } from 'react'
import { Dialog } from '@/components/ui/Dialog/Dialog'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis
} from 'recharts'
import { TimeseriesAnnotations } from '@/features/swaptions-tape/components/TradeRarityPanel/TimeseriesAnnotations'
import type {
  CalibrationObservation,
  CellDetailResponse,
  VolGridCell,
  VolGridHistoryRange,
  VolGridHistorySource,
  VolGridSessionMeta,
  VolGridTradeHistoryStats,
  VolGridTradeTimelineMetric
} from '../types'
import {
  VOL_GRID_HISTORY_RANGE_OPTIONS,
  VOL_GRID_TRADE_TIMELINE_METRIC_OPTIONS,
  filterTimeseriesByRange,
  filterTradeHistoryByRange,
  formatTradeTimelineMetricLabel,
  getTradeTimelineMetricValue
} from '../analytics'
import {
  formatChange,
  formatConfidence,
  formatDate,
  formatNotional,
  formatNumber,
  formatPremiumBps,
  formatTime
} from '../utils'
import { PlotlyNvolChart } from './PlotlyNvolChart'

type CellAnalyticsModalProps = {
  cell: VolGridCell | null
  detail: CellDetailResponse | null
  loading: boolean
  error: string | null
  session: VolGridSessionMeta | null
  onClose: () => void
}

type AnalyticsTab = 'analytics' | 'history'

function formatLongDate(date: string) {
  const parsed = new Date(`${date}T00:00:00Z`)
  return new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/New_York',
    year: 'numeric',
    month: 'short',
    day: '2-digit'
  }).format(parsed)
}

function formatTradeAxisLabel(timestamp: number, range: VolGridHistoryRange) {
  return new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/New_York',
    month: 'short',
    day: '2-digit',
    ...(range === '1M'
      ? {
          hour: '2-digit',
          minute: '2-digit'
        }
      : {})
  }).format(new Date(timestamp))
}

function formatFullTimestamp(timestamp: number | null) {
  if (!timestamp) return '--'
  return `${formatDate(timestamp)} ${formatTime(timestamp)} ET`
}

function formatCompactAmount(value: number | null, maximumFractionDigits = 1) {
  if (value === null || !Number.isFinite(value)) return '--'
  return new Intl.NumberFormat('en-US', {
    notation: 'compact',
    maximumFractionDigits
  }).format(Math.abs(value))
}

function formatDurationMs(value: number | null) {
  if (value === null || !Number.isFinite(value)) return '--'
  const absValue = Math.abs(value)
  if (absValue < 60_000) return `${Math.round(absValue / 1000)}s`
  if (absValue < 3_600_000) return `${(absValue / 60_000).toFixed(1)}m`
  if (absValue < 86_400_000) return `${(absValue / 3_600_000).toFixed(1)}h`
  return `${(absValue / 86_400_000).toFixed(1)}d`
}

function formatRate(value: number | null, digits = 2) {
  if (value === null || !Number.isFinite(value)) return '--'
  return value.toFixed(digits)
}

function formatHistorySourceLabel(source: VolGridHistorySource) {
  return source === 'pca' ? 'PCA Grid' : 'MDP (GSQuant)'
}

function getChangeTone(value: number | null) {
  if (value === null || !Number.isFinite(value)) return 'text-slate-100'
  if (value > 0) return 'text-emerald-300'
  if (value < 0) return 'text-rose-300'
  return 'text-slate-100'
}

function getTradeMetricColor(metric: VolGridTradeTimelineMetric) {
  if (metric === 'notional') return '#38bdf8'
  if (metric === 'premium') return '#34d399'
  return '#f59e0b'
}

function formatTradeMetricValue(
  metric: VolGridTradeTimelineMetric,
  value: number | null,
  withUnit = true
) {
  if (value === null || !Number.isFinite(value)) return '--'
  if (metric === 'notional') return formatNotional(value)
  if (metric === 'premium') return formatCompactAmount(value)
  return withUnit ? `${formatNumber(value, 2)} bpvol` : formatNumber(value, 2)
}

function median(values: number[]) {
  if (!values.length) return null
  const sorted = values.slice().sort((left, right) => left - right)
  const middle = Math.floor(sorted.length / 2)
  if (sorted.length % 2 === 0) {
    return (sorted[middle - 1] + sorted[middle]) / 2
  }
  return sorted[middle]
}

function buildLocalDateKey(timestamp: number) {
  const date = new Date(timestamp)
  if (Number.isNaN(date.getTime())) return null
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'America/New_York',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit'
  }).formatToParts(date)
  const year = parts.find((part) => part.type === 'year')?.value
  const month = parts.find((part) => part.type === 'month')?.value
  const day = parts.find((part) => part.type === 'day')?.value
  if (!year || !month || !day) return null
  return `${year}-${month}-${day}`
}

function computeTradeHistoryStats(trades: CalibrationObservation[]): VolGridTradeHistoryStats {
  const tradeCount = trades.length
  const notionals = trades
    .map((trade) => trade.notional)
    .filter((value): value is number => value !== null && Number.isFinite(value))
    .map((value) => Math.abs(value))
  const premiums = trades
    .map((trade) => trade.premium)
    .filter((value): value is number => value !== null && Number.isFinite(value))
    .map((value) => Math.abs(value))
  const bpvols = trades
    .map((trade) => trade.bpvolYr)
    .filter((value): value is number => Number.isFinite(value))
  const timestamps = trades
    .map((trade) => trade.executionTimestamp)
    .filter((value): value is number => Number.isFinite(value))
    .slice()
    .sort((left, right) => left - right)

  let avgGapMs: number | null = null
  if (timestamps.length > 1) {
    let totalGap = 0
    for (let index = 1; index < timestamps.length; index += 1) {
      totalGap += timestamps[index] - timestamps[index - 1]
    }
    avgGapMs = totalGap / (timestamps.length - 1)
  }

  const activeDaysSet = new Set<string>()
  timestamps.forEach((timestamp) => {
    const key = buildLocalDateKey(timestamp)
    if (key) activeDaysSet.add(key)
  })
  const activeDays = activeDaysSet.size || null
  const platformCounts = new Map<string, number>()
  trades.forEach((trade) => {
    const platform = String(trade.platform ?? '--').trim() || '--'
    platformCounts.set(platform, (platformCounts.get(platform) ?? 0) + 1)
  })

  const totalNotional = notionals.length
    ? notionals.reduce((sum, value) => sum + value, 0)
    : null
  const totalPremium = premiums.length
    ? premiums.reduce((sum, value) => sum + value, 0)
    : null

  return {
    tradeCount,
    firstTradeTimestamp: timestamps[0] ?? null,
    lastTradeTimestamp: timestamps[timestamps.length - 1] ?? null,
    totalNotional,
    avgNotional: totalNotional !== null && notionals.length ? totalNotional / notionals.length : null,
    medianNotional: median(notionals),
    totalPremium,
    avgPremium: totalPremium !== null && premiums.length ? totalPremium / premiums.length : null,
    medianPremium: median(premiums),
    avgBpvol: bpvols.length ? bpvols.reduce((sum, value) => sum + value, 0) / bpvols.length : null,
    medianBpvol: median(bpvols),
    tradesPerDay: activeDays ? tradeCount / activeDays : null,
    avgGapMs,
    activeDays,
    platformBreakdown: Array.from(platformCounts.entries())
      .sort((left, right) => right[1] - left[1])
      .map(([platform, count]) => ({ platform, count }))
  }
}

function TabButton({
  active,
  label,
  onClick
}: {
  active: boolean
  label: string
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`px-3 py-1.5 text-[11px] font-semibold uppercase tracking-wide transition ${
        active
          ? 'bg-slate-700 text-slate-100'
          : 'text-slate-300 hover:bg-slate-800'
      }`}
    >
      {label}
    </button>
  )
}

function StatCard({
  label,
  value,
  subtitle,
  valueClassName = 'text-white'
}: {
  label: string
  value: string
  subtitle?: string
  valueClassName?: string
}) {
  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-950/45 p-3">
      <div className="text-[10px] font-semibold uppercase tracking-[0.2em] text-slate-500">
        {label}
      </div>
      <div className={`mt-2 text-[1.35rem] font-semibold leading-tight ${valueClassName}`}>
        {value}
      </div>
      {subtitle && <div className="mt-1 text-[11px] text-slate-400">{subtitle}</div>}
    </div>
  )
}

function SectionCard({
  title,
  subtitle,
  children,
  className = ''
}: {
  title: string
  subtitle?: string
  children: React.ReactNode
  className?: string
}) {
  return (
    <div className={`rounded-2xl border border-slate-800 bg-slate-950/45 p-3 ${className}`.trim()}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-[0.2em] text-slate-500">
            {title}
          </div>
          {subtitle && <div className="mt-1 text-[11px] text-slate-400">{subtitle}</div>}
        </div>
      </div>
      <div className="mt-3">{children}</div>
    </div>
  )
}

function MetricRow({
  label,
  value
}: {
  label: string
  value: string
}) {
  return (
    <div className="flex items-center justify-between gap-3 border-b border-slate-800/70 py-2 text-[11px] last:border-b-0 last:pb-0">
      <span className="text-slate-400">{label}</span>
      <span className="font-mono text-slate-100">{value}</span>
    </div>
  )
}

function TradeHistoryRow({ trade }: { trade: CalibrationObservation }) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-950/35 px-3 py-2">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-[11px] font-semibold text-slate-300">
            {formatFullTimestamp(trade.executionTimestamp)}
          </div>
          <div className="truncate text-sm font-semibold text-slate-100">
            {trade.tradeLabel}
          </div>
          <div className="mt-1 text-[11px] text-slate-400">
            {trade.platform ?? '--'} | {trade.expiry ?? '--'}x{trade.tenor ?? '--'} |{' '}
            {formatNotional(trade.notional)}
          </div>
        </div>
        <div className="text-right">
          <div className="text-base font-semibold text-white">
            {formatNumber(trade.bpvolYr, 2)}
          </div>
          <div className="text-[11px] text-slate-400">bpvol</div>
        </div>
      </div>
    </div>
  )
}

function TradeTimelineTooltip({
  active,
  payload,
  label,
  metric
}: {
  active?: boolean
  payload?: Array<{ payload: any }>
  label?: string | number
  metric: VolGridTradeTimelineMetric
}) {
  if (!active || !payload?.length) return null
  const point = payload[0]?.payload
  if (!point) return null

  return (
    <div className="rounded-lg border border-slate-700 bg-slate-950/95 px-3 py-2 text-[11px] text-slate-200 shadow-xl">
      <div className="font-semibold text-slate-100">
        {formatFullTimestamp(Number(label))}
      </div>
      <div className="mt-1 text-slate-300">{point.tradeLabel}</div>
      <div className="mt-2 space-y-1 text-slate-400">
        <div className="flex items-center justify-between gap-4">
          <span>{formatTradeTimelineMetricLabel(metric)}</span>
          <span className="font-mono text-slate-100">
            {formatTradeMetricValue(metric, point.value)}
          </span>
        </div>
        <div className="flex items-center justify-between gap-4">
          <span>BPVol</span>
          <span className="font-mono text-slate-100">{formatNumber(point.bpvol, 2)} bpvol</span>
        </div>
        <div className="flex items-center justify-between gap-4">
          <span>Notional</span>
          <span className="font-mono text-slate-100">{formatNotional(point.notional)}</span>
        </div>
        <div className="flex items-center justify-between gap-4">
          <span>Premium</span>
          <span className="font-mono text-slate-100">{formatCompactAmount(point.premium)}</span>
        </div>
        <div className="flex items-center justify-between gap-4">
          <span>Platform</span>
          <span className="font-mono text-slate-100">{point.platform ?? '--'}</span>
        </div>
      </div>
    </div>
  )
}

export function CellAnalyticsModal({
  cell,
  detail,
  loading,
  error,
  session,
  onClose
}: CellAnalyticsModalProps) {
  const [activeTab, setActiveTab] = useState<AnalyticsTab>('analytics')
  const [historyRange, setHistoryRange] = useState<VolGridHistoryRange>('1Y')
  const [historySource, setHistorySource] = useState<VolGridHistorySource>('mdp')
  const [tradeTimelineMetric, setTradeTimelineMetric] =
    useState<VolGridTradeTimelineMetric>('bpvol')
  const [showTradeSigmaBands, setShowTradeSigmaBands] = useState(false)

  useEffect(() => {
    setActiveTab('analytics')
    setHistoryRange('1Y')
    setTradeTimelineMetric('bpvol')
    setShowTradeSigmaBands(false)
  }, [cell?.nodeKey])

  useEffect(() => {
    const nextSource = detail?.defaultHistorySource ?? 'mdp'
    if (!detail?.availableHistorySources?.length) {
      setHistorySource(nextSource)
      return
    }
    if (!detail.availableHistorySources.includes(historySource)) {
      setHistorySource(nextSource)
    }
  }, [detail?.availableHistorySources, detail?.defaultHistorySource, historySource])

  const availableHistorySources = detail?.availableHistorySources ?? []
  const resolvedHistorySource =
    availableHistorySources.includes(historySource)
      ? historySource
      : detail?.defaultHistorySource ?? 'mdp'

  const filteredTimeseries = useMemo(
    () =>
      filterTimeseriesByRange(
        detail?.timeseriesBySource?.[resolvedHistorySource] ?? [],
        historyRange
      ),
    [detail?.timeseriesBySource, historyRange, resolvedHistorySource]
  )

  const nvolSeries = useMemo(
    () => [
      {
        key: resolvedHistorySource,
        label: formatHistorySourceLabel(resolvedHistorySource),
        color: resolvedHistorySource === 'pca' ? '#f59e0b' : '#38bdf8',
        points: filteredTimeseries.map((point) => ({
          date: point.date,
          nvol: point.nvol
        }))
      }
    ],
    [filteredTimeseries, resolvedHistorySource]
  )

  const currentTimeseriesPoint = filteredTimeseries[filteredTimeseries.length - 1] ?? null
  const filteredTrades = useMemo(
    () => filterTradeHistoryByRange(detail?.tradeHistory ?? [], historyRange),
    [detail?.tradeHistory, historyRange]
  )
  const filteredTradeSummary = useMemo(
    () => computeTradeHistoryStats(filteredTrades),
    [filteredTrades]
  )

  const tradeTimelineData = useMemo(
    () =>
      filteredTrades
        .slice()
        .sort((left, right) => left.executionTimestamp - right.executionTimestamp)
        .map((trade) => ({
          timeKey: String(trade.executionTimestamp),
          timestamp: trade.executionTimestamp,
          value: getTradeTimelineMetricValue(trade, tradeTimelineMetric),
          tradeLabel: trade.tradeLabel,
          platform: trade.platform,
          bpvol: trade.bpvolYr,
          notional: trade.notional,
          premium: trade.premium
        }))
        .filter(
          (point): point is {
            timeKey: string
            timestamp: number
            value: number
            tradeLabel: string
            platform: string | null
            bpvol: number
            notional: number | null
            premium: number | null
          } => Number.isFinite(point.value)
        ),
    [filteredTrades, tradeTimelineMetric]
  )

  const tradeDistributionValues = useMemo(
    () => tradeTimelineData.map((point) => point.value).filter((value) => Number.isFinite(value)),
    [tradeTimelineData]
  )

  const latestTimelinePoint = tradeTimelineData[tradeTimelineData.length - 1] ?? null
  const recentTrades = filteredTrades.slice(0, 8)

  if (!cell) return null

  return (
    <Dialog
      isOpen={!!cell}
      onClose={onClose}
      size="5xl"
      title={`${cell.expiry} x ${cell.tenor} Node Analytics`}
      overlayClassName="bg-slate-950/55 backdrop-blur-[3px]"
      className="!bg-slate-950/70 border border-slate-700/70 shadow-2xl shadow-slate-950/70 backdrop-blur-xl"
    >
      <div className="space-y-4">
        <div className="grid gap-3 lg:grid-cols-5">
          <StatCard
            label="ATMF Vol"
            value={`${formatNumber(cell.atmfVol, 2)} bpvol`}
            subtitle={session?.isClosingView ? 'Closing snapshot' : 'Live snapshot'}
          />
          <StatCard
            label="Premium"
            value={formatPremiumBps(cell.atmfPremiumBps)}
            subtitle={`Confidence ${formatConfidence(cell.atmfVolConfidence)}`}
          />
          <StatCard
            label="dVol"
            value={`${formatChange(cell.atmfVolChange, 1)} bpvol`}
            valueClassName={getChangeTone(cell.atmfVolChange)}
            subtitle="Vol change vs reference close"
          />
          <StatCard
            label="dPrem"
            value={`${formatChange(cell.atmfPremiumBpsChange, 2)} bp`}
            valueClassName={getChangeTone(cell.atmfPremiumBpsChange)}
            subtitle="Premium change vs reference close"
          />
          <StatCard
            label="Last Trade"
            value={cell.lastObservation ? formatFullTimestamp(cell.lastObservation.executionTimestamp) : '--'}
            subtitle={
              cell.lastObservation
                ? `${formatNumber(cell.lastObservation.bpvolYr, 2)} bpvol | ${cell.lastObservation.platform ?? '--'}`
                : 'No mapped trade history'
            }
          />
        </div>

        <div className="grid gap-3 lg:grid-cols-4">
          <StatCard label="1W Trade Count" value={String(detail?.volumeStats.tradeCount1w ?? 0)} />
          <StatCard
            label="Avg Notional 1W"
            value={formatNotional(detail?.volumeStats.avgNotional1w ?? null)}
          />
          <StatCard
            label="Window Trades"
            value={String(filteredTradeSummary.tradeCount)}
            subtitle={
              filteredTradeSummary.firstTradeTimestamp
                ? `Since ${formatFullTimestamp(filteredTradeSummary.firstTradeTimestamp)}`
                : 'No trades in range'
            }
          />
          <StatCard
            label="Regime"
            value={detail?.technicalSignals.regimeLabel ?? '--'}
            subtitle={
              detail?.volumeStats.lastTradeTimestamp
                ? `Last print ${detail.volumeStats.daysSinceLastTrade ?? '--'}d ago`
                : 'Awaiting first trade'
            }
          />
        </div>

        <div className="rounded-xl border border-slate-800 bg-slate-950/35 px-3 py-2 text-xs text-slate-400">
          Source: {formatHistorySourceLabel(resolvedHistorySource)}
          {cell.comparisonVol !== null && (
            <span className="ml-3">
              MDP close {formatNumber(cell.comparisonVol, 2)} bpvol, basis {formatChange(cell.comparisonDiff)}
            </span>
          )}
        </div>

        <div className="rounded-2xl border border-slate-800 bg-slate-950/25 p-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="inline-flex overflow-hidden rounded-lg border border-slate-700">
              <TabButton
                active={activeTab === 'analytics'}
                label="Analytics"
                onClick={() => setActiveTab('analytics')}
              />
              <TabButton
                active={activeTab === 'history'}
                label="Trade History"
                onClick={() => setActiveTab('history')}
              />
            </div>

            <div className="flex flex-wrap items-center gap-2">
              {availableHistorySources.length > 0 && (
                <div className="inline-flex overflow-hidden rounded-lg border border-slate-700">
                  {availableHistorySources.map((source) => (
                    <TabButton
                      key={source}
                      active={resolvedHistorySource === source}
                      label={source === 'pca' ? 'PCA' : 'MDP'}
                      onClick={() => setHistorySource(source)}
                    />
                  ))}
                </div>
              )}

              <div className="inline-flex overflow-hidden rounded-lg border border-slate-700">
                {VOL_GRID_HISTORY_RANGE_OPTIONS.map((range) => (
                  <TabButton
                    key={range}
                    active={historyRange === range}
                    label={range}
                    onClick={() => setHistoryRange(range)}
                  />
                ))}
              </div>

              {activeTab === 'analytics' && (
                <>
                  <div className="inline-flex overflow-hidden rounded-lg border border-slate-700">
                    {VOL_GRID_TRADE_TIMELINE_METRIC_OPTIONS.map((metric) => (
                      <TabButton
                        key={metric}
                        active={tradeTimelineMetric === metric}
                        label={metric === 'bpvol' ? 'BPVol' : metric === 'notional' ? 'Notional' : 'Premium'}
                        onClick={() => setTradeTimelineMetric(metric)}
                      />
                    ))}
                  </div>
                  <button
                    type="button"
                    onClick={() => setShowTradeSigmaBands((current) => !current)}
                    className={`rounded-lg border px-3 py-1.5 text-[11px] font-semibold uppercase tracking-wide transition ${
                      showTradeSigmaBands
                        ? 'border-sky-400/70 bg-sky-500/10 text-sky-100'
                        : 'border-slate-700 text-slate-300 hover:bg-slate-800'
                    }`}
                  >
                    Bands
                  </button>
                </>
              )}
            </div>
          </div>

          {activeTab === 'analytics' && (
            <div className="mt-3 space-y-4">
              <div className="grid gap-4 xl:grid-cols-[minmax(0,1.5fr)_minmax(300px,0.85fr)]">
                <SectionCard
                  title="NVOL Timeseries"
                  subtitle={`${formatHistorySourceLabel(resolvedHistorySource)} across ${filteredTimeseries.length} sessions`}
                >
                  {loading ? (
                    <div className="h-[380px] text-sm text-slate-400">Loading timeseries...</div>
                  ) : error ? (
                    <div className="h-[380px] text-sm text-rose-400">{error}</div>
                  ) : filteredTimeseries.length === 0 ? (
                    <div className="h-[380px] text-sm text-slate-500">No historical surface data available.</div>
                  ) : (
                    <PlotlyNvolChart
                      series={nvolSeries}
                      title={`NVOL | ${formatHistorySourceLabel(resolvedHistorySource)}`}
                      height={380}
                    />
                  )}
                </SectionCard>

                <SectionCard
                  title="Window Summary"
                  subtitle={
                    filteredTimeseries.length
                      ? `${formatLongDate(filteredTimeseries[0].date)} to ${formatLongDate(filteredTimeseries[filteredTimeseries.length - 1].date)}`
                      : 'No loaded history in the selected range'
                  }
                >
                  <MetricRow
                    label="Current NVOL"
                    value={currentTimeseriesPoint ? `${formatNumber(currentTimeseriesPoint.nvol, 2)} bpvol` : '--'}
                  />
                  <MetricRow label="Trades in range" value={String(filteredTradeSummary.tradeCount)} />
                  <MetricRow label="Trades / active day" value={formatRate(filteredTradeSummary.tradesPerDay, 2)} />
                  <MetricRow label="Avg gap" value={formatDurationMs(filteredTradeSummary.avgGapMs)} />
                  <MetricRow label="Avg BPVol" value={formatTradeMetricValue('bpvol', filteredTradeSummary.avgBpvol)} />
                  <MetricRow label="Median BPVol" value={formatTradeMetricValue('bpvol', filteredTradeSummary.medianBpvol)} />
                  <MetricRow label="Avg notional" value={formatNotional(filteredTradeSummary.avgNotional)} />
                  <MetricRow label="Median notional" value={formatNotional(filteredTradeSummary.medianNotional)} />
                  <MetricRow label="Avg premium" value={formatCompactAmount(filteredTradeSummary.avgPremium)} />
                  <MetricRow label="Median premium" value={formatCompactAmount(filteredTradeSummary.medianPremium)} />
                  <MetricRow
                    label="First trade"
                    value={formatFullTimestamp(filteredTradeSummary.firstTradeTimestamp)}
                  />
                  <MetricRow
                    label="Last trade"
                    value={formatFullTimestamp(filteredTradeSummary.lastTradeTimestamp)}
                  />
                </SectionCard>
              </div>

              <div className="grid gap-4 xl:grid-cols-[minmax(0,1.35fr)_minmax(300px,0.65fr)]">
                <SectionCard
                  title="SDR Prints Timeline"
                  subtitle={`${formatTradeTimelineMetricLabel(tradeTimelineMetric)} view for ${filteredTrades.length} mapped prints`}
                >
                  <div className="h-72">
                    {tradeTimelineData.length === 0 ? (
                      <div className="text-sm text-slate-500">No mapped trades in the selected range.</div>
                    ) : (
                      <ResponsiveContainer width="100%" height="100%">
                        {tradeTimelineMetric === 'bpvol' ? (
                          <LineChart data={tradeTimelineData}>
                            <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
                            <XAxis
                              dataKey="timeKey"
                              tick={{ fill: '#94a3b8', fontSize: 10 }}
                              minTickGap={20}
                              tickFormatter={(value) => formatTradeAxisLabel(Number(value), historyRange)}
                            />
                            <YAxis
                              tick={{ fill: '#94a3b8', fontSize: 10 }}
                              tickFormatter={(value) => formatTradeMetricValue(tradeTimelineMetric, Number(value), false)}
                              label={{
                                value: formatTradeTimelineMetricLabel(tradeTimelineMetric),
                                angle: -90,
                                position: 'insideLeft',
                                fill: '#94a3b8',
                                fontSize: 10
                              }}
                            />
                            <TimeseriesAnnotations
                              distributionValues={tradeDistributionValues}
                              currentValue={latestTimelinePoint?.value ?? null}
                              currentTimeLabel={latestTimelinePoint?.timeKey ?? null}
                              showSigmaBands={showTradeSigmaBands}
                              formatValue={(value) => formatTradeMetricValue(tradeTimelineMetric, value)}
                              showHighlight={Boolean(latestTimelinePoint)}
                            />
                            <Tooltip content={<TradeTimelineTooltip metric={tradeTimelineMetric} />} />
                            <Line
                              type="monotone"
                              dataKey="value"
                              name={formatTradeTimelineMetricLabel(tradeTimelineMetric)}
                              stroke={getTradeMetricColor(tradeTimelineMetric)}
                              strokeWidth={2}
                              dot={{ r: 2, fill: getTradeMetricColor(tradeTimelineMetric) }}
                              activeDot={{ r: 4, fill: getTradeMetricColor(tradeTimelineMetric) }}
                              connectNulls
                            />
                          </LineChart>
                        ) : (
                          <BarChart data={tradeTimelineData}>
                            <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
                            <XAxis
                              dataKey="timeKey"
                              tick={{ fill: '#94a3b8', fontSize: 10 }}
                              minTickGap={20}
                              tickFormatter={(value) => formatTradeAxisLabel(Number(value), historyRange)}
                            />
                            <YAxis
                              tick={{ fill: '#94a3b8', fontSize: 10 }}
                              tickFormatter={(value) => formatTradeMetricValue(tradeTimelineMetric, Number(value), false)}
                              label={{
                                value: formatTradeTimelineMetricLabel(tradeTimelineMetric),
                                angle: -90,
                                position: 'insideLeft',
                                fill: '#94a3b8',
                                fontSize: 10
                              }}
                            />
                            <TimeseriesAnnotations
                              distributionValues={tradeDistributionValues}
                              currentValue={latestTimelinePoint?.value ?? null}
                              currentTimeLabel={latestTimelinePoint?.timeKey ?? null}
                              showSigmaBands={showTradeSigmaBands}
                              formatValue={(value) => formatTradeMetricValue(tradeTimelineMetric, value)}
                              showHighlight={Boolean(latestTimelinePoint)}
                            />
                            <Tooltip content={<TradeTimelineTooltip metric={tradeTimelineMetric} />} />
                            <Bar
                              dataKey="value"
                              name={formatTradeTimelineMetricLabel(tradeTimelineMetric)}
                              fill={getTradeMetricColor(tradeTimelineMetric)}
                              radius={[3, 3, 0, 0]}
                            />
                          </BarChart>
                        )}
                      </ResponsiveContainer>
                    )}
                  </div>
                </SectionCard>

                <SectionCard
                  title="SDR Trade Summary"
                  subtitle={
                    filteredTradeSummary.platformBreakdown.length
                      ? `${filteredTradeSummary.platformBreakdown.length} active platform bucket${filteredTradeSummary.platformBreakdown.length === 1 ? '' : 's'}`
                      : 'No platform mix available'
                  }
                >
                  <MetricRow label="Total notional" value={formatNotional(filteredTradeSummary.totalNotional)} />
                  <MetricRow label="Total premium" value={formatCompactAmount(filteredTradeSummary.totalPremium)} />
                  <MetricRow label="Active days" value={String(filteredTradeSummary.activeDays ?? '--')} />
                  <MetricRow label="Range start" value={formatFullTimestamp(filteredTradeSummary.firstTradeTimestamp)} />
                  <MetricRow label="Range end" value={formatFullTimestamp(filteredTradeSummary.lastTradeTimestamp)} />

                  <div className="mt-4 space-y-2">
                    <div className="text-[11px] font-semibold uppercase tracking-[0.2em] text-slate-500">
                      Platform Mix
                    </div>
                    {filteredTradeSummary.platformBreakdown.length === 0 && (
                      <div className="text-[11px] text-slate-500">No platform mix available.</div>
                    )}
                    {filteredTradeSummary.platformBreakdown.slice(0, 6).map((entry) => {
                      const sharePct = filteredTradeSummary.tradeCount
                        ? (entry.count / filteredTradeSummary.tradeCount) * 100
                        : 0
                      return (
                        <div key={entry.platform} className="space-y-1">
                          <div className="flex items-center justify-between gap-3 text-[11px]">
                            <span className="text-slate-300">{entry.platform}</span>
                            <span className="font-mono text-slate-100">
                              {entry.count} | {sharePct.toFixed(0)}%
                            </span>
                          </div>
                          <div className="h-1.5 rounded-full bg-slate-900">
                            <div
                              className="h-full rounded-full bg-sky-400/70"
                              style={{ width: `${sharePct}%` }}
                            />
                          </div>
                        </div>
                      )
                    })}
                  </div>
                </SectionCard>
              </div>

              <SectionCard
                title="Recent SDR Prints"
                subtitle={`Latest ${recentTrades.length} mapped prints in the selected range`}
              >
                <div className="grid gap-2 lg:grid-cols-2">
                  {recentTrades.length === 0 && (
                    <div className="text-sm text-slate-500">No mapped trade history in range.</div>
                  )}
                  {recentTrades.map((trade) => (
                    <TradeHistoryRow
                      key={`${trade.packageId}-${trade.executionTimestamp}`}
                      trade={trade}
                    />
                  ))}
                </div>
              </SectionCard>
            </div>
          )}

          {activeTab === 'history' && (
            <div className="mt-3 grid gap-4 xl:grid-cols-[minmax(280px,0.7fr)_minmax(0,1.3fr)]">
              <SectionCard
                title="Full Trade History"
                subtitle={`Complete mapped history for ${cell.expiry}x${cell.tenor}`}
              >
                <MetricRow label="Total trades" value={String(detail?.tradeHistoryStats.tradeCount ?? 0)} />
                <MetricRow
                  label="First trade"
                  value={formatFullTimestamp(detail?.tradeHistoryStats.firstTradeTimestamp ?? null)}
                />
                <MetricRow
                  label="Last trade"
                  value={formatFullTimestamp(detail?.tradeHistoryStats.lastTradeTimestamp ?? null)}
                />
                <MetricRow
                  label="Trades / active day"
                  value={formatRate(detail?.tradeHistoryStats.tradesPerDay ?? null, 2)}
                />
                <MetricRow
                  label="Avg gap"
                  value={formatDurationMs(detail?.tradeHistoryStats.avgGapMs ?? null)}
                />
                <MetricRow
                  label="Avg BPVol"
                  value={formatTradeMetricValue('bpvol', detail?.tradeHistoryStats.avgBpvol ?? null)}
                />
                <MetricRow
                  label="Avg notional"
                  value={formatNotional(detail?.tradeHistoryStats.avgNotional ?? null)}
                />
                <MetricRow
                  label="Avg premium"
                  value={formatCompactAmount(detail?.tradeHistoryStats.avgPremium ?? null)}
                />
              </SectionCard>

              <SectionCard
                title="Print Log"
                subtitle={
                  detail?.tradeHistoryStats.lastTradeTimestamp
                    ? `Most recent print ${formatFullTimestamp(detail.tradeHistoryStats.lastTradeTimestamp)}`
                    : 'No mapped trade history'
                }
              >
                <div className="max-h-[34rem] space-y-2 overflow-y-auto pr-1">
                  {(detail?.tradeHistory ?? []).length === 0 && (
                    <div className="text-sm text-slate-500">No mapped trade history.</div>
                  )}
                  {(detail?.tradeHistory ?? []).map((trade) => (
                    <TradeHistoryRow
                      key={`${trade.packageId}-${trade.executionTimestamp}`}
                      trade={trade}
                    />
                  ))}
                </div>
              </SectionCard>
            </div>
          )}
        </div>
      </div>
    </Dialog>
  )
}
