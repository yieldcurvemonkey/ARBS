'use client'
// Tab 2 — Trade Rarity. Basis toggle, percentile rows, stacked histogram
// with KDE + cumulative-% + IQR band + focused-trade dot, recency scorecard.
import type { Dispatch, JSX, ReactNode, SetStateAction } from 'react'
import { useMemo } from 'react'
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceArea,
  ReferenceDot,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { ANALYTICS_COLORS, fmtDaysAgo, sequenceColor } from './analytics-format'
import { ZONE_BG, ZONE_BORDER, ZONE_TEXT } from './constants'
import { PlatformDot, Pill, SegGroup } from './controls'
import { AssumptionsStrip } from './AssumptionsStrip'
import {
  findFocusedHistogramBin,
  focusedHistogramValue,
  formatHistogramValue,
  statsForHistogram,
} from './TradeRarityTab.helpers'
import type {
  AnalyticsMetricKey,
  DistributionStats,
  FocusedTrade,
  HistogramBin,
  MetricRow,
  RarityBasis,
  RarityState,
  RecencyBucket,
} from './analytics-types'

function PercentileRow(props: { metric: MetricRow; isPrimary?: boolean }): JSX.Element {
  const { metric, isPrimary } = props
  const pct = metric.percentile ?? 0
  const zone = metric.zone ?? 'typical'
  const rowSize = isPrimary ? 'text-[13px]' : 'text-[11px]'
  const rowHeight = isPrimary ? 'h-10' : 'h-9'
  return (
    <div
      className={`flex items-center gap-2 ${rowHeight} ${rowSize} rounded border border-slate-800 bg-slate-950/60 px-2 font-mono text-slate-200 ${
        isPrimary ? `border-l-[3px] ${ZONE_BORDER[zone]}` : ''
      }`}
    >
      <div className="flex min-w-[150px] items-center gap-1.5 text-[10px] uppercase tracking-wide text-slate-400">
        {isPrimary ? <span className="text-[9px] text-indigo-300">PRIMARY</span> : null}
        <span>{metric.label}</span>
      </div>
      <div className="min-w-[92px] text-right text-slate-100 tabular-nums">{metric.displayValue}</div>
      <div className="min-w-[48px] text-right text-slate-400">
        {metric.showPercentile && metric.percentile !== null ? `P${Math.round(metric.percentile)}` : '—'}
      </div>
      <div className="relative h-2 w-[180px] overflow-hidden rounded-full bg-slate-800">
        {metric.showPercentile ? (
          <div
            className={`h-full rounded-full transition-all duration-500 ease-out ${ZONE_BG[zone]}`}
            style={{ width: `${Math.min(Math.max(pct, 0), 100)}%` }}
          />
        ) : null}
      </div>
      <div className={`min-w-[160px] text-[10px] ${metric.showPercentile ? ZONE_TEXT[zone] : 'text-slate-500'}`}>
        {metric.descriptor}
      </div>
      <div className="ml-auto min-w-[72px] text-right text-[10px] text-slate-500">
        N={metric.sampleSize.toLocaleString()}
      </div>
    </div>
  )
}

interface HistogramTooltipProps {
  active?: boolean
  payload?: Array<{ payload: HistogramBin }>
  unit?: string
  metric?: 'fixed_rate' | 'dv01' | 'notional'
}

function HistogramTooltip({ active, payload, unit = 'bps', metric = 'fixed_rate' }: HistogramTooltipProps): JSX.Element | null {
  if (!active || !payload || payload.length === 0) return null
  const d = payload[0].payload
  return (
    <div className="rounded border border-slate-700 bg-slate-950/95 px-2.5 py-2 font-mono text-[11px] text-slate-200 shadow-xl">
      <div className="mb-1 text-[10px] uppercase tracking-wide text-slate-500">
        {formatHistogramValue(d.binStart, metric)} – {formatHistogramValue(d.binEnd, metric)} {unit}
      </div>
      <div className="flex items-center justify-between gap-3">
        <span className="flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-sm" style={{ backgroundColor: ANALYTICS_COLORS.idb }} />IDB
        </span>
        <span className="text-sky-100">{d.idb}</span>
      </div>
      <div className="flex items-center justify-between gap-3">
        <span className="flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-sm" style={{ backgroundColor: ANALYTICS_COLORS.custy }} />Custy
        </span>
        <span className="text-amber-100">{d.custy}</span>
      </div>
      <div className="mt-1 border-t border-slate-800 pt-1 text-[10px] text-slate-400">
        cumulative {d.cumPct.toFixed(1)}%
      </div>
    </div>
  )
}

function RecencyCard(props: {
  title: string
  accent?: 'emerald' | 'amber' | 'sky' | 'fuchsia' | 'slate'
  children: ReactNode
}): JSX.Element {
  const accentBorder =
    props.accent === 'emerald' ? 'border-l-emerald-500/60'
    : props.accent === 'amber' ? 'border-l-amber-500/60'
    : props.accent === 'sky' ? 'border-l-sky-500/60'
    : props.accent === 'fuchsia' ? 'border-l-fuchsia-500/60'
    : 'border-l-slate-700'
  return (
    <div className={`flex flex-col gap-1 rounded border border-slate-800 border-l-[3px] ${accentBorder} bg-slate-950/60 p-2.5`}>
      <div className="text-[9.5px] uppercase tracking-wider text-slate-500">{props.title}</div>
      {props.children}
    </div>
  )
}

export interface TradeRarityTabProps {
  focused: FocusedTrade
  // Multi-trade dock — supplied in sequence mode. Single-mode
  // rendering is byte-for-byte unchanged when sequence is undefined.
  // Phase F2 wires the N-dot histogram overlay against this list.
  sequence?: readonly FocusedTrade[]
  state: RarityState
  setState: Dispatch<SetStateAction<RarityState>>
  bins: HistogramBin[]
  // UX-02: server tells us which metric the bins are in + the bin
  // width so the histogram axis labels and tooltip render with the
  // right units (bps / USD-per-bp / USD millions).
  binMetric?: 'fixed_rate' | 'dv01' | 'notional'
  binWidth?: number
  stats: DistributionStats
  binStats?: DistributionStats
  metricRows: MetricRow[]
  // Recency may be null when the bucket has no qualifying recent prints
  // — the histogram + percentile rows still render, only the recency
  // cards are hidden in that case.
  recency: RecencyBucket | null
  // Focused-trade percentile pre-computed server-side for the active
  // basis (combined/custy/idb). Parent picks which member to pass.
  focusedPercentile: number
  histogramHeight?: number
  // True while the underlying /rarity fetch is in flight. Drives the
  // skeleton loading state so the trader sees layout-sized placeholders
  // instead of a spinner that pops the chart in/out of view.
  loading?: boolean
  // Histogram brushing — clicking a Bar fires this callback with the
  // bin's [start, end] bounds and the metric. Parent (AnalyticsPanel)
  // wires it to the tape's per-column filter URL state.
  onBinBrush?: (binStart: number, binEnd: number, metric: 'fixed_rate' | 'dv01' | 'notional') => void
}

const BIN_METRIC_UNITS: Record<NonNullable<TradeRarityTabProps['binMetric']>, string> = {
  fixed_rate: 'bps',
  dv01: 'USD/bp',
  notional: 'USD mm',
}

const BIN_METRIC_AXIS_LABELS: Record<NonNullable<TradeRarityTabProps['binMetric']>, string> = {
  fixed_rate: 'Fixed Rate (bps)',
  dv01: 'DV01 (USD/bp)',
  notional: 'Notional (USD mm)',
}

function PercentileSkeleton(): JSX.Element {
  return (
    <div className="flex h-9 items-center gap-2 rounded border border-slate-800 bg-slate-950/60 px-2">
      <div className="h-3 w-[140px] animate-pulse rounded bg-slate-800" />
      <div className="h-3 w-[80px] animate-pulse rounded bg-slate-800" />
      <div className="h-3 w-[40px] animate-pulse rounded bg-slate-800" />
      <div className="h-2 w-[180px] animate-pulse rounded-full bg-slate-800" />
      <div className="ml-auto h-3 w-[64px] animate-pulse rounded bg-slate-800" />
    </div>
  )
}

export function TradeRarityTab(props: TradeRarityTabProps): JSX.Element {
  const { focused, sequence, state, setState, bins, stats, metricRows, recency, focusedPercentile, loading, onBinBrush } = props
  const overlayTrades = sequence ?? []
  const histogramHeight = props.histogramHeight ?? 280
  const binMetric = props.binMetric ?? 'fixed_rate'
  const binWidth = props.binWidth ?? 1
  const histogramStats = statsForHistogram(props.binStats ?? stats, stats)
  const binMetricUnit = BIN_METRIC_UNITS[binMetric]
  const binMetricAxisLabel = BIN_METRIC_AXIS_LABELS[binMetric]
  const { basis, histogramMetric, settingsOpen, primaryTol, sizeTol } = state
  const isInitialLoad = loading && bins.length === 0
  const noSamples = !loading && stats.count === 0
  const handleBarClick = (data: { binStart: number; binEnd: number } | null | undefined) => {
    if (!onBinBrush || !data || binMetric !== 'fixed_rate') return
    onBinBrush(data.binStart, data.binEnd, binMetric)
  }

  // P2-06: half-open intervals (>=binStart && <binEnd) drop the
  // focused trade onto a phantom "no bin" when its rate exactly equals
  // the last bin's binEnd, causing the reference dot + "Focused sits
  // in bin [—] · 0 prints" footer to silently disappear at the
  // distribution's upper edge. Allow the last bin to be inclusive at
  // the top so the dot lands cleanly.
  const focusedBinValue = focusedHistogramValue(focused, binMetric)
  const focusedBin = findFocusedHistogramBin(bins, focusedBinValue)

  const primaryPct = focusedPercentile
  const selectedMetricPct =
    binMetric === 'fixed_rate'
      ? primaryPct
      : metricRows.find((m) => m.key === binMetric)?.percentile ?? primaryPct

  const displayMetricRows = useMemo(
    () => [...metricRows].sort((a, b) => Number(Boolean(b.primary)) - Number(Boolean(a.primary))),
    [metricRows],
  )

  const displayBins = useMemo(
    () =>
      bins.map((b) => ({
        ...b,
        custy: basis === 'idb' ? 0 : b.custy,
        idb: basis === 'custy' ? 0 : b.idb,
      })),
    [bins, basis],
  )

  return (
    <div className="flex flex-col gap-2.5">
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex flex-col gap-1">
          <div className="text-[10px] uppercase tracking-wide text-slate-500">Basis</div>
          <div className="flex gap-1">
            <Pill active={basis === 'combined'} onClick={() => setState((s) => ({ ...s, basis: 'combined' }))}>
              Combined
            </Pill>
            <Pill active={basis === 'custy'} onClick={() => setState((s) => ({ ...s, basis: 'custy' }))} accent="amber">
              <PlatformDot platform="CUSTY" size={6} />
              <span className="ml-1">Custy</span>
            </Pill>
            <Pill active={basis === 'idb'} onClick={() => setState((s) => ({ ...s, basis: 'idb' }))} accent="sky">
              <PlatformDot platform="IDB" size={6} />
              <span className="ml-1">IDB</span>
            </Pill>
          </div>
        </div>

        <SegGroup<AnalyticsMetricKey>
          label="Histogram metric"
          value={histogramMetric}
          onChange={(v) => setState((s) => ({ ...s, histogramMetric: v }))}
          options={[
            { key: 'fixed_rate', label: 'Fixed Rate (bps)' },
            { key: 'dv01', label: 'DV01 (USD/bp)' },
            { key: 'notional', label: 'Notional (USD mm)' },
          ]}
        />

        <div className="relative ml-auto">
          <button
            type="button"
            onClick={() => setState((s) => ({ ...s, settingsOpen: !s.settingsOpen }))}
            className={`rounded border px-2 py-1 font-mono text-[10.5px] transition-colors ${
              settingsOpen
                ? 'border-indigo-500/40 bg-indigo-500/15 text-indigo-100'
                : 'border-slate-700 text-slate-300 hover:bg-slate-800'
            }`}
          >
            ⚙ Similarity thresholds
          </button>
          {settingsOpen ? (
            <div className="absolute right-0 top-9 z-10 w-72 rounded border border-slate-700 bg-slate-950/95 p-3 shadow-xl">
              <div className="mb-2 text-[10px] uppercase tracking-wider text-slate-500">
                What counts as "similar"
              </div>
              <label className="mb-2 block text-[11px] font-mono text-slate-300">
                <div className="flex justify-between">
                  <span>Rate tolerance</span>
                  <span className="text-slate-100">±{primaryTol.toFixed(1)} bps</span>
                </div>
                <input
                  type="range"
                  min={0.5}
                  max={10}
                  step={0.1}
                  value={primaryTol}
                  onChange={(e) => setState((s) => ({ ...s, primaryTol: +e.target.value }))}
                  className="w-full accent-indigo-400"
                />
              </label>
              <label className="block text-[11px] font-mono text-slate-300">
                <div className="flex justify-between">
                  <span>Size tolerance</span>
                  <span className="text-slate-100">±{Math.round(sizeTol * 100)}%</span>
                </div>
                <input
                  type="range"
                  min={0.05}
                  max={1}
                  step={0.05}
                  value={sizeTol}
                  onChange={(e) => setState((s) => ({ ...s, sizeTol: +e.target.value }))}
                  className="w-full accent-indigo-400"
                />
              </label>
              <div className="mt-2 text-[10px] text-slate-500">
                These drive "last similar trade", "frequency last 90d", and similarity count.
              </div>
            </div>
          ) : null}
        </div>
      </div>

      <AssumptionsStrip
        items={[
          { label: 'Bucket', value: focused.tape_label },
          { label: 'Histogram', value: binMetricAxisLabel },
          { label: 'Units', value: binMetricUnit, dim: true },
          {
            label: 'Basis',
            value: basis === 'combined' ? 'Custy + IDB' : basis === 'custy' ? 'Custy only' : 'IDB only',
          },
          { label: 'Lookback', value: '90 days' },
          { label: 'N', value: stats.count.toLocaleString() },
          { label: 'Tolerance', value: `±${primaryTol.toFixed(1)} bps · ${Math.round(sizeTol * 100)}% size` },
        ]}
        source="/api/usd-swaps-tape-v2/rarity"
      />

      {isInitialLoad ? (
        <div className="flex flex-col gap-1" data-testid="rarity-loading-skeleton">
          <PercentileSkeleton />
          <PercentileSkeleton />
          <PercentileSkeleton />
        </div>
      ) : noSamples ? (
        <div
          className="rounded border border-dashed border-slate-700 bg-slate-900/40 p-3 font-mono text-[11px] text-slate-300"
          data-testid="rarity-empty-state"
        >
          <span className="font-semibold text-slate-200">No prints in lookback window.</span>
          <div className="mt-1 text-[10.5px] text-slate-500">
            The {focused.tape_label} bucket hasn't traded in the configured 90-day window —
            either the tenor is too rare, the trade type doesn't print to this tape, or the
            most recent print is older than the lookback. Widen the rate / size tolerance in
            the gear menu, or pin the trade and check back after the next ingest run.
          </div>
        </div>
      ) : (
        <div className="flex flex-col gap-1">
          {displayMetricRows.map((m) => (
            <PercentileRow
              key={m.key}
              metric={{
                ...m,
                percentile: m.key === 'fixed_rate' ? primaryPct : m.percentile,
              }}
              isPrimary={m.primary}
            />
          ))}
        </div>
      )}

      <div className="grid grid-cols-[1.5fr_1fr] gap-2.5">
        <div className="flex flex-col gap-1.5 rounded border border-slate-800 bg-slate-950/60 p-2.5">
          <div className="flex items-center justify-between">
            <div className="text-[10px] uppercase tracking-wider text-slate-500">
              Distribution · bin width {formatHistogramValue(binWidth, binMetric)} {binMetricUnit}
            </div>
            <div className="flex items-center gap-3 font-mono text-[10px] text-slate-400">
              <span>μ {formatHistogramValue(histogramStats.mean, binMetric)}</span>
              <span>σ {formatHistogramValue(histogramStats.stddev, binMetric)}</span>
              <span>P25 {formatHistogramValue(histogramStats.p25, binMetric)}</span>
              <span>P50 {formatHistogramValue(histogramStats.median, binMetric)}</span>
              <span>P75 {formatHistogramValue(histogramStats.p75, binMetric)}</span>
            </div>
          </div>
          <div style={{ height: histogramHeight }}>
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart data={displayBins} margin={{ top: 8, right: 48, bottom: 18, left: 40 }}>
                <CartesianGrid stroke={ANALYTICS_COLORS.grid} vertical={false} />
                <XAxis
                  dataKey="mid"
                  stroke={ANALYTICS_COLORS.axis}
                  type="number"
                  domain={[bins[0]?.binStart ?? 0, bins[bins.length - 1]?.binEnd ?? 100]}
                  tick={{ fontSize: 10, fill: ANALYTICS_COLORS.slate400, fontFamily: 'ui-monospace' }}
                  tickFormatter={(v) => Number(v).toFixed(0)}
                  axisLine={{ stroke: ANALYTICS_COLORS.slate800 }}
                  tickLine={{ stroke: ANALYTICS_COLORS.slate800 }}
                  label={{
                    value: binMetricAxisLabel,
                    position: 'insideBottom',
                    offset: -8,
                    style: {
                      fill: ANALYTICS_COLORS.slate400, fontSize: 10, fontFamily: 'ui-monospace',
                      textTransform: 'uppercase', letterSpacing: '0.05em',
                    },
                  }}
                />
                <YAxis
                  yAxisId="count"
                  stroke={ANALYTICS_COLORS.axis}
                  tick={{ fontSize: 10, fill: ANALYTICS_COLORS.slate400, fontFamily: 'ui-monospace' }}
                  axisLine={{ stroke: ANALYTICS_COLORS.slate800 }}
                  tickLine={{ stroke: ANALYTICS_COLORS.slate800 }}
                  label={{
                    value: 'Count', angle: -90, position: 'insideLeft', offset: 10,
                    style: {
                      fill: ANALYTICS_COLORS.slate400, fontSize: 10, fontFamily: 'ui-monospace',
                      textTransform: 'uppercase', letterSpacing: '0.05em',
                    },
                  }}
                />
                <YAxis
                  yAxisId="pct"
                  orientation="right"
                  stroke={ANALYTICS_COLORS.axis}
                  domain={[0, 100]}
                  tick={{ fontSize: 10, fill: ANALYTICS_COLORS.slate400, fontFamily: 'ui-monospace' }}
                  axisLine={{ stroke: ANALYTICS_COLORS.slate800 }}
                  tickLine={{ stroke: ANALYTICS_COLORS.slate800 }}
                  tickFormatter={(v) => `${v}%`}
                  label={{
                    value: 'Cumulative', angle: 90, position: 'insideRight', offset: 10,
                    style: {
                      fill: ANALYTICS_COLORS.slate400, fontSize: 10, fontFamily: 'ui-monospace',
                      textTransform: 'uppercase', letterSpacing: '0.05em',
                    },
                  }}
                />
                <Tooltip content={<HistogramTooltip unit={binMetricUnit} metric={binMetric} />} cursor={{ fill: 'rgba(148,163,184,0.06)' }} />
                <ReferenceArea
                  yAxisId="count"
                  x1={histogramStats.p25}
                  x2={histogramStats.p75}
                  fill="rgba(34, 211, 238, 0.10)"
                  stroke="rgba(34, 211, 238, 0.3)"
                  strokeDasharray="2 4"
                />
                <Bar
                  yAxisId="count"
                  dataKey="idb"
                  stackId="a"
                  fill={ANALYTICS_COLORS.idb}
                  fillOpacity={0.85}
                  onClick={handleBarClick as any}
                  style={onBinBrush && binMetric === 'fixed_rate' ? { cursor: 'pointer' } : undefined}
                />
                <Bar
                  yAxisId="count"
                  dataKey="custy"
                  stackId="a"
                  fill={ANALYTICS_COLORS.custy}
                  fillOpacity={0.85}
                  onClick={handleBarClick as any}
                  style={onBinBrush && binMetric === 'fixed_rate' ? { cursor: 'pointer' } : undefined}
                />
                <Line
                  yAxisId="count"
                  type="monotone"
                  dataKey="kdeScaled"
                  stroke="#e2e8f0"
                  strokeWidth={1.2}
                  dot={false}
                  strokeDasharray="3 3"
                />
                <Line
                  yAxisId="pct"
                  type="monotone"
                  dataKey="cumPct"
                  stroke={ANALYTICS_COLORS.cumulative}
                  strokeWidth={1.2}
                  dot={false}
                />
                <ReferenceLine
                  yAxisId="count"
                  x={focusedBinValue}
                  stroke={ANALYTICS_COLORS.focused}
                  strokeWidth={1.5}
                  strokeDasharray="4 4"
                  label={{
                    value: `${formatHistogramValue(focusedBinValue, binMetric)}  P${Math.round(selectedMetricPct ?? primaryPct)}`,
                    position: 'top',
                    fill: ANALYTICS_COLORS.focused,
                    fontSize: 10,
                    fontFamily: 'ui-monospace',
                  }}
                />
                {focusedBin ? (
                  <ReferenceDot
                    yAxisId="count"
                    x={focusedBin.mid}
                    y={focusedBin.total}
                    r={5}
                    fill={ANALYTICS_COLORS.focused}
                    stroke="#0f172a"
                    strokeWidth={1.5}
                  />
                ) : null}

                {/*
                  Multi-trade dock — N reference dots overlaid on the
                  shared histogram, one per selected trade. Each dot
                  is positioned at the bin its rate falls into and
                  carries the sequence palette colour. The dot's
                  default Recharts tooltip surfaces the trade label
                  via the data-testid + colour cue; richer tooltip
                  identifying which trade lives in a follow-up after
                  Recharts shape-prop typing is settled.
                */}
                {overlayTrades.map((trade, i) => {
                  const value = focusedHistogramValue(trade, binMetric)
                  const bin = findFocusedHistogramBin(bins, value)
                  if (!bin) return null
                  const colour = sequenceColor(i)
                  return (
                    <ReferenceDot
                      key={`seq-rarity-dot-${trade.id}`}
                      data-testid={`sequence-rarity-dot-${i}`}
                      yAxisId="count"
                      x={bin.mid}
                      y={bin.total}
                      r={4}
                      fill={colour}
                      stroke="#0f172a"
                      strokeWidth={1}
                    />
                  )
                })}
              </ComposedChart>
            </ResponsiveContainer>
          </div>
          <div className="flex flex-wrap items-center gap-3 border-t border-slate-800 pt-1.5 font-mono text-[10px] text-slate-400">
            <span className="flex items-center gap-1.5">
              <span className="inline-block h-2 w-3 rounded-sm" style={{ backgroundColor: ANALYTICS_COLORS.idb }} />
              IDB
            </span>
            <span className="flex items-center gap-1.5">
              <span className="inline-block h-2 w-3 rounded-sm" style={{ backgroundColor: ANALYTICS_COLORS.custy }} />
              Custy
            </span>
            <span className="flex items-center gap-1.5">
              <span className="inline-block h-[2px] w-4 border-t border-dashed border-slate-300" />
              KDE
            </span>
            <span className="flex items-center gap-1.5">
              <span className="inline-block h-[2px] w-4" style={{ backgroundColor: ANALYTICS_COLORS.cumulative }} />
              Cumulative %
            </span>
            <span className="flex items-center gap-1.5">
              <span className="inline-block h-2 w-3 rounded-sm" style={{ backgroundColor: 'rgba(34,211,238,0.22)' }} />
              IQR
            </span>
            <span className="flex items-center gap-1.5">
              <span
                className="inline-block h-[2px] w-4 border-t border-dashed"
                style={{ borderColor: ANALYTICS_COLORS.focused }}
              />
              Focused
            </span>
            <span className="ml-auto text-slate-500">
              Focused sits in bin [{focusedBin ? `${formatHistogramValue(focusedBin.binStart, binMetric)}, ${formatHistogramValue(focusedBin.binEnd, binMetric)}` : '—'}] ·{' '}
              {focusedBin ? focusedBin.total : 0} prints
            </span>
          </div>
        </div>

        <div className="flex flex-col gap-1.5">
          <RecencyCard title="Last similar trade" accent="emerald">
            {recency?.lastSimilar ? (
              <>
                <div className="flex items-baseline gap-2">
                  <span className="font-mono text-[16px] text-slate-100">
                    {fmtDaysAgo(recency.lastSimilar.daysAgo)}
                  </span>
                  <span className="font-mono text-[10px] text-slate-500">{recency.lastSimilar.date}</span>
                </div>
                <div className="font-mono text-[10.5px] text-slate-400">
                  rate <span className="text-slate-200">{recency.lastSimilar.value.toFixed(2)}</span>
                  <span className="text-slate-500"> bps</span>
                  <span className="mx-1.5 text-slate-700">·</span>
                  <PlatformDot platform={recency.lastSimilar.platform} size={6} />
                  <span
                    className={`ml-1 ${
                      recency.lastSimilar.platform === 'CUSTY' ? 'text-amber-200' : 'text-sky-200'
                    }`}
                  >
                    {recency.lastSimilar.platform}
                  </span>
                  <span className="mx-1.5 text-slate-700">·</span>
                  <span className="text-slate-300">{recency.lastSimilar.venue}</span>
                </div>
              </>
            ) : (
              <div
                className="font-mono text-[10.5px] text-slate-500"
                title="No prints within the configured rate ± size tolerance window"
              >
                No similar trade in lookback window
              </div>
            )}
          </RecencyCard>

          <RecencyCard title="Frequency · last 90 days" accent="sky">
            {recency?.frequency90d ? (
              <>
                <div className="flex items-baseline gap-2">
                  <span className="font-mono text-[16px] text-slate-100">{recency.frequency90d.count}</span>
                  <span className="font-mono text-[10px] text-slate-400">
                    similar trades · avg{' '}
                    <span className="text-slate-200">{recency.frequency90d.avgIntervalDays.toFixed(1)}</span> days apart
                  </span>
                </div>
                <div className="h-1 rounded-full bg-slate-800">
                  <div
                    className="h-full rounded-full bg-sky-500/70"
                    style={{ width: `${Math.min(recency.frequency90d.count / 60, 1) * 100}%` }}
                  />
                </div>
              </>
            ) : (
              <div className="font-mono text-[10.5px] text-slate-500">No frequency data</div>
            )}
          </RecencyCard>

          <RecencyCard title="Bucket rank" accent="fuchsia">
            {recency?.bucketRank ? (
              <>
                <div className="flex items-baseline gap-2">
                  <span className="font-mono text-[16px] text-slate-100">
                    #{recency.bucketRank.rank}
                    <span className="text-slate-500"> / {recency.bucketRank.total.toLocaleString()}</span>
                  </span>
                  <span className="font-mono text-[10px] text-slate-500">by {recency.bucketRank.by}</span>
                </div>
                <div className="font-mono text-[10px] text-slate-400">
                  top{' '}
                  <span className="text-fuchsia-300">
                    {((recency.bucketRank.rank / recency.bucketRank.total) * 100).toFixed(1)}%
                  </span>{' '}
                  in the {focused.tape_label} bucket this quarter
                </div>
              </>
            ) : (
              <div
                className="font-mono text-[10.5px] text-slate-500"
                title="Bucket rank requires a focused notional; the trade may be an outright with missing leg notional"
              >
                Rank unavailable for this trade
              </div>
            )}
          </RecencyCard>

          <RecencyCard title={`All-time records · ${focused.tape_label}`} accent="amber">
            {recency?.allTimeRecord ? (
              <div className="flex flex-col gap-1 font-mono text-[10.5px]">
                {recency.allTimeRecord.largestNotional ? (
                  <div className="flex items-baseline justify-between">
                    <span className="text-slate-500">largest notional</span>
                    <span className="text-slate-200">{recency.allTimeRecord.largestNotional.displayValue}</span>
                    <span className="text-slate-500">{recency.allTimeRecord.largestNotional.date}</span>
                  </div>
                ) : null}
                {recency.allTimeRecord.highestRate ? (
                  <div className="flex items-baseline justify-between">
                    <span className="text-slate-500">high rate</span>
                    <span className="text-slate-200">{recency.allTimeRecord.highestRate.displayValue} bps</span>
                    <span className="text-slate-500">{recency.allTimeRecord.highestRate.date}</span>
                  </div>
                ) : null}
                {recency.allTimeRecord.lowestRate ? (
                  <div className="flex items-baseline justify-between">
                    <span className="text-slate-500">low rate</span>
                    <span className="text-slate-200">{recency.allTimeRecord.lowestRate.displayValue} bps</span>
                    <span className="text-slate-500">{recency.allTimeRecord.lowestRate.date}</span>
                  </div>
                ) : null}
              </div>
            ) : (
              <div className="font-mono text-[10.5px] text-slate-500">No historical prints</div>
            )}
          </RecencyCard>
        </div>
      </div>
    </div>
  )
}

// RarityBasis is used by the component via state — explicit re-export so
// consumers outside this file can wire state against the same union.
export type { RarityBasis }
