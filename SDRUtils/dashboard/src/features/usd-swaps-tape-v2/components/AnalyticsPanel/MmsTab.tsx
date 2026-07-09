'use client'
// ABOUTME: MMS (matched-maturity swap / UST asset-swap) Analytics tab.
// 4-panel layout: summary stats strip, daily volume bar chart, maturity
// distribution chart, top CUSIPs table. Aggregates over the rows already
// loaded into the tape — no new API endpoint. Design doc §3d.
import type { Dispatch, JSX, SetStateAction } from 'react'
import { useMemo } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { UsdSwapTapeRow } from '../../types'
import type { MmsDistributionMetric, MmsState, MmsVolumeMetric, MmsWindow } from './analytics-types'
import type { UnderlierMixWindow } from '../../utils/underlierMix'
import { filterRowsToWindow } from '../../utils/underlierMix'
import {
  computeMmsSummary,
  computeMmsDailyVolume,
  computeMmsMaturityDistribution,
  computeMmsTopCusips,
} from '../../utils/mmsAnalytics'
import { ANALYTICS_COLORS, fmtDv01Compact, fmtNotionalMM } from './analytics-format'
import { Pill, SegGroup } from './controls'
import { MMS_DEFAULT_STATE } from './constants'

export interface MmsTabProps {
  rows: readonly UsdSwapTapeRow[]
  state: MmsState
  setState: Dispatch<SetStateAction<MmsState>>
}

// Map MmsWindow (lowercase 'ytd') to UnderlierMixWindow (uppercase 'YTD')
function toUnderlierWindow(w: MmsWindow): UnderlierMixWindow {
  if (w === 'ytd') return 'YTD'
  return w
}

const WINDOW_OPTIONS: Array<{ key: MmsWindow; label: string }> = [
  { key: 'today', label: 'Today' },
  { key: '7d', label: '7D' },
  { key: '30d', label: '30D' },
  { key: '90d', label: '90D' },
  { key: 'ytd', label: 'YTD' },
]

// Chart colors
const MMS_BAR_COLOR = '#818cf8'  // indigo-400
const MMS_BAR_ALT = '#6366f1'   // indigo-500
const SHARE_LINE_COLOR = '#f472b6' // pink-400
const MATURITY_COLORS = [
  '#818cf8', '#6366f1', '#a78bfa', '#8b5cf6', '#c084fc',
  '#7c3aed', '#5b21b6', '#4c1d95', '#4338ca', '#3730a3',
  '#312e81', '#1e1b4b', '#60a5fa', '#3b82f6', '#2563eb',
]

function StatCard({ label, value, sub }: { label: string; value: string; sub?: string }): JSX.Element {
  return (
    <div className="flex flex-col gap-0.5 rounded border border-slate-800 bg-slate-950/60 px-3 py-2">
      <div className="text-[9.5px] uppercase tracking-wider text-slate-500">{label}</div>
      <div className="font-mono text-[16px] tabular-nums text-slate-100">{value}</div>
      {sub ? <div className="font-mono text-[10px] text-slate-500">{sub}</div> : null}
    </div>
  )
}

function VolumeTooltip({
  active,
  payload,
  metric,
}: {
  active?: boolean
  payload?: Array<{ payload: { date: string; mmsCount: number; mmsDv01: number; share: number; totalCount: number; totalDv01: number } }>
  metric: MmsVolumeMetric
}): JSX.Element | null {
  if (!active || !payload || payload.length === 0) return null
  const d = payload[0].payload
  return (
    <div className="rounded border border-slate-700 bg-slate-950/95 px-2.5 py-2 font-mono text-[11px] text-slate-200 shadow-xl">
      <div className="mb-1 text-[10px] uppercase tracking-wide text-slate-500">{d.date}</div>
      <div className="flex justify-between gap-3">
        <span>MMS {metric === 'count' ? 'Count' : 'DV01'}</span>
        <span className="text-indigo-200">
          {metric === 'count' ? d.mmsCount : fmtDv01Compact(d.mmsDv01)}
        </span>
      </div>
      <div className="flex justify-between gap-3">
        <span>Total {metric === 'count' ? 'Count' : 'DV01'}</span>
        <span className="text-slate-300">
          {metric === 'count' ? d.totalCount : fmtDv01Compact(d.totalDv01)}
        </span>
      </div>
      <div className="mt-1 border-t border-slate-800 pt-1 text-[10px] text-slate-400">
        MMS share {(d.share * 100).toFixed(1)}%
      </div>
    </div>
  )
}

function DistributionTooltip({
  active,
  payload,
  metric,
}: {
  active?: boolean
  payload?: Array<{ payload: { mmyy: string; count: number; dv01: number; notional: number } }>
  metric: MmsDistributionMetric
}): JSX.Element | null {
  if (!active || !payload || payload.length === 0) return null
  const d = payload[0].payload
  const metricValue = metric === 'count' ? d.count : metric === 'dv01' ? d.dv01 : d.notional
  const metricLabel = metric === 'count' ? 'Count' : metric === 'dv01' ? 'DV01' : 'Notional'
  const formatted = metric === 'count'
    ? String(metricValue)
    : metric === 'dv01'
      ? fmtDv01Compact(metricValue)
      : `${fmtNotionalMM(metricValue)} MM`
  return (
    <div className="rounded border border-slate-700 bg-slate-950/95 px-2.5 py-2 font-mono text-[11px] text-slate-200 shadow-xl">
      <div className="mb-1 text-[10px] uppercase tracking-wide text-slate-500">MMYY {d.mmyy}</div>
      <div className="flex justify-between gap-3">
        <span>{metricLabel}</span>
        <span className="text-indigo-200">{formatted}</span>
      </div>
    </div>
  )
}

export function MmsTab({ rows, state, setState }: MmsTabProps): JSX.Element {
  const filteredRows = useMemo(
    () => filterRowsToWindow(rows, toUnderlierWindow(state.window)),
    [rows, state.window],
  )

  const summary = useMemo(() => computeMmsSummary(filteredRows), [filteredRows])
  const dailyVolume = useMemo(() => computeMmsDailyVolume(filteredRows), [filteredRows])
  const maturityDist = useMemo(
    () => computeMmsMaturityDistribution(filteredRows).slice(0, 15),
    [filteredRows],
  )
  const topCusips = useMemo(() => computeMmsTopCusips(filteredRows), [filteredRows])

  // Empty state
  if (summary.mmsCount === 0) {
    return (
      <div className="flex flex-col gap-3 p-3">
        <div className="flex flex-wrap items-center gap-2">
          {WINDOW_OPTIONS.map((w) => (
            <Pill
              key={w.key}
              active={state.window === w.key}
              onClick={() => setState((s) => ({ ...s, window: w.key }))}
              compact
            >
              {w.label}
            </Pill>
          ))}
        </div>
        <div className="rounded border border-dashed border-slate-700 bg-slate-900/40 p-4 font-mono text-[11px] text-slate-300">
          <span className="font-semibold text-slate-200">No MMS packages in loaded data.</span>
          <div className="mt-1 text-[10.5px] text-slate-500">
            No matched-maturity swap packages were found in the current window.
            Try expanding the time window or loading more data.
          </div>
        </div>
      </div>
    )
  }

  const volumeDataKey = state.volumeMetric === 'count' ? 'mmsCount' : 'mmsDv01'
  const distributionDataKey: MmsDistributionMetric = state.distributionMetric

  return (
    <div className="flex flex-col gap-3 p-3">
      {/* Window selector */}
      <div className="flex flex-wrap items-center gap-2">
        {WINDOW_OPTIONS.map((w) => (
          <Pill
            key={w.key}
            active={state.window === w.key}
            onClick={() => setState((s) => ({ ...s, window: w.key }))}
            compact
          >
            {w.label}
          </Pill>
        ))}
      </div>

      {/* Panel 1: Summary stats strip */}
      <div className="grid grid-cols-5 gap-2">
        <StatCard
          label="MMS Packages"
          value={String(summary.mmsCount)}
          sub={`of ${summary.totalCount} total`}
        />
        <StatCard
          label="% of Total"
          value={summary.totalCount > 0 ? `${((summary.mmsCount / summary.totalCount) * 100).toFixed(1)}%` : '0%'}
        />
        <StatCard
          label="MMS DV01"
          value={fmtDv01Compact(summary.mmsDv01)}
          sub={`of ${fmtDv01Compact(summary.totalDv01)} total`}
        />
        <StatCard
          label="DV01 Share"
          value={`${(summary.dv01Share * 100).toFixed(1)}%`}
        />
        <StatCard
          label="MMS Notional"
          value={`${fmtNotionalMM(summary.mmsNotional)} MM`}
          sub={`of ${fmtNotionalMM(summary.totalNotional)} MM total`}
        />
      </div>

      {/* Panel 2 + Panel 3 side by side */}
      <div className="grid grid-cols-2 gap-3">
        {/* Panel 2: Daily volume chart */}
        <div className="flex flex-col gap-1.5 rounded border border-slate-800 bg-slate-950/60 p-2.5">
          <div className="flex items-center justify-between">
            <div className="text-[10px] uppercase tracking-wider text-slate-500">
              Daily MMS Volume
            </div>
            <SegGroup<MmsVolumeMetric>
              value={state.volumeMetric}
              onChange={(v) => setState((s) => ({ ...s, volumeMetric: v }))}
              options={[
                { key: 'count', label: 'Count' },
                { key: 'dv01', label: 'DV01' },
              ]}
              compact
            />
          </div>
          <div style={{ height: 200 }}>
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart data={dailyVolume} margin={{ top: 8, right: 40, bottom: 4, left: 8 }}>
                <CartesianGrid stroke={ANALYTICS_COLORS.grid} vertical={false} />
                <XAxis
                  dataKey="date"
                  stroke={ANALYTICS_COLORS.axis}
                  tick={{ fontSize: 9, fill: ANALYTICS_COLORS.slate400, fontFamily: 'ui-monospace' }}
                  axisLine={{ stroke: ANALYTICS_COLORS.slate800 }}
                  tickLine={{ stroke: ANALYTICS_COLORS.slate800 }}
                  tickFormatter={(v: string) => v.slice(5)}
                />
                <YAxis
                  yAxisId="vol"
                  stroke={ANALYTICS_COLORS.axis}
                  tick={{ fontSize: 9, fill: ANALYTICS_COLORS.slate400, fontFamily: 'ui-monospace' }}
                  axisLine={{ stroke: ANALYTICS_COLORS.slate800 }}
                  tickLine={{ stroke: ANALYTICS_COLORS.slate800 }}
                  tickFormatter={state.volumeMetric === 'dv01' ? (v: number) => fmtDv01Compact(v) : undefined}
                />
                <YAxis
                  yAxisId="pct"
                  orientation="right"
                  stroke={ANALYTICS_COLORS.axis}
                  domain={[0, 100]}
                  tick={{ fontSize: 9, fill: ANALYTICS_COLORS.slate400, fontFamily: 'ui-monospace' }}
                  axisLine={{ stroke: ANALYTICS_COLORS.slate800 }}
                  tickLine={{ stroke: ANALYTICS_COLORS.slate800 }}
                  tickFormatter={(v: number) => `${v}%`}
                />
                <Tooltip content={<VolumeTooltip metric={state.volumeMetric} />} cursor={{ fill: 'rgba(148,163,184,0.06)' }} />
                <Bar
                  yAxisId="vol"
                  dataKey={volumeDataKey}
                  fill={MMS_BAR_COLOR}
                  fillOpacity={0.85}
                  radius={[2, 2, 0, 0]}
                />
                <Line
                  yAxisId="pct"
                  type="monotone"
                  dataKey={(d: { share: number }) => d.share * 100}
                  stroke={SHARE_LINE_COLOR}
                  strokeWidth={1.5}
                  dot={false}
                  name="MMS Share %"
                />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
          <div className="flex flex-wrap items-center gap-3 border-t border-slate-800 pt-1 font-mono text-[10px] text-slate-400">
            <span className="flex items-center gap-1.5">
              <span className="inline-block h-2 w-3 rounded-sm" style={{ backgroundColor: MMS_BAR_COLOR }} />
              MMS {state.volumeMetric === 'count' ? 'Count' : 'DV01'}
            </span>
            <span className="flex items-center gap-1.5">
              <span className="inline-block h-[2px] w-4" style={{ backgroundColor: SHARE_LINE_COLOR }} />
              Share %
            </span>
          </div>
        </div>

        {/* Panel 3: Maturity distribution */}
        <div className="flex flex-col gap-1.5 rounded border border-slate-800 bg-slate-950/60 p-2.5">
          <div className="flex items-center justify-between">
            <div className="text-[10px] uppercase tracking-wider text-slate-500">
              Maturity Distribution
            </div>
            <SegGroup<MmsDistributionMetric>
              value={state.distributionMetric}
              onChange={(v) => setState((s) => ({ ...s, distributionMetric: v }))}
              options={[
                { key: 'count', label: 'Count' },
                { key: 'dv01', label: 'DV01' },
                { key: 'notional', label: 'Notional' },
              ]}
              compact
            />
          </div>
          <div style={{ height: 200 }}>
            {maturityDist.length > 0 ? (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart
                  data={maturityDist}
                  layout="vertical"
                  margin={{ top: 4, right: 16, bottom: 4, left: 40 }}
                >
                  <CartesianGrid stroke={ANALYTICS_COLORS.grid} horizontal={false} />
                  <XAxis
                    type="number"
                    stroke={ANALYTICS_COLORS.axis}
                    tick={{ fontSize: 9, fill: ANALYTICS_COLORS.slate400, fontFamily: 'ui-monospace' }}
                    axisLine={{ stroke: ANALYTICS_COLORS.slate800 }}
                    tickLine={{ stroke: ANALYTICS_COLORS.slate800 }}
                    tickFormatter={
                      distributionDataKey === 'count'
                        ? undefined
                        : distributionDataKey === 'dv01'
                          ? (v: number) => fmtDv01Compact(v)
                          : (v: number) => `${fmtNotionalMM(v)}M`
                    }
                  />
                  <YAxis
                    type="category"
                    dataKey="mmyy"
                    stroke={ANALYTICS_COLORS.axis}
                    tick={{ fontSize: 9, fill: ANALYTICS_COLORS.slate400, fontFamily: 'ui-monospace' }}
                    axisLine={{ stroke: ANALYTICS_COLORS.slate800 }}
                    tickLine={{ stroke: ANALYTICS_COLORS.slate800 }}
                    width={36}
                  />
                  <Tooltip content={<DistributionTooltip metric={state.distributionMetric} />} cursor={{ fill: 'rgba(148,163,184,0.06)' }} />
                  <Bar dataKey={distributionDataKey} radius={[0, 3, 3, 0]}>
                    {maturityDist.map((_entry, idx) => (
                      <Cell key={`cell-${idx}`} fill={MATURITY_COLORS[idx % MATURITY_COLORS.length]} fillOpacity={0.85} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <div className="flex h-full items-center justify-center text-[10.5px] text-slate-500">
                No maturity data
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Panel 4: Top CUSIPs table */}
      <div className="rounded border border-slate-800 bg-slate-950/60 p-2.5 font-mono text-[11px] text-slate-300">
        <div className="mb-2 text-[10px] uppercase tracking-wider text-slate-500">Top CUSIPs</div>
        {topCusips.length > 0 ? (
          <table className="w-full table-auto border-separate border-spacing-y-0.5">
            <thead>
              <tr className="text-[9.5px] uppercase tracking-wider text-slate-500">
                <th className="text-left px-1 py-1">#</th>
                <th className="text-left px-1 py-1">CUSIP</th>
                <th className="text-left px-1 py-1">MMYY</th>
                <th className="text-right px-1 py-1">Count</th>
                <th className="text-right px-1 py-1">DV01</th>
                <th className="text-right px-1 py-1">Notional</th>
              </tr>
            </thead>
            <tbody>
              {topCusips.map((c, i) => (
                <tr key={c.cusip} className="hover:bg-slate-900/40">
                  <td className="px-1 py-0.5 text-slate-500">{i + 1}</td>
                  <td className="px-1 py-0.5 text-slate-200">{c.cusip}</td>
                  <td className="px-1 py-0.5 text-slate-400">{c.mmyy}</td>
                  <td className="px-1 py-0.5 text-right tabular-nums text-slate-100">{c.count}</td>
                  <td className="px-1 py-0.5 text-right tabular-nums text-slate-100">{fmtDv01Compact(c.dv01)}</td>
                  <td className="px-1 py-0.5 text-right tabular-nums text-slate-100">{fmtNotionalMM(c.notional)} MM</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <div className="text-[10.5px] text-slate-500">No CUSIP data available</div>
        )}
      </div>
    </div>
  )
}
