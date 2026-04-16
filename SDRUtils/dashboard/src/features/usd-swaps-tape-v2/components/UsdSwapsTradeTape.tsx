'use client'
// ABOUTME: Main orchestrator for the USD swap tape v2 feature.
import type { JSX } from 'react'
import { useState } from 'react'
import { PrimeReactProvider } from 'primereact/api'
import 'primereact/resources/themes/lara-dark-indigo/theme.css'
import 'primereact/resources/primereact.min.css'
import 'primeicons/primeicons.css'
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

export default function UsdSwapsTradeTape(): JSX.Element {
  const expansion = useRowExpansion()
  const selection = useRowSelection()

  const [activeModal, setActiveModal] = useState<ModalName>(null)

  const tape = useTradeTapeData({})

  return (
    <PrimeReactProvider>
      <div className="usd-swaps-tape-shell flex h-full min-h-0 flex-col bg-slate-950 text-slate-100 pb-12">
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
          /* Make the funnel-icon button low-key — only really visible when a
             filter is active (the active state class is added by PrimeReact). */
          .usd-swaps-tape-shell .p-column-filter-menu-button {
            width: 1.1rem !important;
            height: 1.1rem !important;
            color: rgba(148, 163, 184, 0.55) !important;
          }
          .usd-swaps-tape-shell .p-column-filter-menu-button:hover {
            color: rgb(125, 211, 252) !important;
            background: rgba(30, 41, 59, 0.6) !important;
          }
          .usd-swaps-tape-shell
            .p-column-filter-menu-button.p-column-filter-menu-button-active {
            color: rgb(125, 211, 252) !important;
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
    </PrimeReactProvider>
  )
}
