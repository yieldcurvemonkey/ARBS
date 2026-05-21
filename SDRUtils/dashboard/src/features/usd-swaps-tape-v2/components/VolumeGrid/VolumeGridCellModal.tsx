'use client'
// ABOUTME: PrimeReact Dialog with daily volume timeseries + recent trades
// for the clicked grid cell. Row click closes modal and routes the
// package_id to onSelectPackage (which writes a URL filter).

import { Fragment, useEffect, useMemo, useState } from 'react'
import type { JSX, ReactNode } from 'react'
import { Dialog } from 'primereact/dialog'
import {
  Bar, BarChart, CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from 'recharts'
import { useVolumeGridCell } from '../../hooks/useVolumeGridCell'
import { lookupLabel } from './buckets'
import type {
  VolumeCellRange, VolumeMetric,
  VolumeGridIntradaySeasonality,
  VolumeGridSchemaAxis,
} from '../../types/volume-grid.types'
import type {
  ForwardSchemaId,
  PackageTypeGroupId,
  TenorSchemaId,
} from '@/lib/usd-swaps-tape-v2/volumeGridBuckets'

const KEY_RANGE = 'usd-tape-v2:volume-grid:cell-range'
const SEASONALITY_X_TICKS = [0, 360, 720, 1080, 1440]

const fmtCompact = (n: number, _metric: VolumeMetric): string => {
  void _metric
  const abs = Math.abs(n)
  if (abs >= 1e9) return `${(abs / 1e9).toFixed(1)}B`
  if (abs >= 1e6) return `${(abs / 1e6).toFixed(1)}M`
  if (abs >= 1e3) return `${(abs / 1e3).toFixed(0)}k`
  return abs.toFixed(0)
}

const fmtRate = (r: number | null): string => (r == null ? '-' : `${(r * 100).toFixed(3)}%`)
const fmtTenor = (y: number): string => {
  const rounded = Math.round(y)
  return Math.abs(y - rounded) < 0.1 ? `${rounded}Y` : `${y.toFixed(1)}Y`
}
const fmtTime = (ts: string): string =>
  new Date(ts).toLocaleString('en-US', {
    timeZone: 'America/New_York', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit',
  })

const PKG_BADGE_COLORS: Record<string, string> = {
  OUTRIGHT: 'bg-slate-500/20 text-slate-300 ring-slate-500/30',
  SPREADOVER: 'bg-slate-500/20 text-slate-300 ring-slate-500/30',
  MATCHED_MATURITY: 'bg-slate-500/20 text-slate-300 ring-slate-500/30',
  CURVE: 'bg-amber-500/20 text-amber-300 ring-amber-500/30',
  SPREADOVER_CURVE: 'bg-amber-500/20 text-amber-300 ring-amber-500/30',
  MATCHED_MATURITY_CURVE: 'bg-amber-500/20 text-amber-300 ring-amber-500/30',
  FLY: 'bg-emerald-500/20 text-emerald-300 ring-emerald-500/30',
  SPREADOVER_FLY: 'bg-emerald-500/20 text-emerald-300 ring-emerald-500/30',
  MATCHED_MATURITY_FLY: 'bg-emerald-500/20 text-emerald-300 ring-emerald-500/30',
}
const pkgBadgeClass = (pt: string | null): string =>
  PKG_BADGE_COLORS[pt ?? ''] ?? 'bg-purple-500/20 text-purple-300 ring-purple-500/30'

const fmtMinuteOfDay = (minuteOfDay: number): string => {
  if (!Number.isFinite(minuteOfDay)) return '--:--'
  const clamped = Math.max(0, Math.min(1440, Math.floor(minuteOfDay)))
  if (clamped >= 1440) return '24:00'
  const hours = Math.floor(clamped / 60)
  const minutes = clamped % 60
  return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}`
}

export interface VolumeGridCellModalProps {
  cell: { fwd: string; tenor?: string } | null
  metric: VolumeMetric
  forwardSchema?: ForwardSchemaId
  tenorSchema?: TenorSchemaId
  packageType?: PackageTypeGroupId
  forwardAxis?: VolumeGridSchemaAxis
  tenorAxis?: VolumeGridSchemaAxis
  textFilter?: string
  customForwardBuckets?: import('@/lib/usd-swaps-tape-v2/volumeGridBuckets').BucketDef[]
  customTenorBuckets?: import('@/lib/usd-swaps-tape-v2/volumeGridBuckets').BucketDef[]
  structureType?: 'curve' | 'fly'
  structureId?: string
  structureTenors?: number[]
  structureTolerance?: number
  onClose: () => void
  onSelectPackage: (packageId: string) => void
}

export function VolumeGridCellModal(props: VolumeGridCellModalProps): JSX.Element {
  const [range, setRange] = useState<VolumeCellRange>(() => {
    if (typeof window === 'undefined') return '3M'
    const v = window.localStorage.getItem(KEY_RANGE)
    return ['1M', '3M', '6M', '1Y'].includes(v ?? '') ? (v as VolumeCellRange) : '3M'
  })
  const onRangeChange = (r: VolumeCellRange) => {
    setRange(r)
    if (typeof window !== 'undefined') window.localStorage.setItem(KEY_RANGE, r)
  }

  const [expandedPkgs, setExpandedPkgs] = useState<Set<string>>(new Set())
  const toggleExpand = (pkgId: string) => {
    setExpandedPkgs((prev) => {
      const next = new Set(prev)
      if (next.has(pkgId)) next.delete(pkgId)
      else next.add(pkgId)
      return next
    })
  }

  const [localTradeFilter, setLocalTradeFilter] = useState('')

  useEffect(() => { setLocalTradeFilter('') }, [props.cell?.fwd, props.cell?.tenor])

  const { data, error, isLoading } = useVolumeGridCell({
    cell: props.cell,
    metric: props.metric,
    range,
    forwardSchema: props.forwardSchema ?? 'default',
    tenorSchema: props.tenorSchema ?? 'default',
    packageType: props.packageType ?? 'all',
    textFilter: props.textFilter,
    customForwardBuckets: props.customForwardBuckets,
    customTenorBuckets: props.customTenorBuckets,
    structureType: props.structureType,
    structureTenors: props.structureTenors,
    structureTolerance: props.structureTolerance,
  })

  const filteredTrades = useMemo(() => {
    if (!localTradeFilter || !data?.recentTrades) return data?.recentTrades ?? []
    const lower = localTradeFilter.toLowerCase()
    return data.recentTrades.filter(
      (t) => t.tape_label?.toLowerCase().includes(lower),
    )
  }, [data?.recentTrades, localTradeFilter])

  const headerLabel = props.cell
    ? props.cell.tenor
      ? `${lookupLabel(props.forwardAxis, props.cell.fwd)} × ${lookupLabel(props.tenorAxis, props.cell.tenor)} — Volume detail`
      : `${props.cell.fwd} — Volume detail`
    : 'Volume detail'

  return (
    <Dialog
      header={headerLabel}
      visible={props.cell != null}
      onHide={props.onClose}
      style={{ width: '80vw', maxWidth: 1200, height: '75vh' }}
      modal
    >
      <div className="flex h-full flex-col gap-3">
        <div className="flex items-center gap-2 text-slate-300">
          <RangeToggle value={range} onChange={onRangeChange} />
          {isLoading && (
            <span className="rounded bg-sky-500/15 px-1.5 py-[1px] font-mono text-[10px] text-sky-200 ring-1 ring-sky-500/30">
              loading…
            </span>
          )}
          {error && (
            <span className="rounded bg-rose-500/15 px-1.5 py-[1px] font-mono text-[10px] text-rose-200 ring-1 ring-rose-500/30">
              {error.message}
            </span>
          )}
        </div>
        {props.packageType === 'all' && (
          <div className="font-mono text-[9.5px] text-slate-500">
            Includes all package types (outright, curve, fly, etc.)
          </div>
        )}
        <div className="grid min-h-[230px] gap-3 lg:grid-cols-2">
          <div data-testid="volume-grid-cell-chart" className="h-[230px]">
            {data?.timeseries.length ? (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={data.timeseries}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(148,163,184,0.2)" />
                  <XAxis dataKey="day" tick={{ fontSize: 10, fill: '#94a3b8' }} />
                  <YAxis tick={{ fontSize: 10, fill: '#94a3b8' }}
                         tickFormatter={(v) => fmtCompact(Number(v), props.metric)} />
                  <Tooltip
                    contentStyle={{ background: '#0f172a', border: '1px solid #1e293b', fontSize: 11 }}
                    formatter={(value: number, name: string) => {
                      if (name === 'tradeCount') return [String(value), 'trades']
                      return [fmtCompact(value, props.metric), props.metric]
                    }}
                  />
                  <Bar
                    dataKey={props.metric === 'notional' ? 'notional' : 'dv01'}
                    fill="#6366f1"
                  />
                  {data.timeseries.length > 1 && (
                    <ReferenceLine
                      y={median(data.timeseries.map((p) => p[props.metric === 'notional' ? 'notional' : 'dv01']))}
                      stroke="#94a3b8"
                      strokeDasharray="4 2"
                    />
                  )}
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <div className="flex h-full items-center justify-center text-sm text-slate-500">
                No trades in this bucket over the selected range.
              </div>
            )}
          </div>
          <IntradaySeasonalityChart
            seasonality={data?.intradaySeasonality}
            metric={props.metric}
          />
        </div>
        <div className="flex items-center gap-2 pb-1">
          <input
            type="text"
            value={localTradeFilter}
            onChange={(e) => setLocalTradeFilter(e.target.value)}
            placeholder="filter trades..."
            className="w-40 rounded border border-slate-700 bg-slate-900 px-2 py-[1px] font-mono text-[10px] text-slate-200 placeholder:text-slate-600"
          />
          {localTradeFilter && (
            <span className="font-mono text-[9px] text-slate-500">
              {filteredTrades.length} of {data?.recentTrades?.length ?? 0}
            </span>
          )}
        </div>
        <div className="flex-1 overflow-auto rounded border border-slate-800">
          <table className="w-full text-left font-mono text-[11px]">
            <thead className="sticky top-0 bg-slate-900/80 text-[9.5px] uppercase tracking-wider text-slate-500">
              <tr>
                <Th> </Th><Th>Time</Th><Th>Type</Th><Th>Tape</Th><Th>Rate</Th>
                <Th>Risk</Th><Th>Notional</Th><Th data-testid="cell-contribution">Cell</Th><Th>Venue</Th><Th>Block?</Th>
              </tr>
            </thead>
            <tbody>
              {filteredTrades.length ? filteredTrades.map((t) => {
                const legs = t.legs ?? []
                const isMultiLeg = legs.length > 1
                const isExpanded = expandedPkgs.has(t.package_id)
                const inCellRisk = legs.filter((l) => l.inCell).reduce((s, l) => s + l.risk, 0)
                const inCellNotional = legs.filter((l) => l.inCell).reduce((s, l) => s + l.notional, 0)
                return (
                  <Fragment key={t.package_id}>
                    <tr
                      className="cursor-pointer border-t border-slate-800/60 hover:bg-indigo-500/10"
                      onClick={() => {
                        props.onSelectPackage(t.package_id)
                        props.onClose()
                      }}
                    >
                      <Td>
                        {isMultiLeg && (
                          <button
                            type="button"
                            data-testid="leg-expand"
                            className="text-slate-500 hover:text-slate-300"
                            onClick={(e) => { e.stopPropagation(); toggleExpand(t.package_id) }}
                          >
                            {isExpanded ? '▾' : '▸'}
                          </button>
                        )}
                      </Td>
                      <Td>{fmtTime(t.execution_start)}</Td>
                      <Td>
                        <span data-testid="pkg-type-badge" className={`rounded px-1 py-0.5 text-[9.5px] ring-1 ${pkgBadgeClass(t.package_type)}`}>
                          {t.package_type ?? '-'}
                        </span>
                      </Td>
                      <Td>{t.tape_label ?? '-'}</Td>
                      <Td>{fmtRate(t.weighted_fixed_rate)}</Td>
                      <Td>{t.total_risk == null ? '-' : fmtCompact(t.total_risk, 'dv01')}</Td>
                      <Td>{t.total_notional == null ? '-' : fmtCompact(t.total_notional, 'notional')}</Td>
                      <Td>
                        {legs.length > 0 ? (() => {
                          const inCellVal = props.metric === 'dv01' ? inCellRisk : inCellNotional
                          const inCellLegs = legs.filter((l) => l.inCell)
                          const showBreakdown = isMultiLeg && inCellLegs.length > 1
                          return (
                            <>
                              {fmtCompact(inCellVal, props.metric)}
                              {showBreakdown && (
                                <div data-testid="cell-leg-breakdown" className="font-mono text-[9px] text-slate-500">
                                  {inCellLegs.map((l) => `${fmtTenor(l.tenorYears)}:${fmtCompact(props.metric === 'dv01' ? l.risk : l.notional, props.metric)}`).join(' ')}
                                </div>
                              )}
                            </>
                          )
                        })() : '-'}
                      </Td>
                      <Td>{t.venue ?? '-'}</Td>
                      <Td>{t.is_block_any ? 'BLOCK' : ''}</Td>
                    </tr>
                    {isMultiLeg && isExpanded && legs.map((leg, i) => (
                      <tr key={`leg-${i}`} data-testid="leg-row"
                        className={`border-t border-slate-800/30 bg-slate-900/40 text-[10px] ${
                          leg.isRiskLeg ? 'text-amber-300 font-medium' : 'text-slate-400'
                        }`}>
                        <Td> </Td>
                        <Td> </Td>
                        <Td> </Td>
                        <Td>{`${leg.tenorYears}Y fwd ${leg.forwardStartYears.toFixed(2)}y`}</Td>
                        <Td> </Td>
                        <Td>{fmtCompact(leg.risk, 'dv01')}</Td>
                        <Td>{fmtCompact(leg.notional, 'notional')}</Td>
                        <Td>
                          <span className={leg.inCell ? 'text-emerald-400' : 'text-slate-600'}>
                            {leg.inCell ? '●' : '○'}
                          </span>
                        </Td>
                        <Td> </Td>
                        <Td> </Td>
                      </tr>
                    ))}
                  </Fragment>
                )
              }) : (
                <tr><td className="p-2 text-slate-500" colSpan={10}>No recent trades for this bucket.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </Dialog>
  )
}

function IntradaySeasonalityChart({
  seasonality,
  metric,
}: {
  seasonality: VolumeGridIntradaySeasonality | undefined
  metric: VolumeMetric
}): JSX.Element {
  const points = seasonality?.points ?? []
  const hasSeries = points.some((p) => p.current != null || p.average != null)
  const averageLabel = seasonality?.observedDays
    ? `${seasonality.observedDays}d avg`
    : 'avg'

  return (
    <div
      data-testid="volume-grid-cell-intraday-seasonality"
      className="h-[230px] rounded border border-slate-800 bg-slate-950/25 p-2"
    >
      <div className="mb-1 flex items-center justify-between gap-2 font-mono text-[10px] text-slate-400">
        <span className="uppercase tracking-wide text-slate-300">
          Intraday seasonality
        </span>
        <span>
          <span className="text-amber-300">current</span>
          <span className="mx-1 text-slate-600">/</span>
          <span className="text-amber-100/75">{averageLabel}</span>
        </span>
      </div>
      {hasSeries ? (
        <ResponsiveContainer width="100%" height="88%">
          <LineChart data={points} margin={{ top: 8, right: 14, bottom: 8, left: 4 }}>
            <CartesianGrid
              vertical={false}
              stroke="rgba(148,163,184,0.18)"
              strokeDasharray="3 3"
            />
            <XAxis
              dataKey="minuteOfDay"
              type="number"
              domain={[0, 1440]}
              ticks={SEASONALITY_X_TICKS}
              tickFormatter={(v) => fmtMinuteOfDay(Number(v))}
              tick={{ fontSize: 10, fill: '#94a3b8' }}
              axisLine={{ stroke: '#334155' }}
              tickLine={{ stroke: '#475569' }}
            />
            <YAxis
              tick={{ fontSize: 10, fill: '#94a3b8' }}
              tickFormatter={(v) => fmtCompact(Number(v), metric)}
              axisLine={{ stroke: '#334155' }}
              tickLine={{ stroke: '#475569' }}
              width={48}
            />
            <Tooltip
              contentStyle={{ background: '#0f172a', border: '1px solid #1e293b', fontSize: 11 }}
              labelFormatter={(label) => fmtMinuteOfDay(Number(label))}
              formatter={(value: unknown, name: string) => [
                value == null ? '-' : fmtCompact(Number(value), metric),
                name === 'current' ? 'current' : averageLabel,
              ]}
            />
            {seasonality?.asOfMinuteOfDay != null && (
              <ReferenceLine
                x={seasonality.asOfMinuteOfDay}
                stroke="#ef4444"
                strokeDasharray="4 3"
              />
            )}
            <Line
              type="stepAfter"
              dataKey="average"
              stroke="#fef3c7"
              strokeDasharray="4 3"
              strokeWidth={1.5}
              dot={false}
              connectNulls={false}
              isAnimationActive={false}
            />
            <Line
              type="stepAfter"
              dataKey="current"
              stroke="#fbbf24"
              strokeWidth={2}
              dot={false}
              connectNulls={false}
              isAnimationActive={false}
            />
          </LineChart>
        </ResponsiveContainer>
      ) : (
        <div className="flex h-[88%] items-center justify-center text-sm text-slate-500">
          No intraday seasonality for this bucket.
        </div>
      )}
    </div>
  )
}

function median(values: number[]): number {
  if (values.length === 0) return 0
  const s = [...values].sort((a, b) => a - b)
  const mid = Math.floor(s.length / 2)
  return s.length % 2 ? s[mid] : (s[mid - 1] + s[mid]) / 2
}

function Th({ children, ...rest }: { children: ReactNode } & Record<string, unknown>): JSX.Element {
  return <th className="px-2 py-1.5" {...rest}>{children}</th>
}
function Td({ children, className }: { children: ReactNode; className?: string }): JSX.Element {
  return <td className={`px-2 py-1.5 ${className ?? ''}`}>{children}</td>
}

function RangeToggle({ value, onChange }: { value: VolumeCellRange; onChange: (v: VolumeCellRange) => void }): JSX.Element {
  return (
    <div className="flex items-center rounded border border-slate-700 p-[1px]">
      {(['1M', '3M', '6M', '1Y'] as const).map((r) => (
        <button
          key={r} type="button" onClick={() => onChange(r)}
          className={`px-2 py-[1px] font-mono text-[10.5px] ${value === r ? 'bg-indigo-500/25 text-indigo-100' : 'text-slate-300 hover:bg-slate-800'}`}
        >
          {r}
        </button>
      ))}
    </div>
  )
}
