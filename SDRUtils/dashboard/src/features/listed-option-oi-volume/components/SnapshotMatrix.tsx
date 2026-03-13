'use client'

import { useMemo, useRef } from 'react'
import { useVirtualizer } from '@tanstack/react-virtual'

import type {
  ListedOptionMetricField,
  ListedOptionSeriesConfig,
  ListedOptionSnapshotCell,
  ListedOptionSnapshotResponse,
  ListedOptionSnapshotRow,
} from '../types'
import { formatNumber } from '../utils'

type Props = {
  snapshot: ListedOptionSnapshotResponse
  rows: ListedOptionSnapshotRow[]
  onSelectSeries: (config: ListedOptionSeriesConfig) => void
}

const ROW_HEIGHT = 36
const MATRIX_ZOOM = 0.85
const MATRIX_VIEWPORT_HEIGHT = 760

function formatCellValue(value: number | null, field: ListedOptionMetricField) {
  if (value === null || !Number.isFinite(value)) return '--'
  const decimals = field === 'open_interest' || field === 'volume' ? 0 : 0
  return formatNumber(value, decimals)
}

function buildHeatmapStyle(value: number | null, field: ListedOptionMetricField, maxLevel: number, maxAbsChange: number) {
  if (value === null || !Number.isFinite(value)) {
    return { backgroundColor: 'rgba(15,23,42,0.2)' }
  }

  if (field === 'open_interest' || field === 'volume') {
    const intensity = maxLevel > 0 ? Math.min(1, value / maxLevel) : 0
    return {
      backgroundColor: `rgba(45, 212, 191, ${0.08 + intensity * 0.38})`,
    }
  }

  const intensity = maxAbsChange > 0 ? Math.min(1, Math.abs(value) / maxAbsChange) : 0
  const [r, g, b] = value >= 0 ? [16, 185, 129] : [248, 113, 113]
  return {
    backgroundColor: `rgba(${r}, ${g}, ${b}, ${0.08 + intensity * 0.4})`,
  }
}

function cellTitle(cell: ListedOptionSnapshotCell | null) {
  if (!cell) return 'No stored data'
  const parts = [
    cell.explicitOptionSymbol ?? '',
    cell.strike !== null ? `Strike ${formatNumber(cell.strike, 3)}` : '',
    cell.deltaAbs !== null ? `Delta ${formatNumber(cell.deltaAbs, 2)}` : '',
    cell.atmOffsetBps !== null ? `Offset ${formatNumber(cell.atmOffsetBps, 2)}bp` : '',
  ].filter(Boolean)
  return parts.join(' | ')
}

export function SnapshotMatrix({ snapshot, rows, onSelectSeries }: Props) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const rowVirtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: 10,
  })

  const gridTemplateColumns = useMemo(
    () => `140px repeat(${snapshot.contractGroups.length * 2}, minmax(84px, 84px))`,
    [snapshot.contractGroups.length]
  )

  const { maxLevel, maxAbsChange } = useMemo(() => {
    const values = rows.flatMap((row) =>
      snapshot.contractGroups.flatMap((group) => [
        row.cells[group.id]?.call?.value ?? null,
        row.cells[group.id]?.put?.value ?? null,
      ])
    )
    const numericValues = values.filter((value): value is number => value !== null && Number.isFinite(value))
    return {
      maxLevel: numericValues.length ? Math.max(...numericValues.map((value) => Math.max(0, value))) : 0,
      maxAbsChange: numericValues.length ? Math.max(...numericValues.map((value) => Math.abs(value))) : 0,
    }
  }, [rows, snapshot.contractGroups])

  return (
    <div
      ref={scrollRef}
      className="relative overflow-auto rounded-xl border border-slate-800/80 bg-slate-950/75"
      style={{ height: `${MATRIX_VIEWPORT_HEIGHT}px` }}
    >
      <div className="min-w-max" style={{ zoom: MATRIX_ZOOM }}>
        <div className="sticky top-0 z-30 border-b border-slate-800/80 bg-slate-950/95 backdrop-blur">
          <div className="grid" style={{ gridTemplateColumns }}>
            <div className="sticky left-0 z-40 border-r border-slate-800/80 bg-slate-950/95 px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400">
              {snapshot.rowAxis.replace('_', ' ')}
            </div>
            {snapshot.contractGroups.map((group) => (
              <div
                key={group.id}
                className="col-span-2 border-l border-slate-800/80 px-2 py-2 text-center"
              >
                <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-100">
                  {group.displayLabel}
                </div>
                <div className="mt-1 text-[10px] text-slate-500">
                  {group.forwardPrice !== null ? formatNumber(group.forwardPrice, 4) : '--'} |{' '}
                  {group.dteDays !== null ? `${group.dteDays} DTE` : '--'}
                </div>
              </div>
            ))}
          </div>
          <div className="grid border-t border-slate-800/70" style={{ gridTemplateColumns }}>
            <div className="sticky left-0 z-40 border-r border-slate-800/80 bg-slate-950/95 px-3 py-2 text-[10px] uppercase tracking-[0.16em] text-slate-500">
              Row
            </div>
            {snapshot.contractGroups.flatMap((group) => [
              <div
                key={`${group.id}:call`}
                className="border-l border-slate-800/70 px-2 py-2 text-center text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500"
              >
                Call
              </div>,
              <div
                key={`${group.id}:put`}
                className="border-l border-slate-800/70 px-2 py-2 text-center text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500"
              >
                Put
              </div>,
            ])}
          </div>
        </div>

        <div style={{ height: `${rowVirtualizer.getTotalSize()}px`, position: 'relative' }}>
          {rowVirtualizer.getVirtualItems().map((virtualRow) => {
            const row = rows[virtualRow.index]!
            return (
              <div
                key={row.rowKey}
                className="absolute left-0 right-0"
                style={{
                  transform: `translateY(${virtualRow.start}px)`,
                }}
              >
                <div
                  className="grid border-b border-slate-900/80"
                  style={{ gridTemplateColumns, height: `${ROW_HEIGHT}px` }}
                >
                  <div className="sticky left-0 z-20 border-r border-slate-800/80 bg-slate-950/95 px-3 py-2 text-[12px] font-medium text-slate-200">
                    {row.rowLabel}
                  </div>
                  {snapshot.contractGroups.flatMap((group) => {
                    const cellBucket = row.cells[group.id]
                    const renderCell = (
                      sideKey: 'call' | 'put',
                      cell: ListedOptionSnapshotCell | null
                    ) => (
                      <button
                        key={`${group.id}:${sideKey}:${row.rowKey}`}
                        type="button"
                        title={cellTitle(cell)}
                        onClick={() => {
                          if (cell?.chartSeries) {
                            onSelectSeries(cell.chartSeries)
                          }
                        }}
                        className="border-l border-slate-900/80 px-2 text-right text-[12px] font-medium text-slate-100 transition hover:outline hover:outline-1 hover:outline-sky-400/60"
                        style={buildHeatmapStyle(cell?.value ?? null, snapshot.field, maxLevel, maxAbsChange)}
                      >
                        {formatCellValue(cell?.value ?? null, snapshot.field)}
                      </button>
                    )

                    return [
                      renderCell('call', cellBucket?.call ?? null),
                      renderCell('put', cellBucket?.put ?? null),
                    ]
                  })}
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
