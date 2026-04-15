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
  const expansion = useRowExpansion()
  const selection = useRowSelection()

  const [activeModal, setActiveModal] = useState<ModalName>(null)

  // `flagFilters.state` is reconstructed from URL params on each render; key
  // the fetch params off the serialized query string instead so the tape hook
  // only refetches when the URL-backed filter state actually changes.
  const tapeQueryParams = useMemo(
    () => ({
      flagFilters: flagFilters.state,
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [flagFilters.queryString],
  )

  const tape = useTradeTapeData(tapeQueryParams)

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
    <div className="usd-swaps-tape-shell flex h-full min-h-0 flex-col bg-slate-950 text-slate-100 pb-12">
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
