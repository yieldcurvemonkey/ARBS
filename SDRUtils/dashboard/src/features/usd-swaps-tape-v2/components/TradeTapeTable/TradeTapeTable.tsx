'use client'
// ABOUTME: PrimeReact DataTable for the USD swap tape v2.
// NOTE(feedback-round-1): removed the global fuzzy search input, AND/OR
// toggle, and the manual filter pipeline in favor of PrimeReact's native
// per-column filtering (filters prop) and sort (sortField / sortOrder),
// both URL-synced through useColumnFilters.
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  type JSX,
  type ReactNode,
} from 'react'
import { ChevronDown, ChevronRight, RefreshCw } from 'lucide-react'
import {
  DataTable,
  type DataTableFilterEvent,
  type DataTableFilterMeta,
  type DataTableSortEvent,
} from 'primereact/datatable'
import { useState } from 'react'
import { ROW_ESTIMATE_PX } from '../../constants'
import {
  DEFAULT_SORT_FIELD,
  DEFAULT_SORT_ORDER,
  useColumnFilters,
} from '../../hooks'
import type { UsdSwapTapeRow } from '../../types'
import { LegsSubTable } from './LegsSubTable'
import { getColumns, rowClassName, type MetricMode } from './columns'
import {
  hasActiveConstraints,
  matchFilterMetaWithRow,
} from './filter-utils'
import { computeAnchorAdjustedScrollTop } from './scroll-anchor'

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
  onLoadMore?: () => void | Promise<void>
  hasMore?: boolean
  expandedRows?: Record<string, boolean>
  /**
   * Full-replacement callback kept for PrimeReact's native `onRowToggle`
   * event (fires if the user triggers expansion through PrimeReact's own
   * machinery rather than our custom button).
   */
  onRowToggle?: (e: { data: Record<string, boolean> }) => void
  /**
   * Preferred per-row toggle — takes a packageId and is expected to use
   * functional setState on the caller's side so multiple successive clicks
   * never drop prior expansion state. Fixes the "expanding row B closes row
   * A" bug caused by stale-closure reads of `expandedRows` prop.
   */
  onToggleRow?: (packageId: string) => void
  selected?: UsdSwapTapeRow[]
  onSelectionChange?: (e: { value: UsdSwapTapeRow[] }) => void
  onOpenTimeseries?: (row: UsdSwapTapeRow) => void
  /**
   * Package ID currently focused in the analytics dock. Tape highlights
   * the matching row with the indigo focused-trade treatment that mirrors
   * the dock's "Focused trade" context bar (see Analytics Dock design).
   */
  focusedPackageId?: string | null
  /**
   * Optional right-side slot rendered in the filter bar — used by the parent
   * to inject extras like a "Link N selected" action without pushing filter
   * state back up.
   */
  actionSlot?: ReactNode
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
    onToggleRow,
    selected,
    onSelectionChange,
    focusedPackageId,
    actionSlot,
  } = props

  // URL-backed column filter + sort state.
  const columnFilters = useColumnFilters()

  // Guards against double-triggering `onLoadMore` within a single paging cycle.
  // Historically this flag could get stuck `true` when `onLoadMore` bailed
  // silently (e.g. poll in flight), leaving pagination dead until a page
  // refresh — the exact "initial filter needs a refresh" regression reported
  // by traders. Reset is now tied to the awaited promise's finally block
  // instead of only to `loadingMore` transitions.
  const loadMoreInFlight = useRef(false)
  useEffect(() => {
    if (!loadingMore) loadMoreInFlight.current = false
  }, [loadingMore])

  const requestLoadMore = useCallback(async () => {
    if (!onLoadMore) return
    if (!hasMore) return
    if (loadingMore) return
    if (loadMoreInFlight.current) return
    loadMoreInFlight.current = true
    try {
      await onLoadMore()
    } finally {
      loadMoreInFlight.current = false
    }
  }, [hasMore, loadingMore, onLoadMore])

  const [metricMode, setMetricMode] = useState<MetricMode>('dv01')
  const toggleMetric = useCallback(
    () => setMetricMode((m) => (m === 'dv01' ? 'notional' : 'dv01')),
    [],
  )

  const effectiveSortField = columnFilters.sortField ?? DEFAULT_SORT_FIELD
  const effectiveSortOrder: 1 | -1 | 0 =
    (columnFilters.sortOrder ?? DEFAULT_SORT_ORDER) as 1 | -1 | 0

  // PrimeReact's DataTable runs in `lazy` mode (required so the
  // VirtualScroller can drive cursor pagination through onLazyLoad). In lazy
  // mode the table does NOT apply `filters` or `sortField`/`sortOrder` to the
  // `value` prop — it only emits the corresponding events. We therefore have
  // to filter + sort the rows ourselves before handing them to the table,
  // otherwise the per-column filter overlay updates URL state but the visible
  // rows never change (the bug we are fixing).
  const activeFilterEntries = useMemo(() => {
    return Object.entries(columnFilters.filters ?? {}).filter(([, meta]) =>
      hasActiveConstraints(meta),
    )
  }, [columnFilters.filters])

  const displayRows = useMemo<UsdSwapTapeRow[]>(() => {
    let result: UsdSwapTapeRow[] = rows
    if (activeFilterEntries.length > 0) {
      result = result.filter((row) =>
        activeFilterEntries.every(([field, meta]) =>
          // Use the row+leg fallback resolver: leg-only fields like
          // `platform_identifier` and `lifecycle_type` are null at the
          // package level, so a plain `row[field]` lookup rejected
          // every package regardless of the user's input. The resolver
          // mirrors the body cell's leg fallback so a Platform filter
          // of "TWSF" matches packages whose first leg is on TWSF.
          matchFilterMetaWithRow(
            row as Record<string, unknown> & {
              legs_json?: Array<Record<string, unknown>>
            },
            field,
            meta,
          ),
        ),
      )
    }
    if (effectiveSortField && effectiveSortOrder !== 0) {
      const field = effectiveSortField
      const dir = effectiveSortOrder === 1 ? 1 : -1
      result = [...result].sort((a, b) => {
        const av = (a as Record<string, unknown>)[field] as
          | string
          | number
          | null
          | undefined
        const bv = (b as Record<string, unknown>)[field] as
          | string
          | number
          | null
          | undefined
        // Push nullish to the bottom regardless of direction.
        if (av == null && bv == null) return 0
        if (av == null) return 1
        if (bv == null) return -1
        if (typeof av === 'number' && typeof bv === 'number') {
          return (av - bv) * dir
        }
        return String(av).localeCompare(String(bv)) * dir
      })
    }
    return result
  }, [rows, activeFilterEntries, effectiveSortField, effectiveSortOrder])

  const filtersActive = activeFilterEntries.length > 0

  // Max rows to chain-load when filters are active. Filters are client-side,
  // so surfacing every match means dragging down every cursor page the
  // server will give us; cap at 20k to bound the pathological case.
  const MAX_FILTERED_AUTOLOAD_ROWS = 20_000

  useEffect(() => {
    if (!hasMore || loadingMore) return
    if (filtersActive) {
      // Column filter is on: the viewport-fill heuristic is wrong here —
      // the user wants to see every row that matches their filter, not
      // just enough to cover the screen. Chain-load until `hasMore`
      // flips false (or the safety cap trips) so the UI never leaves
      // the trader staring at a short filtered result set while there
      // are still unscanned rows on the server. Fixes the "need to
      // refresh after applying a column filter" desk report.
      if (rows.length < MAX_FILTERED_AUTOLOAD_ROWS) {
        void requestLoadMore()
      }
      return
    }
    const approximateVisibleRows =
      typeof window !== 'undefined'
        ? Math.ceil((window.innerHeight * 0.7) / ROW_ESTIMATE_PX)
        : 20
    if (displayRows.length < approximateVisibleRows + 5) {
      void requestLoadMore()
    }
  }, [
    displayRows.length,
    rows.length,
    filtersActive,
    hasMore,
    loadingMore,
    requestLoadMore,
  ])

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

  // Belt-and-suspenders scroll trigger. PrimeReact's onLazyLoad only fires
  // when the virtualscroller decides it needs a fresh page; under slow
  // scroll the `last` index can stay put for long stretches and the loader
  // never kicks. Attach a raw scroll listener on the scrollable element and
  // fire `requestLoadMore` as soon as the user is within ~1.5 viewports of
  // the tail — this covers the "slowly scrolling doesn't fetch" bug the
  // desk reported.
  const tableWrapperRef = useRef<HTMLDivElement | null>(null)

  // Scroll-anchor poll-merge: when the rows array grows or reorders
  // (typically because the 30s poll merged in newer prints), keep the
  // package the trader was looking at under the same on-screen
  // position. Without this, the VirtualScroller renders by pixel offset
  // (`itemSize: ROW_ESTIMATE_PX`) so all rows shift down by N * 40px
  // while scrollTop stays constant — a different row appears under the
  // cursor. Pure adjustment helper lives in ./scroll-anchor.ts.
  const prevDisplayRowsRef = useRef<UsdSwapTapeRow[] | null>(null)
  useLayoutEffect(() => {
    const prev = prevDisplayRowsRef.current
    prevDisplayRowsRef.current = displayRows
    if (!prev || prev === displayRows) return
    const sc = tableWrapperRef.current?.querySelector<HTMLElement>(
      '.p-virtualscroller',
    )
    if (!sc) return
    const next = computeAnchorAdjustedScrollTop({
      oldRows: prev,
      newRows: displayRows,
      oldScrollTop: sc.scrollTop,
      rowHeight: ROW_ESTIMATE_PX,
    })
    if (next !== null) sc.scrollTop = next
  }, [displayRows])
  useEffect(() => {
    const root = tableWrapperRef.current
    if (!root) return
    const scroller = root.querySelector<HTMLElement>('.p-virtualscroller')
    if (!scroller) return
    const NEAR_BOTTOM_PX = Math.max(
      ROW_ESTIMATE_PX * 10,
      Math.round(scroller.clientHeight * 1.5),
    )
    const onScroll = () => {
      if (!hasMore || loadingMore) return
      const remaining =
        scroller.scrollHeight - (scroller.scrollTop + scroller.clientHeight)
      if (remaining <= NEAR_BOTTOM_PX) {
        void requestLoadMore()
      }
    }
    scroller.addEventListener('scroll', onScroll, { passive: true })
    // Prime once after mount in case the user starts already near the tail.
    onScroll()
    return () => {
      scroller.removeEventListener('scroll', onScroll)
    }
  }, [hasMore, loadingMore, requestLoadMore, displayRows.length])

  // Memoize so the row className builder doesn't re-create the Set on
  // every poll tick + every keystroke in a filter input. With 200+ rows
  // the unmemoised version was visibly janky during the 30s tape poll.
  const selectedIds = useMemo(
    () => new Set((selected ?? []).map((row) => row.package_id)),
    [selected],
  )

  const toggleRowExpansion = (row: UsdSwapTapeRow) => {
    // Preferred path: defer to the caller's functional-setState toggle so
    // rapid successive clicks on different rows never drop each other's
    // state. Falls back to the legacy full-replacement `onRowToggle` prop
    // only if the parent did not wire up `onToggleRow`.
    if (onToggleRow) {
      onToggleRow(row.package_id)
      return
    }
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
      'h-9 text-[11px] !text-gray-200 transition-[filter,box-shadow] hover:brightness-110 hover:shadow-[inset_0_0_0_1px_rgba(148,163,184,0.5)]',
      rowClassName(row),
      row.manual_link_id || row.manual_package_id ? 'manual-linked-row' : '',
      selectedIds.has(row.package_id) ? 'selected-share-row' : '',
      // Mirror the Analytics Dock's "Focused trade" treatment on the
      // exact row the dock is currently rendering analytics for. The
      // indigo tint + ring is applied via the focused-trade-row CSS
      // selector in UsdSwapsTradeTape.tsx so it survives PrimeReact's
      // own row hover / selection styling.
      focusedPackageId && row.package_id === focusedPackageId
        ? 'focused-trade-row'
        : '',
    ]
      .join(' ')
      .trim()

  const handleResetAll = useCallback(() => {
    columnFilters.reset()
  }, [columnFilters])

  return (
    <div
      ref={tableWrapperRef}
      className="flex flex-col flex-1 min-h-0 bg-slate-950 text-slate-100"
      data-testid="trade-tape-table"
    >
      <style jsx global>{`
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

      {/* Tape toolbar — mirrors the Analytics Dock's chrome: mono title +
          row-count chip on the left, quick-filter pill snapshot, and
          right-aligned utility buttons (Reset filters, Load more, plus
          the parent-injected actionSlot which carries the Show/Hide
          Analytics toggle). */}
      <div
        className="flex items-center gap-2 border-b border-slate-800 bg-slate-950/80 px-3 py-1.5"
        data-testid="trade-tape-filters"
      >
        <span className="font-mono text-[11px] text-slate-300">
          USD Swaps Tape
          <span className="text-slate-600"> · </span>
          <span className="text-slate-500">v2</span>
        </span>
        <span
          className="rounded bg-slate-800 px-1.5 py-[1px] font-mono text-[10px] text-slate-300"
          title={
            filtersActive
              ? `${rows.length} loaded; ${displayRows.length} match the active filter`
              : `${displayRows.length} rows in tape`
          }
        >
          {filtersActive
            ? `${displayRows.length} matching · ${rows.length} loaded`
            : `${displayRows.length} rows`}
          {hasMore ? ' · more' : ''}
        </span>
        {/* Quick filter context pills — surface that the table is on the
            v2 dataset with a reset/clean toggle handled per-column.
            Visual only; mirrors the Analytics Dock prototype's filter
            pill row so the two surfaces feel unified. */}
        <div className="ml-1 flex items-center gap-1 font-mono text-[10px] text-slate-500">
          {filtersActive ? (
            <span
              className="rounded border border-sky-700/50 bg-sky-900/30 px-1.5 py-[1px] text-sky-200"
              title="Per-column filters active"
            >
              Filtered
            </span>
          ) : (
            <span
              className="rounded border border-slate-800 px-1.5 py-[1px]"
              title="No filters active"
            >
              All rows
            </span>
          )}
          <span className="rounded border border-slate-800 px-1.5 py-[1px]">
            Today
          </span>
        </div>
        {hasMore ? (
          <button
            type="button"
            onClick={() => {
              void requestLoadMore()
            }}
            disabled={!!loadingMore}
            data-testid="trade-tape-load-more"
            className="rounded border border-slate-700 bg-sky-900/30 px-2 py-[3px] font-mono text-[10.5px] text-sky-200 hover:bg-sky-900/60 disabled:cursor-not-allowed disabled:opacity-60"
            title={
              filtersActive
                ? 'Load another page from the server and re-apply your filter'
                : 'Load another page from the server'
            }
          >
            {loadingMore ? (
              <span className="inline-flex items-center gap-1">
                <RefreshCw className="h-3 w-3 animate-spin" />
                Loading
              </span>
            ) : (
              'Load more'
            )}
          </button>
        ) : null}
        <div className="flex-1" />
        <button
          type="button"
          onClick={handleResetAll}
          className="rounded border border-slate-700 px-2 py-[3px] font-mono text-[10.5px] text-slate-300 hover:bg-slate-800"
          title="Clear every per-column filter"
        >
          Reset filters
        </button>
        {actionSlot}
      </div>

      <DataTable
        value={displayRows}
        dataKey="package_id"
        size="small"
        scrollable
        scrollHeight="flex"
        stripedRows={false}
        rowClassName={dataTableRowClassName as any}
        loading={loading && displayRows.length === 0}
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
        filters={columnFilters.filters as DataTableFilterMeta}
        onFilter={(e: DataTableFilterEvent) =>
          columnFilters.setFilters(e.filters as any)
        }
        filterDisplay="menu"
        sortField={effectiveSortField}
        sortOrder={effectiveSortOrder}
        onSort={(e: DataTableSortEvent) => {
          const nextField = (e.sortField as string) || null
          const nextOrder = ((e.sortOrder as 1 | -1 | 0) ?? 0) as 1 | -1 | 0
          columnFilters.setSort(
            nextField,
            nextOrder === 0 ? null : (nextOrder as 1 | -1),
          )
        }}
        className="usd-swaps-tape-table rounded-2xl border border-gray-800 bg-gradient-to-b from-gray-950 to-gray-900 text-gray-200 shadow-inner"
        tableStyle={{ minWidth: '1120px' }}
        resizableColumns
        columnResizeMode="fit"
        rowHover
        lazy
        totalRecords={
          // When filters are active, server pagination cannot help us — the
          // filter is client-side, so the virtual scroller must size to the
          // visible (filtered) row count. Without this, the scroller leaves a
          // huge blank tail under a small filtered result set.
          filtersActive
            ? displayRows.length
            : hasMore
              ? displayRows.length + LAZY_LOAD_PAGE_SIZE
              : displayRows.length
        }
        virtualScrollerOptions={{
          itemSize: ROW_ESTIMATE_PX,
          lazy: true,
          onLazyLoad: handleVirtualLoad as any,
        }}
        pt={
          {
            headerCell: {
              className: 'px-2 py-0.5 text-[12px] !border-0',
            },
            bodyCell: {
              className: 'px-2 py-0.5 text-[11px] !border-0',
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
          activeFilters: columnFilters.filters as DataTableFilterMeta,
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
