'use client'
// ABOUTME: PrimeReact Dialog with daily volume timeseries + recent trades
// for the clicked grid cell. Row click closes modal and routes the
// package_id to onSelectPackage (which writes a URL filter).

import type { JSX, ReactNode } from 'react'
import { useState } from 'react'
import { Dialog } from 'primereact/dialog'
import {
  Bar, BarChart, CartesianGrid, ReferenceLine, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from 'recharts'
import { useVolumeGridCell } from '../../hooks/useVolumeGridCell'
import { lookupLabel } from './buckets'
import type {
  VolumeCellRange, VolumeMetric,
  VolumeGridSchemaAxis,
} from '../../types/volume-grid.types'
import type {
  ForwardSchemaId,
  PackageTypeGroupId,
  TenorSchemaId,
} from '@/lib/usd-swaps-tape-v2/volumeGridBuckets'

const KEY_RANGE = 'usd-tape-v2:volume-grid:cell-range'

const fmtCompact = (n: number, _metric: VolumeMetric): string => {
  void _metric
  const abs = Math.abs(n)
  if (abs >= 1e9) return `${(abs / 1e9).toFixed(1)}B`
  if (abs >= 1e6) return `${(abs / 1e6).toFixed(1)}M`
  if (abs >= 1e3) return `${(abs / 1e3).toFixed(0)}k`
  return abs.toFixed(0)
}

const fmtRate = (r: number | null): string => (r == null ? '-' : `${(r * 100).toFixed(3)}%`)
const fmtTime = (ts: string): string =>
  new Date(ts).toLocaleString('en-US', {
    timeZone: 'America/New_York', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit',
  })

export interface VolumeGridCellModalProps {
  cell: { fwd: string; tenor: string } | null
  metric: VolumeMetric
  forwardSchema: ForwardSchemaId
  tenorSchema: TenorSchemaId
  packageType: PackageTypeGroupId
  forwardAxis: VolumeGridSchemaAxis | undefined
  tenorAxis: VolumeGridSchemaAxis | undefined
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

  const { data, error, isLoading } = useVolumeGridCell({
    cell: props.cell,
    metric: props.metric,
    range,
    forwardSchema: props.forwardSchema,
    tenorSchema: props.tenorSchema,
    packageType: props.packageType,
  })

  const headerLabel = props.cell
    ? `${lookupLabel(props.forwardAxis, props.cell.fwd)} × ${lookupLabel(props.tenorAxis, props.cell.tenor)} — Volume detail`
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
        <div data-testid="volume-grid-cell-chart" className="h-[40%] min-h-[200px]">
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
        <div className="flex-1 overflow-auto rounded border border-slate-800">
          <table className="w-full text-left font-mono text-[11px]">
            <thead className="sticky top-0 bg-slate-900/80 text-[9.5px] uppercase tracking-wider text-slate-500">
              <tr>
                <Th>Time</Th><Th>Type</Th><Th>Tape</Th><Th>Rate</Th>
                <Th>Risk</Th><Th>Notional</Th><Th>Venue</Th><Th>Block?</Th>
              </tr>
            </thead>
            <tbody>
              {data?.recentTrades.length ? data.recentTrades.map((t) => (
                <tr
                  key={t.package_id}
                  className="cursor-pointer border-t border-slate-800/60 hover:bg-indigo-500/10"
                  onClick={() => {
                    props.onSelectPackage(t.package_id)
                    props.onClose()
                  }}
                >
                  <Td>{fmtTime(t.execution_start)}</Td>
                  <Td>{t.package_type ?? '-'}</Td>
                  <Td>{t.tape_label ?? '-'}</Td>
                  <Td>{fmtRate(t.weighted_fixed_rate)}</Td>
                  <Td>{t.total_risk == null ? '-' : fmtCompact(t.total_risk, 'dv01')}</Td>
                  <Td>{t.total_notional == null ? '-' : fmtCompact(t.total_notional, 'notional')}</Td>
                  <Td>{t.venue ?? '-'}</Td>
                  <Td>{t.is_block_any ? 'BLOCK' : ''}</Td>
                  <Td className="hidden">{t.package_id}</Td>
                </tr>
              )) : (
                <tr><td className="p-2 text-slate-500" colSpan={8}>No recent trades for this bucket.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </Dialog>
  )
}

function median(values: number[]): number {
  if (values.length === 0) return 0
  const s = [...values].sort((a, b) => a - b)
  const mid = Math.floor(s.length / 2)
  return s.length % 2 ? s[mid] : (s[mid - 1] + s[mid]) / 2
}

function Th({ children }: { children: ReactNode }): JSX.Element {
  return <th className="px-2 py-1.5">{children}</th>
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
