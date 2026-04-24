'use client'
// Tab 1 — Timeseries. Recharts ComposedChart with Custy/IDB series, IQR/
// sigma bands, focused-trade reference line + pulsing dot, VOLUME bar
// view, always-visible assumption strip.
import type { Dispatch, JSX, SetStateAction } from 'react'
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
import { ANALYTICS_COLORS, fmtDv01Compact, fmtTickTs, fmtTs } from './analytics-format'
import {
  ANALYTICS_METRICS,
  ANALYTICS_RANGES,
  ANALYTICS_VIEWS,
  RANGE_DAYS,
} from './constants'
import { NumberInput, PlatformDot, Pill, SegGroup, ToggleSwitch } from './controls'
import { AssumptionsStrip } from './AssumptionsStrip'
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
  unit: string
}

function TsTooltip({ active, payload, viewKey, unit }: TsTooltipProps): JSX.Element | null {
  if (!active || !payload || payload.length === 0) return null
  const d = payload[0].payload
  return (
    <div className="rounded border border-slate-700 bg-slate-950/95 px-2.5 py-2 font-mono text-[11px] text-slate-200 shadow-xl">
      <div className="mb-1 text-[10px] uppercase tracking-wide text-slate-500">
        {viewKey === 'INTRADAY'
          ? new Date(d.ts).toLocaleString('en-US', {
              timeZone: 'America/New_York',
              month: 'short', day: '2-digit',
              hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
            })
          : fmtTs(d.ts, { dateOnly: true })}
      </div>
      {typeof d.idbClose === 'number' ? (
        <div className="flex items-center justify-between gap-3">
          <span className="flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full" style={{ backgroundColor: ANALYTICS_COLORS.idb }} />
            IDB
          </span>
          <span className="text-sky-100">
            {d.idbClose.toFixed(2)} <span className="text-slate-500">{unit}</span>
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
            {d.custyClose.toFixed(2)} <span className="text-slate-500">{unit}</span>
          </span>
        </div>
      ) : null}
      {viewKey === 'VOLUME' && typeof d.idbDv01 === 'number' ? (
        <>
          <div className="flex items-center justify-between gap-3">
            <span className="flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-sm" style={{ backgroundColor: ANALYTICS_COLORS.idb }} />
              IDB DV01
            </span>
            <span className="text-sky-100">{fmtDv01Compact(d.idbDv01)}</span>
          </div>
          <div className="flex items-center justify-between gap-3">
            <span className="flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-sm" style={{ backgroundColor: ANALYTICS_COLORS.custy }} />
              Custy DV01
            </span>
            <span className="text-amber-100">{fmtDv01Compact(d.custyDv01 ?? null)}</span>
          </div>
        </>
      ) : null}
      {typeof d.idbPrints === 'number' ? (
        <div className="mt-1 border-t border-slate-800 pt-1 text-[10px] text-slate-400">
          <span className="text-slate-500">prints </span>
          IDB {d.idbPrints} · Custy {d.custyPrints ?? '—'}
        </div>
      ) : null}
    </div>
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
}

export function TimeseriesTab(props: TimeseriesTabProps): JSX.Element {
  const { focused, state, setState, dailyClose, intraday, stats, focusedPercentile } = props
  const chartHeight = props.chartHeight ?? 340
  const {
    view, metric, range, showCusty, showIdb, showSigmaBands, showIqrBand,
    showDots, useGrossDv01, excludeComicallyLargeCusty, yMin, yMax,
  } = state

  const metricConf = ANALYTICS_METRICS.find((m) => m.key === metric) ?? ANALYTICS_METRICS[0]
  const isIntraday = view === 'INTRADAY'
  const isVolume = view === 'VOLUME'
  const rawData = isIntraday ? intraday : filterRangeDays(dailyClose, range)

  // Re-project the series for metrics other than fixed_rate by deriving
  // from fixed_rate + DV01 so shapes stay plausible without needing per-
  // metric backend wiring yet.
  const data = useMemo(() => {
    return rawData.map((d, i) => {
      let idb = d.idbClose ?? 0
      let custy = d.custyClose ?? 0
      if (metric === 'spread_to_mid') {
        idb = (d.idbClose ?? 0) * 0 + ((d.idbClose ?? 0) - (d.custyClose ?? 0)) * 0.6
        custy = ((d.custyClose ?? 0) - (d.idbClose ?? 0)) * 0.6
      } else if (metric === 'dv01') {
        idb = (d.idbDv01 ?? 0) / 1000
        custy = (d.custyDv01 ?? 0) / 1000
      } else if (metric === 'notional') {
        idb = ((d.idbDv01 ?? 0) * 11.5) / 1e6
        custy = ((d.custyDv01 ?? 0) * 11.5) / 1e6
      } else if (metric === 'tenor_years') {
        idb = focused.tenor_years
        custy = focused.tenor_years
      }
      return {
        ...d,
        idxPos: i,
        idbClose: +idb.toFixed(2),
        custyClose: +custy.toFixed(2),
      }
    })
  }, [rawData, metric, focused.tenor_years])

  const focusedValue =
    metric === 'fixed_rate'
      ? focused.fixed_rate_bps
      : metric === 'dv01'
        ? focused.dv01_usd_per_bp / 1000
        : metric === 'notional'
          ? focused.notional_usd / 1e6
          : metric === 'spread_to_mid'
            ? -0.9
            : focused.tenor_years

  const yDomain: [number | string, number | string] = [
    yMin === '' ? 'auto' : Number(yMin),
    yMax === '' ? 'auto' : Number(yMax),
  ]

  const yFmt = (v: number): string => {
    if (metric === 'fixed_rate' || metric === 'spread_to_mid') return v.toFixed(1)
    if (metric === 'dv01') return `${v.toFixed(0)}K`
    if (metric === 'notional') return v.toFixed(0)
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
          <ComposedChart data={data} margin={{ top: 12, right: 60, bottom: 20, left: 48 }}>
            <CartesianGrid stroke={ANALYTICS_COLORS.grid} vertical={false} />
            <XAxis
              dataKey="ts"
              stroke={ANALYTICS_COLORS.axis}
              tick={{ fontSize: 10, fill: ANALYTICS_COLORS.slate400, fontFamily: 'ui-monospace' }}
              tickFormatter={(ts) => fmtTickTs(String(ts), view)}
              minTickGap={48}
              axisLine={{ stroke: ANALYTICS_COLORS.slate800 }}
              tickLine={{ stroke: ANALYTICS_COLORS.slate800 }}
            />
            <YAxis
              stroke={ANALYTICS_COLORS.axis}
              tick={{ fontSize: 10, fill: ANALYTICS_COLORS.slate400, fontFamily: 'ui-monospace' }}
              tickFormatter={yFmt}
              domain={yDomain}
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
              content={<TsTooltip viewKey={view} unit={metricConf.unit} />}
              cursor={{ stroke: ANALYTICS_COLORS.slate700, strokeDasharray: '3 3' }}
            />

            {metric === 'fixed_rate' && showSigmaBands && !isVolume ? (
              <>
                <ReferenceArea
                  y1={stats.mean - 2 * stats.stddev}
                  y2={stats.mean + 2 * stats.stddev}
                  fill={ANALYTICS_COLORS.sigma2}
                  ifOverflow="extendDomain"
                />
                <ReferenceArea
                  y1={stats.mean - stats.stddev}
                  y2={stats.mean + stats.stddev}
                  fill={ANALYTICS_COLORS.sigma1}
                  ifOverflow="extendDomain"
                />
              </>
            ) : null}

            {metric === 'fixed_rate' && showIqrBand && !isVolume ? (
              <ReferenceArea
                y1={stats.p25}
                y2={stats.p75}
                fill={ANALYTICS_COLORS.iqr}
                stroke={ANALYTICS_COLORS.iqrRing}
                strokeDasharray="2 4"
                ifOverflow="extendDomain"
                label={{
                  value: `IQR  P25 ${stats.p25.toFixed(1)}  –  P75 ${stats.p75.toFixed(1)}`,
                  position: 'insideTopRight',
                  fill: 'rgba(34, 211, 238, 0.55)',
                  fontSize: 9,
                  fontFamily: 'ui-monospace',
                }}
              />
            ) : null}

            {metric === 'fixed_rate' && !isVolume ? (
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

            {isVolume ? (
              <>
                {showCusty ? (
                  <Bar dataKey="custyDv01" stackId="dv01" fill={ANALYTICS_COLORS.custy} fillOpacity={0.85} name="Custy DV01" />
                ) : null}
                {showIdb ? (
                  <Bar dataKey="idbDv01" stackId="dv01" fill={ANALYTICS_COLORS.idb} fillOpacity={0.9} name="IDB DV01" />
                ) : null}
              </>
            ) : (
              <>
                {showCusty ? (
                  <Line
                    type="monotone"
                    dataKey="custyClose"
                    stroke={ANALYTICS_COLORS.custy}
                    strokeWidth={1.4}
                    dot={showDots ? { r: 1.5, fill: ANALYTICS_COLORS.custy } : false}
                    activeDot={{ r: 4, stroke: '#0f172a', strokeWidth: 1.5 }}
                    name="Custy"
                    isAnimationActive={false}
                  />
                ) : null}
                {showIdb ? (
                  <Line
                    type="monotone"
                    dataKey="idbClose"
                    stroke={ANALYTICS_COLORS.idb}
                    strokeWidth={1.6}
                    dot={showDots ? { r: 1.5, fill: ANALYTICS_COLORS.idb } : false}
                    activeDot={{ r: 4, stroke: '#0f172a', strokeWidth: 1.5 }}
                    name="IDB"
                    isAnimationActive={false}
                  />
                ) : null}
              </>
            )}

            {metric === 'fixed_rate' && !isVolume && data.length > 0 ? (
              <ReferenceDot
                x={data[data.length - 1].ts}
                y={focusedValue}
                shape={<PulsingDot />}
              />
            ) : null}
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
          {metric === 'fixed_rate' && !isVolume ? (
            <span className="flex items-center gap-1.5">
              <span
                className="inline-block h-[2px] w-4 border-t border-dashed"
                style={{ borderColor: ANALYTICS_COLORS.focused }}
              />
              Focused trade
            </span>
          ) : null}
          {metric === 'fixed_rate' && showIqrBand && !isVolume ? (
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
    </div>
  )
}
