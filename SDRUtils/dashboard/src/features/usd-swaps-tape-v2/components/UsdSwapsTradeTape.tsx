'use client'
// ABOUTME: Main orchestrator for the USD swap tape v2 feature.
import type { JSX } from 'react'
import { useCallback, useMemo, useState } from 'react'
import 'primereact/resources/themes/lara-dark-indigo/theme.css'
import 'primereact/resources/primereact.min.css'
import 'primeicons/primeicons.css'
import { TradeTapeHeader } from './TradeTapeHeader/TradeTapeHeader'
import { FilterChips } from './TradeTapeFilters/FilterChips'
// Global fuzzy search, column-filter AND/OR toggle, sort, and Reset now live
// inside TradeTapeTable itself (mirroring SwaptionTradeTape.tsx.bak) and are
// URL-synced via the useColumnFilters / useTableControls hooks — the page
// header only owns flag filters + clean-tape toggles.
import { TradeTapeTable } from './TradeTapeTable/TradeTapeTable'
import { TimeseriesChart } from './TradeTapeCharts/TimeseriesChart'
import { FlowHistoryGrid } from './TradeTapeCharts/FlowHistoryGrid'
import { ManualLinksDialog } from './ManualLinksDialog/ManualLinksDialog'
import { UsdSwapsMethodologyModal } from './UsdSwapsMethodologyModal'
import {
  useColumnFilters,
  useFlagFilters,
  useRowExpansion,
  useRowSelection,
  useTradeTapeData,
} from '../hooks'
import type { LifecycleType } from '../types'

type ModalName = 'timeseries' | 'flow-history' | 'links' | 'methodology' | null

function todayIso(): string {
  return new Date().toISOString().slice(0, 10)
}

export default function UsdSwapsTradeTape(): JSX.Element {
  const flagFilters = useFlagFilters()
  // Still read column-filter state at this level so the server query rehydrates
  // when the user pastes a URL that already contains ?columnFilters=… — the
  // DataTable's own copy of this state lives inside TradeTapeTable.
  const columnFilters = useColumnFilters()
  const expansion = useRowExpansion()
  const selection = useRowSelection()

  const [activeModal, setActiveModal] = useState<ModalName>(null)

  const tape = useTradeTapeData({
    // Fuzzy search is handled client-side in TradeTapeTable — do NOT forward
    // it to the server. The server still receives column filters and the
    // URL-synced filter payload so power-user SQL-style filters keep working.
    columnFilterPayloadKey:
      Object.keys(columnFilters.filters).length > 0
        ? JSON.stringify(columnFilters.filters)
        : undefined,
    columnFilterOperator: columnFilters.operator,
    flagFilters: flagFilters.state,
  })

  // Pick the as-of date from the latest row we actually have data for so
  // related drill-down views stay anchored to the same trading day. Falls
  // back to today when the tape is empty (first load / no data yet).
  const asOf = useMemo(() => {
    const latest = tape.rows[0]?.as_of_date
    if (typeof latest === 'string' && latest.length >= 10) {
      return latest.slice(0, 10)
    }
    return todayIso()
  }, [tape.rows])

  const fields = useMemo(
    () => [
      {
        key: 'venues' as const,
        label: 'Venue',
        values: ['D2D', 'D2C'],
        selected: flagFilters.state.venues,
        onToggle: flagFilters.toggleVenue,
      },
      {
        key: 'ccps' as const,
        label: 'CCP',
        values: ['LCH', 'CME'],
        selected: flagFilters.state.ccps,
        onToggle: flagFilters.toggleCcp,
      },
      {
        key: 'rateIndex' as const,
        label: 'Index',
        values: ['SOFR', 'FED_FUNDS', 'OTHER'],
        selected: flagFilters.state.rateIndex,
        onToggle: flagFilters.toggleRateIndex,
      },
      {
        key: 'sessions' as const,
        label: 'Session',
        values: ['Asia', 'London', 'NY_AM', 'NY_PM', 'Late'],
        selected: flagFilters.state.sessions,
        onToggle: flagFilters.toggleSession,
      },
    ],
    [flagFilters],
  )

  const handleFilterByLifecycle = useCallback(
    (type: LifecycleType) => {
      flagFilters.toggleLifecycle(type)
    },
    [flagFilters],
  )

  const liveStatus: 'live' | 'amber' | 'offline' = tape.pollError
    ? 'amber'
    : tape.initialError
      ? 'offline'
      : 'live'

  return (
    <div className="flex flex-col h-full min-h-0 bg-slate-950 text-slate-100 pb-2">
      <TradeTapeHeader
        asOfDate={asOf}
        liveStatus={liveStatus}
        rows={tape.rows}
        flagFilters={flagFilters.state}
        onRefresh={() => tape.refetch()}
        onOpenFlowHistory={() => setActiveModal('flow-history')}
        onOpenMethodology={() => setActiveModal('methodology')}
        onToggleLifecycle={flagFilters.toggleLifecycle}
        onApplyClean={flagFilters.applyCleanPreset}
        onResetClean={flagFilters.resetAll}
        onFilterByLifecycle={handleFilterByLifecycle}
      />
      <FilterChips fields={fields} />
      <div className="flex flex-1 overflow-hidden">
        <TradeTapeTable
          rows={tape.rows}
          loading={tape.loading}
          loadingMore={tape.loadingMore}
          onLoadMore={tape.loadMore}
          hasMore={tape.hasMore}
          expandedRows={expansion.expandedRows}
          onRowToggle={expansion.onRowToggle}
          selected={selection.selected}
          onSelectionChange={selection.onSelectionChange}
          onOpenTimeseries={() => setActiveModal('timeseries')}
          actionSlot={
            selection.count > 0 ? (
              <button
                type="button"
                className="whitespace-nowrap text-[11px] text-sky-200 hover:text-sky-100"
                onClick={() => setActiveModal('links')}
              >
                Link {selection.count} selected
              </button>
            ) : null
          }
        />
      </div>
      <TimeseriesChart
        open={activeModal === 'timeseries'}
        onClose={() => setActiveModal(null)}
      />
      <FlowHistoryGrid
        open={activeModal === 'flow-history'}
        onClose={() => setActiveModal(null)}
        start={asOf}
        end={asOf}
      />
      <ManualLinksDialog
        open={activeModal === 'links'}
        onClose={() => setActiveModal(null)}
        selected={selection.selected}
        onSuccess={() => {
          selection.clear()
          tape.refetch()
        }}
      />
      <UsdSwapsMethodologyModal
        open={activeModal === 'methodology'}
        onClose={() => setActiveModal(null)}
      />
    </div>
  )
}
