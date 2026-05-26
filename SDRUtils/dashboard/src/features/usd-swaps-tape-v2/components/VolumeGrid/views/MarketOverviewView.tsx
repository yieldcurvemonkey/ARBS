'use client'
import { useState, useEffect, useRef, type JSX } from 'react'
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
  StructureProjectionEntry,
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
          <VolumeProjectionTable entries={data.structureProjection} metric={metric} />
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
// Volume projection table — per-structure today vs 1W/1M ADV
// ---------------------------------------------------------------------------

function vsRatioColor(r: number | null): string {
  if (r == null) return 'text-slate-500'
  if (r >= 1.2) return 'text-emerald-300'
  if (r >= 1.0) return 'text-emerald-400/70'
  if (r >= 0.8) return 'text-slate-200'
  if (r >= 0.5) return 'text-amber-300'
  return 'text-rose-300'
}

const STRUCTURE_TYPE_COLORS: Record<string, string> = {
  Outright: '#6366f1',
  Curve: '#f59e0b',
  Fly: '#10b981',
  Spreadover: '#8b5cf6',
  'Sprd Curve': '#d97706',
  'Sprd Fly': '#059669',
  Other: '#64748b',
}

function structureColor(key: string): string | undefined {
  for (const [type, color] of Object.entries(STRUCTURE_TYPE_COLORS)) {
    if (key.endsWith(type)) return color
  }
  return undefined
}

function isOutrightLike(key: string): boolean {
  return key.endsWith('Outright') || key.endsWith('Spreadover')
}

function fmtLevel(level: number | null, structureKey: string): string {
  if (level == null) return '-'
  if (isOutrightLike(structureKey)) return `${level.toFixed(3)}%`
  return `${level.toFixed(1)}bp`
}

function fmtTradeTime(iso: string | null): string {
  if (!iso) return '-'
  return new Date(iso).toLocaleTimeString('en-US', {
    timeZone: 'America/New_York',
    hour12: false,
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

const COMMON_STRUCTURES: Record<string, string[]> = {
  Outright: ['1Y', '2Y', '3Y', '4Y', '5Y', '7Y', '10Y', '12Y', '15Y', '20Y', '25Y', '30Y']
    .map((t) => `${t} Outright`),
  Curve: ['2s3s', '2s5s', '2s7s', '2s10s', '2s30s', '3s5s', '3s10s', '5s7s', '5s10s', '5s30s', '7s10s', '10s30s']
    .map((t) => `${t} Curve`),
  Fly: ['2s3s5s', '2s5s10s', '2s5s30s', '2s10s30s', '3s5s10s', '5s7s10s', '5s10s30s']
    .map((t) => `${t} Fly`),
  Spreadover: ['2Y', '5Y', '7Y', '10Y', '30Y']
    .map((t) => `${t} Spreadover`),
}

const ALL_COMMON = Object.values(COMMON_STRUCTURES).flat()

const DEFAULT_SELECTED = new Set([
  '2Y Outright', '3Y Outright', '5Y Outright', '7Y Outright',
  '10Y Outright', '20Y Outright', '30Y Outright',
  '2s5s Curve', '2s10s Curve', '2s30s Curve',
  '5s10s Curve', '5s30s Curve', '10s30s Curve',
  '2s5s10s Fly', '5s10s30s Fly',
  '5Y Spreadover', '10Y Spreadover', '30Y Spreadover',
])

const STORAGE_KEY = 'volume-grid-structure-selection'

function loadSelection(): Set<string> {
  if (typeof window === 'undefined') return DEFAULT_SELECTED
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return DEFAULT_SELECTED
    const arr = JSON.parse(raw) as string[]
    return new Set(arr)
  } catch { return DEFAULT_SELECTED }
}

function saveSelection(sel: Set<string>): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify([...sel]))
}

function structureGroup(key: string): string {
  for (const [group] of Object.entries(STRUCTURE_TYPE_COLORS)) {
    if (key.endsWith(group)) return group
  }
  return 'Other'
}

function StructureSelector({ available, selected, onChange }: {
  available: string[]
  selected: Set<string>
  onChange: (s: Set<string>) => void
}): JSX.Element {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  const allKeys = [...new Set([...ALL_COMMON, ...available])].sort((a, b) => {
    const ga = structureGroup(a), gb = structureGroup(b)
    if (ga !== gb) return ga.localeCompare(gb)
    return a.localeCompare(b)
  })

  const groups = new Map<string, string[]>()
  for (const k of allKeys) {
    const g = structureGroup(k)
    if (!groups.has(g)) groups.set(g, [])
    groups.get(g)!.push(k)
  }

  const toggle = (k: string) => {
    const next = new Set(selected)
    if (next.has(k)) next.delete(k); else next.add(k)
    onChange(next)
  }

  const toggleGroup = (keys: string[]) => {
    const allOn = keys.every((k) => selected.has(k))
    const next = new Set(selected)
    for (const k of keys) { if (allOn) next.delete(k); else next.add(k) }
    onChange(next)
  }

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="rounded border border-slate-700 px-2 py-[2px] font-mono text-[10px] text-slate-300 hover:bg-slate-800"
      >
        {selected.size} structures ▾
      </button>
      {open && (
        <div className="absolute left-0 top-full z-50 mt-1 max-h-[420px] w-[260px] overflow-y-auto rounded border border-slate-700 bg-slate-900 p-1.5 shadow-xl">
          <div className="mb-1.5 flex gap-1">
            <button type="button" onClick={() => onChange(DEFAULT_SELECTED)}
              className="rounded bg-slate-800 px-1.5 py-0.5 font-mono text-[9px] text-slate-300 hover:bg-slate-700">
              Defaults
            </button>
            <button type="button" onClick={() => onChange(new Set(allKeys))}
              className="rounded bg-slate-800 px-1.5 py-0.5 font-mono text-[9px] text-slate-300 hover:bg-slate-700">
              All
            </button>
            <button type="button" onClick={() => onChange(new Set())}
              className="rounded bg-slate-800 px-1.5 py-0.5 font-mono text-[9px] text-slate-300 hover:bg-slate-700">
              Clear
            </button>
          </div>
          {[...groups.entries()].map(([group, keys]) => (
            <div key={group} className="mb-1">
              <button type="button" onClick={() => toggleGroup(keys)}
                className="mb-0.5 font-mono text-[9px] font-semibold uppercase tracking-wide text-slate-400 hover:text-slate-200">
                <span className="mr-1 inline-block h-1.5 w-1.5 rounded-sm"
                  style={{ backgroundColor: STRUCTURE_TYPE_COLORS[group] ?? '#64748b' }} />
                {group}
              </button>
              <div className="flex flex-wrap gap-x-0.5 gap-y-0.5">
                {keys.map((k) => {
                  const on = selected.has(k)
                  const label = k.replace(` ${group}`, '')
                  return (
                    <button key={k} type="button" onClick={() => toggle(k)}
                      className={`rounded px-1.5 py-[1px] font-mono text-[9px] transition-colors ${
                        on
                          ? 'bg-indigo-500/25 text-indigo-200 ring-1 ring-indigo-500/40'
                          : 'bg-slate-800/60 text-slate-500 hover:text-slate-300'
                      }`}>
                      {label}
                    </button>
                  )
                })}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function VolumeProjectionTable({ entries, metric }: {
  entries: StructureProjectionEntry[]
  metric: VolumeMetric
}): JSX.Element {
  const [selected, setSelected] = useState<Set<string>>(loadSelection)

  const handleChange = (s: Set<string>) => {
    setSelected(s)
    saveSelection(s)
  }

  const available = entries.map((e) => e.structureKey)
  const filtered = entries.filter((e) => selected.has(e.structureKey))

  return (
    <div data-testid="volume-projection-table" className="rounded border border-slate-800 bg-slate-950/25 p-2">
      <div className="mb-2 flex items-center justify-between">
        <span className="font-mono text-[10px] uppercase tracking-wide text-slate-300">
          Structure Activity — Today vs Averages
        </span>
        <StructureSelector available={available} selected={selected} onChange={handleChange} />
      </div>
      {filtered.length === 0 ? (
        <div className="flex h-16 items-center justify-center font-mono text-[10px] text-slate-500">
          No structures selected — click the dropdown to choose.
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full font-mono text-[10px]">
            <thead>
              <tr className="border-b border-slate-700/50 text-slate-400">
                <th className="py-1.5 pr-2 text-left font-medium">Structure</th>
                <th className="px-1.5 py-1.5 text-right font-medium">Last</th>
                <th className="px-1.5 py-1.5 text-right font-medium">#</th>
                <th className="px-1.5 py-1.5 text-right font-medium">Plat</th>
                <th className="px-1.5 py-1.5 text-right font-medium">Level</th>
                <th className="px-1.5 py-1.5 text-right font-medium">Today {metric.toUpperCase()}</th>
                <th className="px-1.5 py-1.5 text-right font-medium">ADV 1W</th>
                <th className="px-1.5 py-1.5 text-right font-medium">ADV 1M</th>
                <th className="px-1.5 py-1.5 text-right font-medium">vs 1W</th>
                <th className="px-1.5 py-1.5 text-right font-medium">vs 1M</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((e) => {
                const vsWeek = e.adv1w > 0 ? e.todayVolume / e.adv1w : null
                const vsMonth = e.adv1m > 0 ? e.todayVolume / e.adv1m : null
                const color = structureColor(e.structureKey)

                return (
                  <tr key={e.structureKey} className="border-b border-slate-800/30 hover:bg-slate-800/20">
                    <td className="py-1 pr-2 text-slate-200">
                      <span className="flex items-center gap-1.5">
                        {color && <span className="inline-block h-2 w-2 rounded-sm" style={{ backgroundColor: color }} />}
                        <span>{e.structureKey}</span>
                      </span>
                    </td>
                    <td className="px-1.5 py-1 text-right text-slate-400">{fmtTradeTime(e.lastTradeTime)}</td>
                    <td className="px-1.5 py-1 text-right text-slate-300">{e.todayCount}</td>
                    <td className="px-1.5 py-1 text-right text-slate-400">{e.latestPlatform ?? '-'}</td>
                    <td className="px-1.5 py-1 text-right text-sky-300">{fmtLevel(e.lastLevel, e.structureKey)}</td>
                    <td className="px-1.5 py-1 text-right text-slate-100">{fmtCompact(e.todayVolume)}</td>
                    <td className="px-1.5 py-1 text-right text-slate-300">{fmtCompact(e.adv1w)}</td>
                    <td className="px-1.5 py-1 text-right text-slate-300">{fmtCompact(e.adv1m)}</td>
                    <td className={`px-1.5 py-1 text-right font-medium ${vsRatioColor(vsWeek)}`}>
                      {vsWeek != null ? `${vsWeek.toFixed(2)}x` : '-'}
                    </td>
                    <td className={`px-1.5 py-1 text-right font-medium ${vsRatioColor(vsMonth)}`}>
                      {vsMonth != null ? `${vsMonth.toFixed(2)}x` : '-'}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
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
