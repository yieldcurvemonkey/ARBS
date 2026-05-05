'use client'
// ABOUTME: Pure render of the forward x tenor matrix + totals. No fetch.

import type { JSX } from 'react'
import { useMemo } from 'react'
import { FORWARD_AXIS, TENOR_AXIS, fwdLabel } from './buckets'
import { VolumeGridCell } from './VolumeGridCell'
import { colorForPercentile, foregroundForPercentile } from './colorRamp'
import type {
  VolumeGridCell as Cell, VolumeGridResponse, VolumeMetric, VolumePeriod,
} from '../../types/volume-grid.types'

export interface VolumeGridProps {
  data: VolumeGridResponse
  metric: VolumeMetric
  period: VolumePeriod
  onCellClick: (id: { fwd: Cell['fwd']; tenor: Cell['tenor'] }) => void
}

export function VolumeGrid({ data, metric, period, onCellClick }: VolumeGridProps): JSX.Element {
  const cellMap = useMemo(() => {
    const m = new Map<string, Cell>()
    for (const c of data.cells) m.set(`${c.fwd}|${c.tenor}`, c)
    return m
  }, [data.cells])
  return (
    <div
      className="grid gap-px font-mono text-[10.5px] text-slate-300"
      style={{
        gridTemplateColumns: `minmax(54px,auto) repeat(${TENOR_AXIS.length},minmax(58px,1fr)) minmax(64px,auto)`,
      }}
    >
      <div />
      {TENOR_AXIS.map((t) => (
        <div
          key={t.id}
          data-testid="volume-grid-col-label"
          className="px-1 pb-1 text-center text-[9.5px] uppercase tracking-wider text-slate-500"
        >
          {t.label}
        </div>
      ))}
      <div
        data-testid="volume-grid-col-label"
        className="px-1 pb-1 text-center text-[9.5px] uppercase tracking-wider text-slate-400"
      >
        Total
      </div>
      {FORWARD_AXIS.map((f) => (
        <RowFragment
          key={f.id}
          fwd={f.id}
          fwdLabelText={fwdLabel(f.id)}
          cellMap={cellMap}
          metric={metric}
          period={period}
          rowTotal={data.totals.rowTotals[f.id]}
          onCellClick={onCellClick}
        />
      ))}
      <div
        data-testid="volume-grid-row-label"
        className="flex items-center px-1 text-[9.5px] uppercase tracking-wider text-slate-400"
      >
        Total
      </div>
      {TENOR_AXIS.map((t) => (
        <TotalCell
          key={t.id}
          value={data.totals.colTotals[t.id]?.current ?? 0}
          percentile={data.totals.colTotals[t.id]?.percentile ?? null}
          metric={metric}
        />
      ))}
      <TotalCell
        value={data.totals.grand.current}
        percentile={data.totals.grand.percentile}
        metric={metric}
        emphasized
      />
    </div>
  )
}

function RowFragment(props: {
  fwd: Cell['fwd']
  fwdLabelText: string
  cellMap: Map<string, Cell>
  metric: VolumeMetric
  period: VolumePeriod
  rowTotal: { current: number; percentile: number | null } | undefined
  onCellClick: VolumeGridProps['onCellClick']
}): JSX.Element {
  return (
    <>
      <div
        data-testid="volume-grid-row-label"
        className="flex items-center px-1 text-[9.5px] uppercase tracking-wider text-slate-400"
      >
        {props.fwdLabelText}
      </div>
      {TENOR_AXIS.map((t) => {
        const cell =
          props.cellMap.get(`${props.fwd}|${t.id}`) ??
          ({
            fwd: props.fwd,
            tenor: t.id,
            current: 0, tradeCount: 0,
            baseline: { p25: 0, p50: 0, p75: 0, min: 0, max: 0, n: 0 },
            percentile: null,
          } as Cell)
        return (
          <div key={t.id} data-testid="volume-grid-cell">
            <VolumeGridCell
              cell={cell}
              metric={props.metric}
              period={props.period}
              onClick={props.onCellClick}
            />
          </div>
        )
      })}
      <TotalCell
        value={props.rowTotal?.current ?? 0}
        percentile={props.rowTotal?.percentile ?? null}
        metric={props.metric}
      />
    </>
  )
}

function TotalCell(props: {
  value: number
  percentile: number | null
  metric: VolumeMetric
  emphasized?: boolean
}): JSX.Element {
  void props.metric
  const fmt = (() => {
    const abs = Math.abs(props.value)
    if (abs >= 1e9) return `${(abs / 1e9).toFixed(1)}B`
    if (abs >= 1e6) return `${(abs / 1e6).toFixed(1)}M`
    if (abs >= 1e3) return `${(abs / 1e3).toFixed(0)}k`
    return abs.toFixed(0)
  })()
  return (
    <div
      style={{ backgroundColor: colorForPercentile(props.percentile) }}
      className={`flex h-12 flex-col items-center justify-center rounded-sm border border-slate-700/60 text-center text-[11px] tabular-nums ${foregroundForPercentile(props.percentile)} ${props.emphasized ? 'font-semibold ring-1 ring-indigo-400/40' : ''}`}
    >
      <span>{fmt}</span>
      {props.percentile != null && <span className="text-[9.5px] text-slate-400">P{Math.round(props.percentile)}</span>}
    </div>
  )
}
