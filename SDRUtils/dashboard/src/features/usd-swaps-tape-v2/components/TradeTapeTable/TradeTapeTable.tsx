'use client'
// ABOUTME: PrimeReact DataTable for the USD swap tape v2.
import { useCallback, useEffect, useMemo, useRef, useState, type JSX } from 'react'
import { ChevronDown, ChevronRight, RefreshCw } from 'lucide-react'
import {
  DataTable,
  type DataTableFilterEvent,
  type DataTableFilterMeta,
  type DataTableSortEvent,
} from 'primereact/datatable'
import { ROW_ESTIMATE_PX } from '../../constants'
import type { UsdSwapTapeRow } from '../../types'
import { LegsSubTable } from './LegsSubTable'
import { getColumns, rowClassName, type MetricMode } from './columns'
import { applyColumnFilters, applyFuzzy, applySort } from './filter-pipeline'

// PrimeReact's `VirtualScrollerLazyEvent` types `first` / `last` as
// `number | VirtualScrollerState`; we only care about the numeric case and
// fall back safely otherwise.
type VirtualScrollerLazyLoadEvent = {
  first?: number | unknown
  last?: number | unknown
  rows?: number
}

export interface TradeTapeTableProps {
  rows: UsdSwapTapeRow[]
  loading: boolean
  loadingMore?: boolean
  onLoadMore?: () => void
  hasMore?: boolean
  expandedRows?: Record<string, boolean>
  onRowToggle?: (e: { data: Record<string, boolean> }) => void
  selected?: UsdSwapTapeRow[]
  onSelectionChange?: (e: { value: UsdSwapTapeRow[] }) => void
  onOpenTimeseries?: (row: UsdSwapTapeRow) => void
  search?: string
}

// Approximate page size used when extending the VirtualScroller's `totalRecords`
// past the currently-loaded row count. Matches the swaption tape's lazy-load
// pattern so the scroller keeps asking for more until the server reports
// `hasMore=false`.
const LAZY_LOAD_PAGE_SIZE = 50

export function TradeTapeTable(props: TradeTapeTableProps): JSX.Element {
  const {
    rows,
    loading,
    loadingMore,
    onLoadMore,
    hasMore,
    expandedRows,
    onRowToggle,
    selected,
    onSelectionChange,
  } = props

  // Guards against double-triggering `onLoadMore` within a single paging cycle.
  // The VirtualScroller's `onLazyLoad` can fire repeatedly while the user
  // continues to scroll; without this, we'd queue multiple fetches before the
  // first one resolves and the parent hook updates `loadingMore`.
  const loadMoreInFlight = useRef(false)
  useEffect(() => {
    if (!loadingMore) loadMoreInFlight.current = false
  }, [loadingMore])

  const requestLoadMore = useCallback(() => {
    if (!onLoadMore) return
    if (!hasMore) return
    if (loadingMore) return
    if (loadMoreInFlight.current) return
    loadMoreInFlight.current = true
    onLoadMore()
  }, [hasMore, loadingMore, onLoadMore])

  const [metricMode, setMetricMode] = useState<MetricMode>('dv01')
  const toggleMetric = useCallback(
    () => setMetricMode((m) => (m === 'dv01' ? 'notional' : 'dv01')),
    [],
  )

  const [filters, setFilters] = useState<DataTableFilterMeta>({})
  const [sortField, setSortField] = useState<string | null>(null)
  const [sortOrder, setSortOrder] = useState<1 | -1 | 0>(0)

  const displayRows = useMemo(() => {
    const fuzzied = applyFuzzy(rows, props.search ?? '')
    const filtered = applyColumnFilters(fuzzied, filters)
    return applySort(filtered, sortField, sortOrder)
  }, [rows, props.search, filters, sortField, sortOrder])

  // When column/search filters cut the visible list below the viewport height,
  // eagerly pull the next page so the scroll-triggered lazy load actually has
  // something to chew on. Mirrors the legacy auto-load in SwaptionTradeTape.
  useEffect(() => {
    if (!hasMore || loadingMore) return
    const approximateVisibleRows =
      typeof window !== 'undefined'
        ? Math.ceil((window.innerHeight * 0.7) / ROW_ESTIMATE_PX)
        : 20
    if (displayRows.length < approximateVisibleRows + 5) {
      requestLoadMore()
    }
  }, [displayRows.length, hasMore, loadingMore, requestLoadMore])

  const handleVirtualLoad = useCallback(
    (event: VirtualScrollerLazyLoadEvent) => {
      const first = typeof event.first === 'number' ? event.first : 0
      const last =
        typeof event.last === 'number'
          ? event.last
          : first + (event.rows ?? 0)
      if (last >= displayRows.length - 5) {
        requestLoadMore()
      }
    },
    [displayRows.length, requestLoadMore],
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
        /* Propagate the DataTable's scroll height down to the inner
         * VirtualScroller — with scrollHeight="flex" the wrapper sizes itself
         * via flex-basis, but the nested virtualscroller doesn't inherit that
         * height, so the scroll viewport collapses to 0 and no rows render.
         */
        .usd-swaps-tape-table .p-datatable-wrapper {
          flex: 1 1 auto;
          min-height: 0;
        }
        .usd-swaps-tape-table .p-datatable-wrapper > .p-virtualscroller,
        .usd-swaps-tape-table .p-virtualscroller {
          height: 100% !important;
          min-height: 0;
        }
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
        value={displayRows}
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
        filters={filters}
        onFilter={(e: DataTableFilterEvent) => setFilters(e.filters as DataTableFilterMeta)}
        filterDisplay="menu"
        sortField={sortField ?? undefined}
        sortOrder={sortOrder}
        onSort={(e: DataTableSortEvent) => {
          setSortField((e.sortField as string) || null)
          setSortOrder(((e.sortOrder as 1 | -1 | 0) ?? 0))
        }}
        className="usd-swaps-tape-table rounded-2xl border border-gray-800 bg-gradient-to-b from-gray-950 to-gray-900 text-gray-200 shadow-inner"
        tableStyle={{ minWidth: '1188px' }}
        resizableColumns
        columnResizeMode="fit"
        rowHover
        lazy
        totalRecords={
          hasMore ? displayRows.length + LAZY_LOAD_PAGE_SIZE : displayRows.length
        }
        virtualScrollerOptions={{
          itemSize: ROW_ESTIMATE_PX,
          lazy: true,
          // PrimeReact's VirtualScrollerLazyEvent widens first/last to
          // `number | VirtualScrollerState`; we only care about numeric
          // indices, so cast the handler rather than fight the type.
          onLazyLoad: handleVirtualLoad as any,
        }}
        pt={
          {
            headerCell: {
              // Match the swaption tape's denser header — slightly wider
              // x-padding, same 11px font size.
              className: 'py-1 px-2 text-[11px] !border-0',
            },
            bodyCell: {
              className: 'py-1 px-2 text-xs !border-0',
              // Keep the cell transparent so the tr-level tint shows through.
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
      {loadingMore ? (
        <div className="flex items-center justify-center gap-2 py-1 text-[11px] text-slate-400">
          <RefreshCw className="h-3 w-3 animate-spin" />
          Loading more packages...
        </div>
      ) : null}
    </div>
  )
}
