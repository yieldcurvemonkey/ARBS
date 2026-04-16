'use client'
// ABOUTME: Main orchestrator for the USD swap tape v2 feature.
import type { JSX } from 'react'
import { useMemo, useState } from 'react'
import 'primereact/resources/themes/lara-dark-indigo/theme.css'
import 'primereact/resources/primereact.min.css'
import 'primeicons/primeicons.css'
import { TradeTapeHeader } from './TradeTapeHeader/TradeTapeHeader'
// NOTE(feedback-round-1): every hardcoded filter (FilterChips search bar,
// AND/OR toggle, lifecycle flag chips) was removed. Filtering now happens
// per-column inside TradeTapeTable, URL-synced via useColumnFilters.
import { TradeTapeTable } from './TradeTapeTable/TradeTapeTable'
import { ManualLinksDialog } from './ManualLinksDialog/ManualLinksDialog'
import {
  useRowExpansion,
  useRowSelection,
  useTradeTapeData,
} from '../hooks'

type ModalName = 'links' | null

function todayIso(): string {
  return new Date().toISOString().slice(0, 10)
}

export default function UsdSwapsTradeTape(): JSX.Element {
  const expansion = useRowExpansion()
  const selection = useRowSelection()

  const [activeModal, setActiveModal] = useState<ModalName>(null)

  const tape = useTradeTapeData({})

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

  const liveStatus: 'live' | 'amber' | 'offline' = tape.pollError
    ? 'amber'
    : tape.initialError
      ? 'offline'
      : 'live'

  return (
    <div className="usd-swaps-tape-shell flex h-full min-h-0 flex-col bg-slate-950 text-slate-100 pb-12">
      {/* NOTE(feedback-round-1): header prop set is being slimmed in the
          next commit (Task 11). Passing noop handlers here keeps the type
          check green between the Task 10 deletions and the Task 11 header
          refactor without widening scope of a single commit. */}
      <TradeTapeHeader
        asOfDate={asOf}
        liveStatus={liveStatus}
        rows={tape.rows}
        flagFilters={{
          lifecycle: new Set(),
          tradeTypes: new Set(),
          venues: new Set(),
          ccps: new Set(),
          sessions: new Set(),
          rateIndex: new Set(),
          tenors: new Set(),
          fomcMeeting: null,
          clean: false,
        }}
        onRefresh={() => tape.refetch()}
        onOpenFlowHistory={() => {}}
        onOpenMethodology={() => {}}
        onToggleLifecycle={() => {}}
        onApplyClean={() => {}}
        onResetClean={() => {}}
        onFilterByLifecycle={() => {}}
      />
      <div className="flex flex-1 min-h-0 overflow-hidden">
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
      <style jsx global>{`
        .usd-swaps-tape-shell {
          --usd-swaps-tape-scale: 0.9;
          zoom: var(--usd-swaps-tape-scale);
        }
        @supports not (zoom: 1) {
          .usd-swaps-tape-shell {
            transform: scale(var(--usd-swaps-tape-scale));
            transform-origin: top left;
            width: calc(100% / var(--usd-swaps-tape-scale));
          }
        }
        @media (max-width: 1024px) {
          .usd-swaps-tape-shell {
            --usd-swaps-tape-scale: 1;
            transform: none;
            width: 100%;
          }
        }
        .usd-swaps-tape-shell .p-column-filter-overlay,
        .usd-swaps-tape-shell .p-column-filter-overlay * {
          font-size: 0.7rem !important;
        }
      `}</style>
      <ManualLinksDialog
        open={activeModal === 'links'}
        onClose={() => setActiveModal(null)}
        selected={selection.selected}
        onSuccess={() => {
          selection.clear()
          tape.refetch()
        }}
      />
    </div>
  )
}
