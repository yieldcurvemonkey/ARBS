'use client'
// Tab 1 — Timeseries. Recharts ComposedChart with Custy/IDB series, IQR/
// sigma bands, focused-trade reference line + pulsing dot, VOLUME bar
// view, always-visible assumption strip.
import type { Dispatch, JSX, SetStateAction } from 'react'
import { useMemo, useState } from 'react'
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
import { ANALYTICS_COLORS, fmtDv01Compact, sequenceColor } from './analytics-format'
import {
  ANALYTICS_METRICS,
  ANALYTICS_RANGES,
  ANALYTICS_VIEWS,
  RANGE_DAYS,
} from './constants'
import { NumberInput, PlatformDot, Pill, SegGroup, ToggleSwitch } from './controls'
import {
  CANONICAL_BUCKETS,
  canonicalDisplayLabel,
} from '../../utils/canonicalDisplay'
import { AssumptionsStrip } from './AssumptionsStrip'
import {
  effectiveTimeseriesMetric,
  focusedTimeseriesValue,
  formatTimeseriesTickParts,
  formatTimeseriesTooltipTime,
  projectTimeseriesPoint,
} from './TimeseriesTab.helpers'
import type {
  AnalyticsMetricKey,
  AnalyticsRangeKey,
  AnalyticsViewKey,
  DistributionStats,
  FocusedTrade,
  TimeseriesPointAug,
  TimeseriesState,
} from './analytics-types'

function filterRangeDays(data: TimeseriesPointAug[], rangeKey: AnalyticsRangeKey): TimeseriesPointAug[] {
  const n = RANGE_DAYS[rangeKey] ?? 365
  return data.slice(-n)
}

interface TsTooltipProps {
  active?: boolean
  payload?: Array<{ payload: TimeseriesPointAug }>
  viewKey: AnalyticsViewKey
  metricKey: AnalyticsMetricKey
  unit: string
  focused: FocusedTrade
}

function formatTooltipMetric(value: number, metricKey: AnalyticsMetricKey): string {
  if (metricKey === 'dv01') return fmtDv01Compact(value, { signNegativeOnly: true })
  if (metricKey === 'notional') return value.toFixed(1)
  return value.toFixed(2)
}

function TooltipRow(props: {
  label: string
  value: string
  accent?: 'sky' | 'amber' | 'slate'
}): JSX.Element {
  const valueColor =
    props.accent === 'sky' ? 'text-sky-100'
    : props.accent === 'amber' ? 'text-amber-100'
    : 'text-slate-100'
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="text-slate-500">{props.label}</span>
      <span className={`${valueColor} text-right tabular-nums`}>{props.value}</span>
    </div>
  )
}

function TsTooltip({ active, payload, metricKey, unit, focused }: TsTooltipProps): JSX.Element | null {
  if (!active || !payload || payload.length === 0) return null
  const d = payload[0].payload
  const hoveredTime = formatTimeseriesTooltipTime(d.ts)
  const focusedTime = formatTimeseriesTooltipTime(focused.execution_start)
  return (
    <div className="w-[285px] rounded border border-slate-700 bg-slate-950/95 px-2.5 py-2 font-mono text-[11px] text-slate-200 shadow-xl">
      <div className="mb-1.5 grid grid-cols-[72px_1fr] gap-x-2 gap-y-0.5 text-[10px]">
        <span className="uppercase tracking-wide text-slate-500">Date</span>
        <span className="text-slate-200">{hoveredTime.date}</span>
        <span className="uppercase tracking-wide text-slate-500">Timestamp</span>
        <span className="text-slate-200">{hoveredTime.timestamp} {hoveredTime.timezone}</span>
      </div>
      <div className="border-t border-slate-800 pt-1">
        <div className="mb-0.5 text-[9.5px] uppercase tracking-wider text-slate-500">
          Hovered print bucket
        </div>
      {typeof d.idbClose === 'number' ? (
        <div className="flex items-center justify-between gap-3">
          <span className="flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full" style={{ backgroundColor: ANALYTICS_COLORS.idb }} />
            IDB
          </span>
          <span className="text-sky-100">
            {formatTooltipMetric(d.idbClose, metricKey)} <span className="text-slate-500">{unit}</span>
          </span>
        </div>
      ) : null}
      {typeof d.custyClose === 'number' ? (
        <div className="flex items-center justify-between gap-3">
          <span className="flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full" style={{ backgroundColor: ANALYTICS_COLORS.custy }} />
            Custy
          </span>
          <span className="text-amber-100">
            {formatTooltipMetric(d.custyClose, metricKey)} <span className="text-slate-500">{unit}</span>
          </span>
        </div>
      ) : null}
      {typeof d.idbDv01 === 'number' || typeof d.custyDv01 === 'number' ? (
        <TooltipRow
          label="DV01 IDB/Custy"
          value={`${fmtDv01Compact(d.idbDv01 ?? null, { signNegativeOnly: true })} / ${fmtDv01Compact(d.custyDv01 ?? null, { signNegativeOnly: true })}`}
        />
      ) : null}
      {typeof d.idbNotional === 'number' || typeof d.custyNotional === 'number' ? (
        <TooltipRow
          label="Notional IDB/Custy"
          value={`${((d.idbNotional ?? 0) / 1e6).toFixed(0)} / ${((d.custyNotional ?? 0) / 1e6).toFixed(0)} MM`}
        />
      ) : null}
      {typeof d.idbPrints === 'number' ? (
        <div className="mt-1 border-t border-slate-800 pt-1 text-[10px] text-slate-400">
          <span className="text-slate-500">prints </span>
          IDB {d.idbPrints} · Custy {d.custyPrints ?? '—'}
        </div>
      ) : null}
      </div>
      <div className="mt-1 border-t border-slate-800 pt-1">
        <div className="mb-0.5 text-[9.5px] uppercase tracking-wider text-slate-500">
          Focused trade
        </div>
        <TooltipRow
          label="Trade"
          value={`${focused.side} ${focused.tape_label}`}
          accent={focused.platform === 'IDB' ? 'sky' : 'amber'}
        />
        <TooltipRow label="Rate" value={`${focused.fixed_rate_bps.toFixed(2)} bps`} />
        <TooltipRow
          label="DV01 / Notional"
          value={`${fmtDv01Compact(focused.dv01_usd_per_bp)} / ${(focused.notional_usd / 1e6).toFixed(0)} MM`}
        />
        <TooltipRow label="Venue" value={`${focused.platform} ${focused.venue}`} />
        <TooltipRow label="Executed" value={`${focusedTime.date} ${focusedTime.timestamp} ${focusedTime.timezone}`} />
      </div>
    </div>
  )
}

function TsAxisTick(props: {
  x?: number
  y?: number
  payload?: { value?: string | number }
  viewKey: AnalyticsViewKey
}): JSX.Element | null {
  if (props.x == null || props.y == null) return null
  const parts = formatTimeseriesTickParts(String(props.payload?.value ?? ''), props.viewKey)
  return (
    <g transform={`translate(${props.x},${props.y})`}>
      <text
        x={0}
        y={0}
        dy={4}
        textAnchor="middle"
        fill={ANALYTICS_COLORS.slate400}
        fontSize={10}
        fontFamily="ui-monospace"
      >
        {parts.primary}
      </text>
      {parts.secondary ? (
        <text
          x={0}
          y={12}
          dy={4}
          textAnchor="middle"
          fill={ANALYTICS_COLORS.slate500}
          fontSize={9}
          fontFamily="ui-monospace"
        >
          {parts.secondary}
        </text>
      ) : null}
    </g>
  )
}

// Pulsing circle marking the focused trade's most recent print on the chart.
function PulsingDot(props: { cx?: number; cy?: number }): JSX.Element | null {
  if (props.cx == null || props.cy == null) return null
  return (
    <g>
      <circle cx={props.cx} cy={props.cy} r={10} fill={ANALYTICS_COLORS.focused} opacity={0.18}>
        <animate attributeName="r" values="6;14;6" dur="2s" repeatCount="indefinite" />
        <animate attributeName="opacity" values="0.35;0;0.35" dur="2s" repeatCount="indefinite" />
      </circle>
      <circle cx={props.cx} cy={props.cy} r={4} fill={ANALYTICS_COLORS.focused} stroke="#0f172a" strokeWidth={1.5} />
    </g>
  )
}

export interface TimeseriesTabProps {
  focused: FocusedTrade
  state: TimeseriesState
  setState: Dispatch<SetStateAction<TimeseriesState>>
  dailyClose: TimeseriesPointAug[]
  intraday: TimeseriesPointAug[]
  stats: DistributionStats
  focusedPercentile: number
  chartHeight?: number
  // Multi-trade dock — when present, the tab renders N reference
  // lines + N reference dots overlaid on top of the existing
  // single-trade pulsing dot. Single-mode rendering is byte-for-
  // byte unchanged when sequence is null/undefined.
  sequence?: readonly FocusedTrade[]
}

export function TimeseriesTab(props: TimeseriesTabProps): JSX.Element {
  const { focused, state, setState, dailyClose, intraday, stats, focusedPercentile, sequence } = props
  const chartHeight = props.chartHeight ?? 340

  // Multi-trade dock — sequence-mode overlay state. The legend chip
  // for each trade has a click target that toggles the trade's id
  // in/out of `hiddenTradeIds`; reference lines/dots check the set
  // before rendering. Single-mode is unaffected because sequence
  // defaults to undefined and the .map below short-circuits on it.
  const [hiddenTradeIds, setHiddenTradeIds] = useState<Set<string>>(() => new Set())
  const overlayTrades = sequence ?? []
  const {
    view, metric, range, showCusty, showIdb, showSigmaBands, showIqrBand,
    showDots, useGrossDv01, excludeComicallyLargeCusty, yMin, yMax,
  } = state

  const effectiveMetric = effectiveTimeseriesMetric(metric, view)
  const metricConf = ANALYTICS_METRICS.find((m) => m.key === effectiveMetric) ?? ANALYTICS_METRICS[0]
  const isIntraday = view === 'INTRADAY'
  // DV01 always renders as stacked bars; VOLUME view forces bars for any
  // metric (trader's vega-style volume chart ask). Fixed rate, spread,
  // and tenor stay as line plots.
  const renderBars =
    view === 'VOLUME' ||
    effectiveMetric === 'dv01' ||
    effectiveMetric === 'notional'
  const rawData = isIntraday ? intraday : filterRangeDays(dailyClose, range)

  // Re-project the series for metrics other than fixed_rate. Null stays
  // null — the chart draws gaps on days where one side didn't print
  // instead of dropping to zero, which would otherwise drag the y-axis
  // down to the floor and flatten the visible signal.
  const data = useMemo(() => {
    return rawData.map((d, i) => projectTimeseriesPoint(d, i, effectiveMetric, focused))
  }, [rawData, effectiveMetric, focused])

  const focusedValue = focusedTimeseriesValue(focused, effectiveMetric)

  // Recharts treats numeric domain values as hard limits only when paired
  // with a non-string companion. When yMin is set but yMax is 'auto',
  // Recharts falls back to its data-driven auto-extent. Force both sides
  // explicit (min set → use 'dataMax + 1%' for the other end so the chart
  // clamps predictably).
  const yDomainLow: number | string = yMin === '' ? 'auto' : Number(yMin)
  const yDomainHigh: number | string = yMax === '' ? 'auto' : Number(yMax)
  const yDomain: [number | string, number | string] = [yDomainLow, yDomainHigh]
  const allowDataOverflow = yMin !== '' || yMax !== ''

  const yFmt = (v: number): string => {
    if (effectiveMetric === 'fixed_rate' || effectiveMetric === 'spread_to_mid') return v.toFixed(1)
    if (effectiveMetric === 'dv01') {
      const abs = Math.abs(v)
      if (abs >= 1e6) return `${(v / 1e6).toFixed(1)}M`
      if (abs >= 1e3) return `${Math.round(v / 1e3)}K`
      return v.toFixed(0)
    }
    if (effectiveMetric === 'notional') return v.toFixed(0)
    return String(v)
  }

  const yLabel = `${metricConf.label} (${metricConf.unit})`

  const basisText = showCusty && showIdb ? 'Custy + IDB' : showCusty ? 'Custy' : showIdb ? 'IDB' : 'none'

  return (
    <div className="flex flex-col gap-2.5">
      {/* control rail */}
      <div className="flex flex-wrap items-start gap-x-3 gap-y-2">
        <div className="flex flex-col gap-1">
          <div className="text-[10px] uppercase tracking-wide text-slate-500">Series</div>
          <div className="flex gap-1">
            <Pill
              active={showCusty}
              onClick={() => setState((s) => ({ ...s, showCusty: !s.showCusty }))}
              accent="amber"
            >
              <PlatformDot platform="CUSTY" size={6} />
              <span className="ml-1">Custy</span>
            </Pill>
            <Pill
              active={showIdb}
              onClick={() => setState((s) => ({ ...s, showIdb: !s.showIdb }))}
              accent="sky"
            >
              <PlatformDot platform="IDB" size={6} />
              <span className="ml-1">IDB</span>
            </Pill>
          </div>
        </div>

        <SegGroup<AnalyticsMetricKey>
          label="Metric"
          value={metric}
          onChange={(v) => setState((s) => ({ ...s, metric: v }))}
          options={ANALYTICS_METRICS.map((m) => ({ key: m.key, label: `${m.label} (${m.unit})` }))}
        />

        <SegGroup<AnalyticsViewKey>
          label="View"
          value={view}
          onChange={(v) => setState((s) => ({ ...s, view: v }))}
          options={ANALYTICS_VIEWS}
          accent="cyan"
        />

        <SegGroup<AnalyticsRangeKey>
          label="Range"
          value={range}
          onChange={(v) => setState((s) => ({ ...s, range: v }))}
          options={ANALYTICS_RANGES}
        />

        {/*
          Phase 4 canonical bucket selector. When the user picks a
          canonical underlier the chart pivots from `groupBy=tape_label`
          to `groupBy=canonical&value=<key>` (see
          useAnalyticsTimeseries) so e.g. SOFR-OIS, Term-SOFR, and
          Fed-Funds OIS each appear as one self-consistent series
          regardless of how many SDR-feed string variants the
          Phase 4 canonicaliser collapsed into them.
        */}
        <div className="flex flex-col gap-1">
          <div className="text-[10px] uppercase tracking-wide text-slate-500">
            Bucket
          </div>
          <select
            aria-label="Bucket grouping"
            className="rounded border border-slate-700 bg-slate-900 px-2 py-1 font-mono text-[11px] text-slate-200 focus:border-indigo-400 focus:outline-none"
            value={
              state.groupBy === 'canonical' && state.canonicalKey
                ? `canonical:${state.canonicalKey}`
                : 'tape_label'
            }
            onChange={(e) => {
              const v = e.target.value
              if (v === 'tape_label') {
                setState((s) => ({ ...s, groupBy: 'tape_label', canonicalKey: null }))
              } else if (v.startsWith('canonical:')) {
                const key = v.slice('canonical:'.length)
                setState((s) => ({ ...s, groupBy: 'canonical', canonicalKey: key }))
              }
            }}
          >
            <option value="tape_label">Tape label (focused)</option>
            {CANONICAL_BUCKETS.map((b) => (
              <option key={b.key} value={`canonical:${b.key}`}>
                {canonicalDisplayLabel(b.key)} — {b.longLabel}
              </option>
            ))}
          </select>
        </div>

        <div className="ml-auto flex flex-col gap-1">
          <div className="text-[10px] uppercase tracking-wide text-slate-500">Overlays</div>
          <div className="flex gap-1">
            <ToggleSwitch
              label="IQR"
              on={showIqrBand}
              onChange={(v) => setState((s) => ({ ...s, showIqrBand: v }))}
              accent="cyan"
              hint="Shade the interquartile range [P25, P75]"
            />
            <ToggleSwitch
              label="±σ bands"
              on={showSigmaBands}
              onChange={(v) => setState((s) => ({ ...s, showSigmaBands: v }))}
              accent="sky"
              hint="Shade ±1σ / ±2σ around the mean"
            />
            <ToggleSwitch
              label="Dots"
              on={showDots}
              onChange={(v) => setState((s) => ({ ...s, showDots: v }))}
              accent="emerald"
              hint="Draw one dot per data point"
            />
          </div>
        </div>
      </div>

      {/* second control row */}
      <div className="flex flex-wrap items-center gap-2">
        <ToggleSwitch
          label={`DV01: ${useGrossDv01 ? 'Gross' : 'Net'}`}
          on={useGrossDv01}
          onChange={(v) => setState((s) => ({ ...s, useGrossDv01: v }))}
          accent="amber"
          hint="Gross sums the absolute value per print; Net keeps sign"
        />
        <ToggleSwitch
          label="Exclude comically large custy notional"
          on={excludeComicallyLargeCusty}
          onChange={(v) => setState((s) => ({ ...s, excludeComicallyLargeCusty: v }))}
          accent="emerald"
          hint="Drop custy prints > 5× median so outliers don't dominate the scale. Trader-requested default: ON."
        />
        <div className="ml-auto flex items-center gap-1.5">
          <NumberInput
            label="Y min"
            value={yMin}
            onChange={(v) => setState((s) => ({ ...s, yMin: v }))}
            placeholder="auto"
          />
          <NumberInput
            label="Y max"
            value={yMax}
            onChange={(v) => setState((s) => ({ ...s, yMax: v }))}
            placeholder="auto"
          />
          <button
            type="button"
            onClick={() => setState((s) => ({ ...s, yMin: '', yMax: '' }))}
            className="rounded border border-slate-800 bg-slate-900/60 px-2 py-1 font-mono text-[10px] text-slate-400 hover:text-slate-200"
          >
            reset
          </button>
        </div>
      </div>

      <AssumptionsStrip
        items={[
          { label: 'Bucket', value: focused.tape_label },
          { label: 'Metric', value: metricConf.label },
          { label: 'Units', value: metricConf.unit, dim: true },
          { label: 'Basis', value: basisText },
          { label: 'Range', value: range === 'CUSTOM' ? '2025-10-24 → 2026-04-24' : range },
          { label: 'View', value: ANALYTICS_VIEWS.find((v) => v.key === view)?.label ?? view },
          { label: 'N', value: String(data.length) },
          {
            label: 'Excl. outliers',
            value: excludeComicallyLargeCusty ? 'ON' : 'OFF',
            trailing: (
              <span
                className={`ml-1 rounded px-1 py-[1px] text-[9px] ring-1 ${
                  excludeComicallyLargeCusty
                    ? 'bg-emerald-500/15 text-emerald-200 ring-emerald-500/30'
                    : 'bg-amber-500/15 text-amber-200 ring-amber-500/30'
                }`}
              >
                {excludeComicallyLargeCusty ? 'clean' : 'raw'}
              </span>
            ),
          },
        ]}
        source="/api/usd-swaps-tape-v2/timeseries"
      />

      {/* chart */}
      <div
        className="relative rounded border border-slate-800 bg-slate-950/60 p-2"
        style={{ height: chartHeight }}
      >
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={data} margin={{ top: 12, right: 60, bottom: 34, left: 48 }}>
            <CartesianGrid stroke={ANALYTICS_COLORS.grid} vertical={false} />
            <XAxis
              dataKey="ts"
              stroke={ANALYTICS_COLORS.axis}
              tick={<TsAxisTick viewKey={view} />}
              minTickGap={48}
              axisLine={{ stroke: ANALYTICS_COLORS.slate800 }}
              tickLine={{ stroke: ANALYTICS_COLORS.slate800 }}
              label={{
                value: view === 'INTRADAY' ? 'NY date / timestamp' : 'NY trade date',
                position: 'insideBottom',
                offset: -22,
                style: {
                  fill: ANALYTICS_COLORS.slate500,
                  fontSize: 9,
                  fontFamily: 'ui-monospace',
                  textTransform: 'uppercase',
                  letterSpacing: '0.05em',
                },
              }}
            />
            <YAxis
              stroke={ANALYTICS_COLORS.axis}
              tick={{ fontSize: 10, fill: ANALYTICS_COLORS.slate400, fontFamily: 'ui-monospace' }}
              tickFormatter={yFmt}
              domain={yDomain}
              allowDataOverflow={allowDataOverflow}
              axisLine={{ stroke: ANALYTICS_COLORS.slate800 }}
              tickLine={{ stroke: ANALYTICS_COLORS.slate800 }}
              label={{
                value: yLabel,
                angle: -90,
                position: 'insideLeft',
                offset: 10,
                style: {
                  fill: ANALYTICS_COLORS.slate400,
                  fontSize: 10,
                  fontFamily: 'ui-monospace',
                  textTransform: 'uppercase',
                  letterSpacing: '0.05em',
                },
              }}
            />
            <Tooltip
              content={<TsTooltip viewKey={view} metricKey={effectiveMetric} unit={metricConf.unit} focused={focused} />}
              cursor={{ stroke: ANALYTICS_COLORS.slate700, strokeDasharray: '3 3' }}
              allowEscapeViewBox={{ x: true, y: true }}
              offset={18}
              wrapperStyle={{ pointerEvents: 'none', zIndex: 20 }}
              position={{ x: 72, y: 8 }}
            />

            {effectiveMetric === 'fixed_rate' && showSigmaBands && !renderBars ? (
              <ReferenceArea
                y1={stats.mean - 2 * stats.stddev}
                y2={stats.mean + 2 * stats.stddev}
                fill={ANALYTICS_COLORS.sigma2}
                ifOverflow="hidden"
              />
            ) : null}
            {effectiveMetric === 'fixed_rate' && showSigmaBands && !renderBars ? (
              <ReferenceArea
                y1={stats.mean - stats.stddev}
                y2={stats.mean + stats.stddev}
                fill={ANALYTICS_COLORS.sigma1}
                ifOverflow="hidden"
              />
            ) : null}

            {effectiveMetric === 'fixed_rate' && showIqrBand && !renderBars ? (
              <ReferenceArea
                y1={stats.p25}
                y2={stats.p75}
                fill={ANALYTICS_COLORS.iqr}
                stroke={ANALYTICS_COLORS.iqrRing}
                strokeDasharray="2 4"
                ifOverflow="hidden"
                label={{
                  value: `IQR  P25 ${stats.p25.toFixed(1)}  –  P75 ${stats.p75.toFixed(1)}`,
                  position: 'insideTopRight',
                  fill: 'rgba(34, 211, 238, 0.55)',
                  fontSize: 9,
                  fontFamily: 'ui-monospace',
                }}
              />
            ) : null}

            {effectiveMetric === 'fixed_rate' && !renderBars ? (
              <ReferenceLine
                y={focusedValue}
                stroke={ANALYTICS_COLORS.focused}
                strokeDasharray="4 4"
                strokeWidth={1.25}
                label={{
                  value: `${focusedValue.toFixed(2)} ${metricConf.unit}  (P${Math.round(focusedPercentile)})`,
                  position: 'right',
                  fill: ANALYTICS_COLORS.focused,
                  fontSize: 10,
                  fontFamily: 'ui-monospace',
                  offset: 8,
                }}
              />
            ) : null}

            {renderBars && showCusty ? (
              <Bar
                dataKey="custyClose"
                stackId="dv01"
                fill={ANALYTICS_COLORS.custy}
                fillOpacity={0.85}
                name={`Custy ${metricConf.label}`}
              />
            ) : null}
            {renderBars && showIdb ? (
              <Bar
                dataKey="idbClose"
                stackId="dv01"
                fill={ANALYTICS_COLORS.idb}
                fillOpacity={0.9}
                name={`IDB ${metricConf.label}`}
              />
            ) : null}
            {!renderBars && showCusty ? (
              <Line
                type="monotone"
                dataKey="custyClose"
                stroke={ANALYTICS_COLORS.custy}
                strokeWidth={1.4}
                dot={showDots ? { r: 1.5, fill: ANALYTICS_COLORS.custy } : false}
                activeDot={{ r: 4, stroke: '#0f172a', strokeWidth: 1.5 }}
                name="Custy"
                isAnimationActive={false}
                connectNulls
              />
            ) : null}
            {!renderBars && showIdb ? (
              <Line
                type="monotone"
                dataKey="idbClose"
                stroke={ANALYTICS_COLORS.idb}
                strokeWidth={1.6}
                dot={showDots ? { r: 1.5, fill: ANALYTICS_COLORS.idb } : false}
                activeDot={{ r: 4, stroke: '#0f172a', strokeWidth: 1.5 }}
                name="IDB"
                isAnimationActive={false}
                connectNulls
              />
            ) : null}

            {effectiveMetric === 'fixed_rate' && !renderBars && data.length > 0 ? (
              <ReferenceDot
                x={data[data.length - 1].ts}
                y={focusedValue}
                shape={<PulsingDot />}
              />
            ) : null}

            {/*
              Multi-trade dock — N reference lines + N reference dots
              when `sequence` is supplied. Each entry gets a stable
              palette colour indexed by selection order. Trades in
              `hiddenTradeIds` skip rendering so the trader can
              declutter the chart via the legend below. Reference
              dots position the marker at the trade's
              execution_start when present, else fall back to the
              latest data point's ts so the dot is still visible.
            */}
            {effectiveMetric === 'fixed_rate' && !renderBars
              ? overlayTrades.map((trade, i) => {
                  if (hiddenTradeIds.has(trade.id)) return null
                  const colour = sequenceColor(i)
                  return (
                    <ReferenceLine
                      key={`seq-line-${trade.id}`}
                      data-testid={`sequence-reference-line-${i}`}
                      y={trade.fixed_rate_bps}
                      stroke={colour}
                      strokeDasharray="3 3"
                      strokeWidth={1}
                      ifOverflow="hidden"
                    />
                  )
                })
              : null}
            {effectiveMetric === 'fixed_rate' && !renderBars && data.length > 0
              ? overlayTrades.map((trade, i) => {
                  if (hiddenTradeIds.has(trade.id)) return null
                  const colour = sequenceColor(i)
                  const xValue = trade.execution_start ?? data[data.length - 1].ts
                  return (
                    <ReferenceDot
                      key={`seq-dot-${trade.id}`}
                      data-testid={`sequence-reference-dot-${i}`}
                      x={xValue}
                      y={trade.fixed_rate_bps}
                      r={3.5}
                      fill={colour}
                      stroke="#0f172a"
                      strokeWidth={1}
                      ifOverflow="hidden"
                    />
                  )
                })
              : null}
          </ComposedChart>
        </ResponsiveContainer>

        <div className="pointer-events-none absolute bottom-2 left-14 flex items-center gap-3 font-mono text-[10px] text-slate-400">
          {showCusty ? (
            <span className="flex items-center gap-1.5">
              <span className="inline-block h-[2px] w-4" style={{ backgroundColor: ANALYTICS_COLORS.custy }} />
              Custy
            </span>
          ) : null}
          {showIdb ? (
            <span className="flex items-center gap-1.5">
              <span className="inline-block h-[2px] w-4" style={{ backgroundColor: ANALYTICS_COLORS.idb }} />
              IDB
            </span>
          ) : null}
          {effectiveMetric === 'fixed_rate' && !renderBars ? (
            <span className="flex items-center gap-1.5">
              <span
                className="inline-block h-[2px] w-4 border-t border-dashed"
                style={{ borderColor: ANALYTICS_COLORS.focused }}
              />
              Focused trade
            </span>
          ) : null}
          {effectiveMetric === 'fixed_rate' && showIqrBand && !renderBars ? (
            <span className="flex items-center gap-1.5">
              <span
                className="inline-block h-2 w-3 rounded-sm"
                style={{ backgroundColor: 'rgba(34,211,238,0.25)' }}
              />
              IQR
            </span>
          ) : null}
        </div>
      </div>

      {/*
        Multi-trade dock — per-trade legend with show/hide toggles.
        Each chip shows the trade's tape_label + rate at colour
        index `i`; clicking the chip toggles the trade's id in/out
        of `hiddenTradeIds` so the trader can declutter overlapping
        overlays without losing the selection.
      */}
      {overlayTrades.length > 0 ? (
        <div
          data-testid="timeseries-sequence-legend"
          className="flex flex-wrap items-center gap-1 px-1 pt-1 font-mono text-[10px]"
        >
          <span className="text-slate-500">Sequence:</span>
          {overlayTrades.map((trade, i) => {
            const hidden = hiddenTradeIds.has(trade.id)
            const colour = sequenceColor(i)
            return (
              <button
                key={`legend-${trade.id}`}
                type="button"
                data-testid={`sequence-legend-chip-${i}`}
                title={`${trade.tape_label} — click to ${hidden ? 'show' : 'hide'} on chart`}
                onClick={() =>
                  setHiddenTradeIds((prev) => {
                    const next = new Set(prev)
                    if (next.has(trade.id)) next.delete(trade.id)
                    else next.add(trade.id)
                    return next
                  })
                }
                className={`inline-flex items-center gap-1 rounded border px-1.5 py-[1px] ${
                  hidden
                    ? 'border-slate-700 bg-transparent text-slate-500 line-through'
                    : 'border-slate-700 bg-slate-900/60 text-slate-200'
                }`}
              >
                <span
                  className="inline-block h-[6px] w-[6px] rounded-full"
                  style={{ backgroundColor: hidden ? 'transparent' : colour, border: hidden ? `1px solid ${colour}` : 'none' }}
                />
                <span className="truncate max-w-[180px]">{trade.tape_label}</span>
                <span className="text-slate-500">{trade.fixed_rate_bps.toFixed(1)}</span>
              </button>
            )
          })}
        </div>
      ) : null}
    </div>
  )
}
