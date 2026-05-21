'use client'
// ABOUTME: Pure render of the forward x tenor matrix + totals. No fetch.

import type { JSX } from 'react'
import { useMemo } from 'react'
import { VolumeGridCell } from './VolumeGridCell'
import { colorForPercentile, foregroundForPercentile } from './colorRamp'
import type {
  VolumeGridCell as Cell, VolumeGridColorMode, VolumeGridResponse, VolumeGridViewMode,
  VolumeMetric, VolumePeriod,
} from '../../types/volume-grid.types'
import type { PackageTypeGroupId } from '@/lib/usd-swaps-tape-v2/volumeGridBuckets'

export interface VolumeGridProps {
  data: VolumeGridResponse
  metric: VolumeMetric
  period: VolumePeriod
  viewMode: VolumeGridViewMode
  colorMode: VolumeGridColorMode
  packageType?: PackageTypeGroupId
  uppercaseLabels?: boolean
  onCellClick: (id: { fwd: string; tenor: string }) => void
  onCellHover?: (id: { fwd: string; tenor: string }) => void
  onCellLeave?: () => void
}

export function VolumeGrid({ data, metric, period, viewMode, colorMode, packageType, uppercaseLabels = true, onCellClick, onCellHover, onCellLeave }: VolumeGridProps): JSX.Element {
  const cellMap = useMemo(() => {
    const m = new Map<string, Cell>()
    for (const c of data.cells) m.set(`${c.fwd}|${c.tenor}`, c)
    return m
  }, [data.cells])
  const gridMaxCurrent = useMemo(
    () =>
      data.cells.reduce(
        (max, c) =>
          c.tradeCount > 0 && Number.isFinite(c.current)
            ? Math.max(max, Math.abs(c.current))
            : max,
        0,
      ),
    [data.cells],
  )
  const forwardAxis = data.axes.forward
  const tenorAxis = data.axes.tenor
  const labelCase = uppercaseLabels ? 'uppercase' : 'normal-case'
  return (
    <div
      className="grid gap-px font-mono text-[10.5px] text-slate-300"
      style={{
        gridTemplateColumns: `minmax(60px,auto) repeat(${tenorAxis.buckets.length},minmax(58px,1fr)) minmax(64px,auto)`,
      }}
    >
      <div />
      {tenorAxis.buckets.map((t) => (
        <div
          key={t.id}
          data-testid="volume-grid-col-label"
          className={`px-1 pb-1 text-center text-[9.5px] ${labelCase} tracking-wider text-slate-500`}
        >
          {t.label}
        </div>
      ))}
      <div
        data-testid="volume-grid-col-label"
        className={`px-1 pb-1 text-center text-[9.5px] ${labelCase} tracking-wider text-slate-400`}
      >
        Total
      </div>
      {forwardAxis.buckets.map((f) => (
        <RowFragment
          key={f.id}
          fwd={f.id}
          fwdLabelText={f.label}
          cellMap={cellMap}
          metric={metric}
          period={period}
          viewMode={viewMode}
          colorMode={colorMode}
          packageType={packageType}
          gridMaxCurrent={gridMaxCurrent}
          tenorAxis={tenorAxis}
          forwardAxis={forwardAxis}
          rowTotal={data.totals.rowTotals[f.id]}
          onCellClick={onCellClick}
          onCellHover={onCellHover}
          onCellLeave={onCellLeave}
        />
      ))}
      <div
        data-testid="volume-grid-row-label"
        className="flex items-center px-1 text-[9.5px] uppercase tracking-wider text-slate-400"
      >
        Total
      </div>
      {tenorAxis.buckets.map((t) => (
        <TotalCell
          key={t.id}
          value={data.totals.colTotals[t.id]?.current ?? 0}
          percentile={data.totals.colTotals[t.id]?.percentile ?? null}
        />
      ))}
      <TotalCell
        value={data.totals.grand.current}
        percentile={data.totals.grand.percentile}
        emphasized
      />
    </div>
  )
}

function RowFragment(props: {
  fwd: string
  fwdLabelText: string
  cellMap: Map<string, Cell>
  metric: VolumeMetric
  period: VolumePeriod
  viewMode: VolumeGridViewMode
  colorMode: VolumeGridColorMode
  packageType?: PackageTypeGroupId
  gridMaxCurrent: number
  forwardAxis: VolumeGridResponse['axes']['forward']
  tenorAxis: VolumeGridResponse['axes']['tenor']
  rowTotal: { current: number; percentile: number | null } | undefined
  onCellClick: VolumeGridProps['onCellClick']
  onCellHover?: VolumeGridProps['onCellHover']
  onCellLeave?: VolumeGridProps['onCellLeave']
}): JSX.Element {
  return (
    <>
      <div
        data-testid="volume-grid-row-label"
        className="flex items-center px-1 text-[9.5px] uppercase tracking-wider text-slate-400"
      >
        {props.fwdLabelText}
      </div>
      {props.tenorAxis.buckets.map((t) => {
        const cell =
          props.cellMap.get(`${props.fwd}|${t.id}`) ??
          ({
            fwd: props.fwd,
            tenor: t.id,
            current: 0, idbCurrent: 0, custyCurrent: 0,
            outrightCurrent: 0, curveCurrent: 0, flyCurrent: 0, otherCurrent: 0,
            tradeCount: 0,
            baseline: { p25: 0, p50: 0, p75: 0, min: 0, max: 0, n: 0 },
            percentile: null,
          } as Cell)
        return (
          <div
            key={t.id}
            data-testid="volume-grid-cell"
            onMouseEnter={props.onCellHover ? () => props.onCellHover!({ fwd: props.fwd, tenor: t.id }) : undefined}
            onMouseLeave={props.onCellLeave}
          >
            <VolumeGridCell
              cell={cell}
              metric={props.metric}
              period={props.period}
              viewMode={props.viewMode}
              colorMode={props.colorMode}
              colorPercentile={
                props.gridMaxCurrent > 0
                  ? (Math.abs(cell.current) / props.gridMaxCurrent) * 100
                  : null
              }
              forwardAxis={props.forwardAxis}
              tenorAxis={props.tenorAxis}
              packageType={props.packageType}
              onClick={props.onCellClick}
            />
          </div>
        )
      })}
      <TotalCell
        value={props.rowTotal?.current ?? 0}
        percentile={props.rowTotal?.percentile ?? null}
      />
    </>
  )
}

function TotalCell(props: {
  value: number
  percentile: number | null
  emphasized?: boolean
}): JSX.Element {
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
