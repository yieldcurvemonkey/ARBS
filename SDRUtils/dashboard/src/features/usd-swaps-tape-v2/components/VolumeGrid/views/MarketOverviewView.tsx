'use client'
import type { JSX } from 'react'
import {
  Bar, BarChart, CartesianGrid, Cell, Line, LineChart, ReferenceLine,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { useAggregateVolume } from '../../../hooks/useAggregateVolume'
import type { ViewProps } from '../../../types/volume-grid-views.types'
import type { VolumeMetric } from '../../../types/volume-grid.types'
import type {
  AggregateDailyPoint,
  AggregateDistributionEntry,
  AggregateSummary,
  AggregateVolumeResponse,
} from '../../../types/aggregate-volume.types'
import type { VolumeGridIntradaySeasonality } from '../../../types/volume-grid.types'

const STACKED_COLORS = {
  outright: '#6366f1',
  curve: '#f59e0b',
  fly: '#10b981',
  other: '#64748b',
} as const

const SEASONALITY_X_TICKS = [0, 360, 720, 1080, 1440]

const fmtCompact = (n: number): string => {
  const abs = Math.abs(n)
  if (abs >= 1e9) return `${(n / 1e9).toFixed(1)}B`
  if (abs >= 1e6) return `${(n / 1e6).toFixed(1)}M`
  if (abs >= 1e3) return `${(n / 1e3).toFixed(0)}k`
  return n.toFixed(0)
}

const fmtPct = (n: number | null): string => n == null ? '-' : `${n.toFixed(0)}th`

const fmtMinuteOfDay = (m: number): string => {
  const h = Math.floor(Math.max(0, Math.min(1440, m)) / 60)
  const min = Math.floor(m) % 60
  return `${String(h).padStart(2, '0')}:${String(min).padStart(2, '0')}`
}

export function MarketOverviewView({ metric, period, lookbackDays, textFilter }: ViewProps): JSX.Element {
  const { data, error, isLoading } = useAggregateVolume({
    metric,
    period,
    lookbackDays,
    packageType: 'all',
    textFilter: textFilter || undefined,
  })

  return (
    <div className="space-y-3 px-3 pb-3">
      <div className="flex items-center gap-2">
        {isLoading && (
          <span className="rounded bg-sky-500/15 px-1.5 py-[1px] font-mono text-[10px] text-sky-200 ring-1 ring-sky-500/30">
            loading&hellip;
          </span>
        )}
        {error && (
          <span className="rounded bg-rose-500/15 px-1.5 py-[1px] font-mono text-[10px] text-rose-200 ring-1 ring-rose-500/30">
            {error.message}
          </span>
        )}
      </div>

      {data && (
        <>
          <KpiStrip summary={data.summary} metric={metric} />
          <VolumeProjectionTable series={data.dailySeries} metric={metric} />
          <DailyVolumeChart series={data.dailySeries} metric={metric} adv={data.summary.adv} />
          <div className="grid gap-3 lg:grid-cols-3">
            <CompositionPanel entries={data.packageMix} title="Package Mix" />
            <VenueSplitPanel idb={data.venueSplit.idb} custy={data.venueSplit.custy} />
            <IntradayPaceChart seasonality={data.intradayCurve} metric={metric} />
          </div>
          <TenorDistributionChart entries={data.tenorDistribution} metric={metric} />
        </>
      )}

      {!data && !isLoading && !error && (
        <div className="flex h-32 items-center justify-center font-mono text-[11px] text-slate-500">
          No aggregate data available.
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// KPI strip
// ---------------------------------------------------------------------------

function KpiStrip({ summary, metric }: { summary: AggregateSummary; metric: VolumeMetric }): JSX.Element {
  const pctColor = percentileColor(summary.percentileRank)
  const advRatioColor = summary.currentVsAdv >= 1.2
    ? 'text-emerald-300'
    : summary.currentVsAdv <= 0.8 ? 'text-rose-300' : 'text-slate-200'

  return (
    <div data-testid="aggregate-kpi-strip" className="flex flex-wrap gap-2">
      <KpiCard label={`Total ${metric.toUpperCase()}`} value={fmtCompact(summary.currentTotal)} />
      <KpiCard label="Percentile" value={fmtPct(summary.percentileRank)} className={pctColor} />
      <KpiCard label="Trade Count" value={String(summary.tradeCount)} />
      <KpiCard label="ADV" value={fmtCompact(summary.adv)} />
      <KpiCard label="vs ADV" value={`${summary.currentVsAdv.toFixed(2)}x`} className={advRatioColor} />
      <KpiCard label="Wt Avg Tenor" value={`${summary.weightedAvgTenor.toFixed(1)}Y`} />
      {summary.blockCount > 0 && (
        <KpiCard
          label="Block Share"
          value={summary.currentTotal > 0 ? `${((summary.blockVolume / summary.currentTotal) * 100).toFixed(0)}%` : '0%'}
        />
      )}
    </div>
  )
}

function KpiCard({ label, value, className }: { label: string; value: string; className?: string }): JSX.Element {
  return (
    <div className="rounded border border-slate-700 bg-slate-800/40 px-3 py-1.5">
      <div className="font-mono text-[9px] uppercase tracking-wider text-slate-500">{label}</div>
      <div className={`font-mono text-[14px] font-semibold ${className ?? 'text-slate-100'}`}>{value}</div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Volume projection table — today vs 1W/1M ADV
// ---------------------------------------------------------------------------

type StructureKey = 'total' | 'outright' | 'curve' | 'fly' | 'other'

const STRUCTURE_ROWS: ReadonlyArray<{ key: StructureKey; label: string; color?: string }> = [
  { key: 'total', label: 'Total' },
  { key: 'outright', label: 'Outright', color: STACKED_COLORS.outright },
  { key: 'curve', label: 'Curve', color: STACKED_COLORS.curve },
  { key: 'fly', label: 'Fly', color: STACKED_COLORS.fly },
  { key: 'other', label: 'Other', color: STACKED_COLORS.other },
]

const ONE_DAY_MS = 24 * 60 * 60 * 1000

function computeAvg(entries: AggregateDailyPoint[], key: StructureKey): number {
  if (entries.length === 0) return 0
  return entries.reduce((sum, d) => sum + d[key], 0) / entries.length
}

function vsRatioColor(r: number | null): string {
  if (r == null) return 'text-slate-500'
  if (r >= 1.2) return 'text-emerald-300'
  if (r >= 1.0) return 'text-emerald-400/70'
  if (r >= 0.8) return 'text-slate-200'
  if (r >= 0.5) return 'text-amber-300'
  return 'text-rose-300'
}

function VolumeProjectionTable({ series, metric }: {
  series: AggregateDailyPoint[]
  metric: VolumeMetric
}): JSX.Element {
  if (series.length < 2) return <EmptyPanel text="Not enough history for volume projection." />

  const today = series[series.length - 1]
  const historical = series.slice(0, -1)

  const todayDate = new Date(today.day + 'T12:00:00Z')
  const weekCutoff = new Date(todayDate.getTime() - 7 * ONE_DAY_MS)
  const monthCutoff = new Date(todayDate.getTime() - 30 * ONE_DAY_MS)

  const pastWeek = historical.filter(d => new Date(d.day + 'T12:00:00Z') >= weekCutoff)
  const pastMonth = historical.filter(d => new Date(d.day + 'T12:00:00Z') >= monthCutoff)

  const weekTradeAvg = pastWeek.length > 0
    ? pastWeek.reduce((s, d) => s + d.tradeCount, 0) / pastWeek.length
    : 0
  const monthTradeAvg = pastMonth.length > 0
    ? pastMonth.reduce((s, d) => s + d.tradeCount, 0) / pastMonth.length
    : 0

  return (
    <div data-testid="volume-projection-table" className="rounded border border-slate-800 bg-slate-950/25 p-2">
      <div className="mb-2 font-mono text-[10px] uppercase tracking-wide text-slate-300">
        Volume Projection — Today vs Averages
      </div>
      <div className="overflow-x-auto">
        <table className="w-full font-mono text-[10px]">
          <thead>
            <tr className="border-b border-slate-700/50 text-slate-400">
              <th className="py-1.5 pr-3 text-left font-medium">Structure</th>
              <th className="px-2 py-1.5 text-right font-medium">Today</th>
              <th className="px-2 py-1.5 text-right font-medium">ADV (1W)</th>
              <th className="px-2 py-1.5 text-right font-medium">ADV (1M)</th>
              <th className="px-2 py-1.5 text-right font-medium">vs 1W</th>
              <th className="px-2 py-1.5 text-right font-medium">vs 1M</th>
            </tr>
          </thead>
          <tbody>
            {STRUCTURE_ROWS.map(({ key, label, color }) => {
              const todayVal = today[key]
              const weekAvg = computeAvg(pastWeek, key)
              const monthAvg = computeAvg(pastMonth, key)
              const vsWeek = weekAvg > 0 ? todayVal / weekAvg : null
              const vsMonth = monthAvg > 0 ? todayVal / monthAvg : null
              const isTotal = key === 'total'

              return (
                <tr key={key} className={`border-b border-slate-800/30 ${isTotal ? 'bg-slate-800/20' : ''}`}>
                  <td className="py-1.5 pr-3 text-slate-300">
                    <span className="flex items-center gap-1.5">
                      {color && <span className="inline-block h-2 w-2 rounded-sm" style={{ backgroundColor: color }} />}
                      <span className={isTotal ? 'font-semibold' : ''}>{label}</span>
                    </span>
                  </td>
                  <td className={`px-2 py-1.5 text-right text-slate-100 ${isTotal ? 'font-semibold' : ''}`}>
                    {fmtCompact(todayVal)}
                  </td>
                  <td className="px-2 py-1.5 text-right text-slate-300">{fmtCompact(weekAvg)}</td>
                  <td className="px-2 py-1.5 text-right text-slate-300">{fmtCompact(monthAvg)}</td>
                  <td className={`px-2 py-1.5 text-right font-medium ${vsRatioColor(vsWeek)}`}>
                    {vsWeek != null ? `${vsWeek.toFixed(2)}x` : '-'}
                  </td>
                  <td className={`px-2 py-1.5 text-right font-medium ${vsRatioColor(vsMonth)}`}>
                    {vsMonth != null ? `${vsMonth.toFixed(2)}x` : '-'}
                  </td>
                </tr>
              )
            })}
            <tr className="border-b border-slate-800/30 bg-slate-800/20">
              <td className="py-1.5 pr-3 font-semibold text-slate-300"># Trades</td>
              <td className="px-2 py-1.5 text-right font-semibold text-slate-100">{today.tradeCount}</td>
              <td className="px-2 py-1.5 text-right text-slate-300">{weekTradeAvg.toFixed(0)}</td>
              <td className="px-2 py-1.5 text-right text-slate-300">{monthTradeAvg.toFixed(0)}</td>
              <td className={`px-2 py-1.5 text-right font-medium ${vsRatioColor(weekTradeAvg > 0 ? today.tradeCount / weekTradeAvg : null)}`}>
                {weekTradeAvg > 0 ? `${(today.tradeCount / weekTradeAvg).toFixed(2)}x` : '-'}
              </td>
              <td className={`px-2 py-1.5 text-right font-medium ${vsRatioColor(monthTradeAvg > 0 ? today.tradeCount / monthTradeAvg : null)}`}>
                {monthTradeAvg > 0 ? `${(today.tradeCount / monthTradeAvg).toFixed(2)}x` : '-'}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div className="mt-1.5 flex items-center justify-between font-mono text-[8.5px] text-slate-600">
        <span>
          1W = avg daily over {pastWeek.length} trading day{pastWeek.length !== 1 ? 's' : ''}
          {' · '}1M = avg daily over {pastMonth.length} trading day{pastMonth.length !== 1 ? 's' : ''}
        </span>
        <span>{today.day}</span>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Daily volume stacked bar chart
// ---------------------------------------------------------------------------

function DailyVolumeChart({ series, metric, adv }: {
  series: AggregateDailyPoint[]
  metric: VolumeMetric
  adv: number
}): JSX.Element {
  if (series.length === 0) return <EmptyPanel text="No daily data." />

  return (
    <div data-testid="aggregate-daily-chart" className="h-[220px] rounded border border-slate-800 bg-slate-950/25 p-2">
      <div className="mb-1 flex items-center justify-between font-mono text-[10px] text-slate-400">
        <span className="uppercase tracking-wide text-slate-300">Daily {metric.toUpperCase()}</span>
        <div className="flex items-center gap-3">
          {Object.entries(STACKED_COLORS).map(([k, c]) => (
            <span key={k} className="flex items-center gap-1">
              <span className="inline-block h-2 w-2 rounded-sm" style={{ backgroundColor: c }} />
              <span className="capitalize">{k}</span>
            </span>
          ))}
        </div>
      </div>
      <ResponsiveContainer width="100%" height="88%">
        <BarChart data={series}>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(148,163,184,0.15)" />
          <XAxis dataKey="day" tick={{ fontSize: 9, fill: '#94a3b8' }} />
          <YAxis tick={{ fontSize: 9, fill: '#94a3b8' }} tickFormatter={(v) => fmtCompact(Number(v))} width={52} />
          <Tooltip
            contentStyle={{ background: '#0f172a', border: '1px solid #1e293b', fontSize: 11 }}
            formatter={(value: number, name: string) => [fmtCompact(value), name]}
            labelFormatter={(label) => String(label)}
          />
          <Bar dataKey="outright" stackId="pkg" fill={STACKED_COLORS.outright} isAnimationActive={false} />
          <Bar dataKey="curve" stackId="pkg" fill={STACKED_COLORS.curve} isAnimationActive={false} />
          <Bar dataKey="fly" stackId="pkg" fill={STACKED_COLORS.fly} isAnimationActive={false} />
          <Bar dataKey="other" stackId="pkg" fill={STACKED_COLORS.other} isAnimationActive={false} />
          {adv > 0 && (
            <ReferenceLine y={adv} stroke="#94a3b8" strokeDasharray="4 2" label={{ value: 'ADV', position: 'right', fontSize: 9, fill: '#94a3b8' }} />
          )}
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Composition panels
// ---------------------------------------------------------------------------

function CompositionPanel({ entries, title }: {
  entries: AggregateDistributionEntry[]
  title: string
}): JSX.Element {
  const maxVal = Math.max(...entries.map((e) => Math.max(e.current, e.historicalAvg)), 1)
  return (
    <div className="rounded border border-slate-800 bg-slate-950/25 p-2">
      <div className="mb-2 font-mono text-[10px] uppercase tracking-wide text-slate-300">{title}</div>
      <div className="space-y-1.5">
        {entries.map((e) => (
          <div key={e.id}>
            <div className="flex items-center justify-between font-mono text-[9.5px]">
              <span className="text-slate-300">{e.label}</span>
              <span className="text-slate-400">
                {fmtCompact(e.current)} ({e.share.toFixed(0)}%)
                <span className="ml-1 text-slate-600">hist: {e.historicalShare.toFixed(0)}%</span>
              </span>
            </div>
            <div className="relative mt-0.5 h-2 overflow-hidden rounded bg-slate-800">
              <div
                className="absolute left-0 top-0 h-full rounded bg-indigo-500/60"
                style={{ width: `${(e.current / maxVal) * 100}%` }}
              />
              <div
                className="absolute left-0 top-0 h-full border-r-2 border-dashed border-slate-400/40"
                style={{ width: `${(e.historicalAvg / maxVal) * 100}%` }}
              />
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function VenueSplitPanel({ idb, custy }: {
  idb: AggregateDistributionEntry
  custy: AggregateDistributionEntry
}): JSX.Element {
  return (
    <div className="rounded border border-slate-800 bg-slate-950/25 p-2">
      <div className="mb-2 font-mono text-[10px] uppercase tracking-wide text-slate-300">Venue Split</div>
      <div className="space-y-3">
        {[idb, custy].map((e) => (
          <div key={e.id}>
            <div className="flex items-center justify-between font-mono text-[9.5px]">
              <span className="text-slate-300">{e.label}</span>
              <span className="text-slate-400">
                {fmtCompact(e.current)} ({e.share.toFixed(0)}%)
                <span className="ml-1 text-slate-600">hist: {e.historicalShare.toFixed(0)}%</span>
              </span>
            </div>
            <div className="mt-0.5 h-3 overflow-hidden rounded bg-slate-800">
              <div
                className={`h-full rounded ${e.id === 'idb' ? 'bg-sky-500/50' : 'bg-amber-500/50'}`}
                style={{ width: `${e.share}%` }}
              />
            </div>
          </div>
        ))}
        <div className="flex h-4 overflow-hidden rounded bg-slate-800">
          <div className="bg-sky-500/50" style={{ width: `${idb.share}%` }} />
          <div className="bg-amber-500/50" style={{ width: `${custy.share}%` }} />
        </div>
        <div className="flex items-center justify-between font-mono text-[9px] text-slate-500">
          <span>Historical: IDB {idb.historicalShare.toFixed(0)}% / CUSTY {custy.historicalShare.toFixed(0)}%</span>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Intraday pace chart
// ---------------------------------------------------------------------------

function IntradayPaceChart({ seasonality, metric }: {
  seasonality: VolumeGridIntradaySeasonality
  metric: VolumeMetric
}): JSX.Element {
  const points = seasonality?.points ?? []
  const hasSeries = points.some((p) => p.current != null || p.average != null)
  const avgLabel = seasonality?.observedDays ? `${seasonality.observedDays}d avg` : 'avg'

  return (
    <div className="rounded border border-slate-800 bg-slate-950/25 p-2">
      <div className="mb-1 flex items-center justify-between font-mono text-[10px] text-slate-400">
        <span className="uppercase tracking-wide text-slate-300">Aggregate Intraday Volume (All Tenors)</span>
        <span>
          <span className="text-amber-300">today</span>
          <span className="mx-1 text-slate-600">/</span>
          <span className="text-amber-100/75">{avgLabel}</span>
        </span>
      </div>
      {hasSeries ? (
        <ResponsiveContainer width="100%" height={130}>
          <LineChart data={points} margin={{ top: 4, right: 8, bottom: 4, left: 4 }}>
            <CartesianGrid vertical={false} stroke="rgba(148,163,184,0.15)" strokeDasharray="3 3" />
            <XAxis
              dataKey="minuteOfDay" type="number" domain={[0, 1440]}
              ticks={SEASONALITY_X_TICKS}
              tickFormatter={(v) => fmtMinuteOfDay(Number(v))}
              tick={{ fontSize: 9, fill: '#94a3b8' }}
              axisLine={{ stroke: '#334155' }}
            />
            <YAxis
              tick={{ fontSize: 9, fill: '#94a3b8' }}
              tickFormatter={(v) => fmtCompact(Number(v))}
              axisLine={{ stroke: '#334155' }}
              width={44}
            />
            <Tooltip
              contentStyle={{ background: '#0f172a', border: '1px solid #1e293b', fontSize: 11 }}
              labelFormatter={(label) => fmtMinuteOfDay(Number(label))}
              formatter={(value: unknown, name: string) => [
                value == null ? '-' : fmtCompact(Number(value)),
                name === 'current' ? 'today' : avgLabel,
              ]}
            />
            {seasonality?.asOfMinuteOfDay != null && (
              <ReferenceLine x={seasonality.asOfMinuteOfDay} stroke="#ef4444" strokeDasharray="4 3" />
            )}
            <Line type="stepAfter" dataKey="average" stroke="#fef3c7" strokeDasharray="4 3" strokeWidth={1.5} dot={false} connectNulls={false} isAnimationActive={false} />
            <Line type="stepAfter" dataKey="current" stroke="#fbbf24" strokeWidth={2} dot={false} connectNulls={false} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      ) : (
        <div className="flex h-[130px] items-center justify-center text-[11px] text-slate-500">No intraday data.</div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Tenor distribution
// ---------------------------------------------------------------------------

function TenorDistributionChart({ entries, metric }: {
  entries: AggregateDistributionEntry[]
  metric: VolumeMetric
}): JSX.Element {
  if (entries.length === 0) return <EmptyPanel text="No tenor distribution data." />

  return (
    <div data-testid="aggregate-tenor-distribution" className="rounded border border-slate-800 bg-slate-950/25 p-2">
      <div className="mb-2 flex items-center justify-between font-mono text-[10px] text-slate-400">
        <span className="uppercase tracking-wide text-slate-300">Tenor Distribution</span>
        <span>
          <span className="text-indigo-300">current</span>
          <span className="mx-1 text-slate-600">/</span>
          <span className="text-slate-400">historical avg</span>
        </span>
      </div>
      <ResponsiveContainer width="100%" height={Math.max(120, entries.length * 22)}>
        <BarChart data={entries} layout="vertical" margin={{ top: 0, right: 12, bottom: 0, left: 60 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(148,163,184,0.12)" horizontal={false} />
          <XAxis type="number" tick={{ fontSize: 9, fill: '#94a3b8' }} tickFormatter={(v) => fmtCompact(Number(v))} />
          <YAxis type="category" dataKey="label" tick={{ fontSize: 9, fill: '#cbd5e1' }} width={58} />
          <Tooltip
            contentStyle={{ background: '#0f172a', border: '1px solid #1e293b', fontSize: 11 }}
            formatter={(value: number, name: string) => [
              fmtCompact(value),
              name === 'current' ? 'Current' : 'Historical Avg',
            ]}
          />
          <Bar dataKey="historicalAvg" fill="rgba(148,163,184,0.25)" isAnimationActive={false} />
          <Bar dataKey="current" isAnimationActive={false}>
            {entries.map((e) => (
              <Cell key={e.id} fill={e.current > e.historicalAvg ? '#6366f1' : '#818cf8'} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function percentileColor(p: number | null): string {
  if (p == null) return 'text-slate-400'
  if (p >= 90) return 'text-emerald-300'
  if (p >= 75) return 'text-emerald-400/80'
  if (p >= 50) return 'text-slate-200'
  if (p >= 25) return 'text-amber-300'
  return 'text-rose-300'
}

function EmptyPanel({ text }: { text: string }): JSX.Element {
  return (
    <div className="flex h-32 items-center justify-center rounded border border-slate-800 bg-slate-950/25 font-mono text-[11px] text-slate-500">
      {text}
    </div>
  )
}
