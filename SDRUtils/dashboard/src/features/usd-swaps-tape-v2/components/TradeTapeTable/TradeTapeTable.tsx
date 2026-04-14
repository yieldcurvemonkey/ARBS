'use client'
// ABOUTME: Virtual-scrolling PrimeReact DataTable for the USD swap tape v2.
import type { JSX } from 'react'
import { DataTable } from 'primereact/datatable'
import { ROW_ESTIMATE_PX } from '../../constants'
import type { UsdSwapTapeRow } from '../../types'
import { LegsSubTable } from './LegsSubTable'
import { getColumns, rowClassName } from './columns'

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

  return (
    <div
      className="flex flex-col flex-1 bg-slate-950 text-slate-100"
      data-testid="trade-tape-table"
    >
      <DataTable
        value={rows}
        dataKey="package_id"
        size="small"
        scrollable
        scrollHeight="flex"
        virtualScrollerOptions={{ itemSize: ROW_ESTIMATE_PX, lazy: !!onLoadMore }}
        stripedRows={false}
        rowClassName={rowClassName as any}
        loading={loading}
        selectionMode={onSelectionChange ? 'multiple' : undefined}
        selection={selected as any}
        onSelectionChange={onSelectionChange as any}
        expandedRows={expandedRows as any}
        onRowToggle={onRowToggle as any}
        rowExpansionTemplate={(row: UsdSwapTapeRow) => <LegsSubTable row={row} />}
        className="text-sm"
        tableStyle={{ minWidth: '1600px' }}
      >
        {getColumns({ expansion: true, selection: !!onSelectionChange })}
      </DataTable>
      {hasMore ? (
        <div className="py-2 flex justify-center">
          <button
            type="button"
            className="text-xs px-3 py-1.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-200"
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
