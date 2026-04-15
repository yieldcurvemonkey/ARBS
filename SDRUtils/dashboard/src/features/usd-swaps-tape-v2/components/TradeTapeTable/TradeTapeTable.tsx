'use client'
// ABOUTME: PrimeReact DataTable for the USD swap tape v2.
import { useCallback, useState, type JSX } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { DataTable } from 'primereact/datatable'
import type { UsdSwapTapeRow } from '../../types'
import { LegsSubTable } from './LegsSubTable'
import { getColumns, rowClassName, type MetricMode } from './columns'

export interface TradeTapeTableProps {
  rows: UsdSwapTapeRow[]
  loading: boolean
  onLoadMore?: () => void
  hasMore?: boolean
  expandedRows?: Record<string, boolean>
  onRowToggle?: (e: { data: Record<string, boolean> }) => void
  selected?: UsdSwapTapeRow[]
  onSelectionChange?: (e: { value: UsdSwapTapeRow[] }) => void
  onOpenTimeseries?: (row: UsdSwapTapeRow) => void
}

export function TradeTapeTable(props: TradeTapeTableProps): JSX.Element {
  const {
    rows,
    loading,
    onLoadMore,
    hasMore,
    expandedRows,
    onRowToggle,
    selected,
    onSelectionChange,
  } = props

  const [metricMode, setMetricMode] = useState<MetricMode>('dv01')
  const toggleMetric = useCallback(
    () => setMetricMode((m) => (m === 'dv01' ? 'notional' : 'dv01')),
    [],
  )

  const selectedIds = new Set((selected ?? []).map((row) => row.package_id))

  const toggleRowExpansion = (row: UsdSwapTapeRow) => {
    if (!onRowToggle) return
    const next = { ...(expandedRows ?? {}) }
    if (next[row.package_id]) delete next[row.package_id]
    else next[row.package_id] = true
    onRowToggle({ data: next })
  }

  const expanderBody = (row: UsdSwapTapeRow) => {
    const canExpand = (row.legs_json ?? []).length > 0
    if (!canExpand) return <span className="inline-flex h-6 w-6" />
    const isExpanded = !!expandedRows?.[row.package_id]
    return (
      <button
        type="button"
        onClick={(event) => {
          event.stopPropagation()
          toggleRowExpansion(row)
        }}
        className="inline-flex h-6 w-6 items-center justify-center rounded border border-gray-700 text-gray-300 hover:border-gray-500 hover:text-gray-100"
        aria-label={isExpanded ? 'Collapse package details' : 'Expand package details'}
      >
        {isExpanded ? (
          <ChevronDown className="h-4 w-4" />
        ) : (
          <ChevronRight className="h-4 w-4" />
        )}
      </button>
    )
  }

  const dataTableRowClassName = (row: UsdSwapTapeRow) =>
    [
      'h-10 text-sm !text-gray-200 transition-[filter,box-shadow] hover:brightness-110 hover:shadow-[inset_0_0_0_1px_rgba(148,163,184,0.5)]',
      rowClassName(row),
      row.manual_link_id || row.manual_package_id ? 'manual-linked-row' : '',
      selectedIds.has(row.package_id) ? 'selected-share-row' : '',
    ]
      .join(' ')
      .trim()

  return (
    <div
      className="flex flex-col flex-1 bg-slate-950 text-slate-100"
      data-testid="trade-tape-table"
    >
      <style jsx global>{`
        .usd-swaps-tape-table .p-datatable-tbody > tr,
        .usd-swaps-tape-table .p-datatable-tbody > tr > td {
          border: none !important;
        }
        .usd-swaps-tape-table
          .p-datatable-tbody
          > tr.manual-linked-row
          > td {
          background-color: rgba(245, 158, 11, 0.18) !important;
        }
        .usd-swaps-tape-table
          .p-datatable-tbody
          > tr.selected-share-row
          > td {
          box-shadow:
            inset 0 1px 0 rgba(125, 211, 252, 0.4),
            inset 0 -1px 0 rgba(125, 211, 252, 0.4) !important;
        }
        .usd-swaps-tape-table
          .p-datatable-tbody
          > tr.selected-share-row
          > td:first-child {
          box-shadow:
            inset 1px 0 0 rgba(125, 211, 252, 0.4),
            inset 0 1px 0 rgba(125, 211, 252, 0.4),
            inset 0 -1px 0 rgba(125, 211, 252, 0.4) !important;
        }
        .usd-swaps-tape-table
          .p-datatable-tbody
          > tr.selected-share-row
          > td:last-child {
          box-shadow:
            inset -1px 0 0 rgba(125, 211, 252, 0.4),
            inset 0 1px 0 rgba(125, 211, 252, 0.4),
            inset 0 -1px 0 rgba(125, 211, 252, 0.4) !important;
        }
      `}</style>
      <DataTable
        value={rows}
        dataKey="package_id"
        size="small"
        scrollable
        scrollHeight="flex"
        stripedRows={false}
        rowClassName={dataTableRowClassName as any}
        loading={loading}
        selectionMode={onSelectionChange ? 'multiple' : undefined}
        cellSelection={false}
        metaKeySelection={false}
        selection={selected as any}
        onSelectionChange={onSelectionChange as any}
        expandedRows={expandedRows as any}
        rowExpansionTemplate={(row: UsdSwapTapeRow) => (
          <div className="-mx-2 -my-1 px-0 py-0">
            <LegsSubTable row={row} />
          </div>
        )}
        className="usd-swaps-tape-table rounded-2xl border border-gray-800 bg-gradient-to-b from-gray-950 to-gray-900 text-gray-200 shadow-inner"
        tableStyle={{ minWidth: '1700px' }}
        resizableColumns
        columnResizeMode="fit"
        rowHover
        pt={
          {
            bodyCell: {
              className: 'py-1 px-2 text-xs !border-0',
              style: { backgroundColor: 'transparent' },
            },
          } as any
        }
      >
        {getColumns({
          selection: !!onSelectionChange,
          expanderBody,
          metricMode,
          onToggleMetric: toggleMetric,
        })}
      </DataTable>
      {hasMore ? (
        <div className="flex justify-center py-2">
          <button
            type="button"
            className="rounded bg-slate-800 px-3 py-1.5 text-xs text-slate-200 hover:bg-slate-700"
            onClick={onLoadMore}
            disabled={loading}
          >
            Load more
          </button>
        </div>
      ) : null}
    </div>
  )
}
