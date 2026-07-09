'use client'
// ABOUTME: Main orchestrator for the USD swap tape v2 feature.
import type { JSX } from 'react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { usePathname, useRouter, useSearchParams } from 'next/navigation'
import { HelpCircle } from 'lucide-react'
import { FilterMatchMode, PrimeReactProvider } from 'primereact/api'
import 'primereact/resources/themes/lara-dark-indigo/theme.css'
import 'primereact/resources/primereact.min.css'
import 'primeicons/primeicons.css'
// NOTE(feedback-round-1): every hardcoded filter (FilterChips search bar,
// AND/OR toggle, lifecycle flag chips) was removed. Filtering now happens
// per-column inside TradeTapeTable, URL-synced via useColumnFilters.
import { TradeTapeTable } from './TradeTapeTable/TradeTapeTable'
import { RegroupActionBar } from './RegroupActionBar/RegroupActionBar'
import { OverrideCommitPopover } from './OverrideCommitPopover/OverrideCommitPopover'
import { NotePopover } from './NotePopover/NotePopover'
import { OverridesPanel } from './OverridesPanel/OverridesPanel'
import { AnalyticsPanel } from './AnalyticsPanel'
import { VolumeGridCard } from './VolumeGrid/VolumeGridCard'
import {
  hasSeenUsdSwapsOnboarding,
  markUsdSwapsOnboardingSeen,
  UsdSwapsOnboardingGuide,
} from './UsdSwapsOnboardingGuide'
import { useIsMobile } from '@/lib/hooks/useIsMobile'
import { ManualLinkDetailModal } from '@/lib/manual-links-ui/components/ManualLinkDetailModal'
import { TAPE_V2_API_BASE } from '../constants'
import { useSavedUser } from '../hooks/useSavedUser'
import { applyOverrides } from '../utils/applyOverrides'
import { createOverride, deactivateOverride } from '../api/overrideApi'
import type { NoteTarget } from '../types/note.types'
import type { OverrideType } from '../types/override.types'

const V2_LINKS_BASE = `${TAPE_V2_API_BASE}/links`

const PACKAGE_TYPE_OPTIONS = [
  { value: 'MANUAL', label: 'Manual' },
  { value: 'USER_STRADDLE_PAIR', label: 'Straddle Pair' },
  { value: 'USER_VERTICAL_SPREAD', label: 'Vertical Spread' },
  { value: 'USER_TIME_SPREAD', label: 'Time Spread' },
  { value: 'USER_CUSTOM', label: 'Custom' },
]

const LINK_REASON_OPTIONS = [
  { value: '', label: 'Select reason...' },
  { value: 'Vega hedge', label: 'Vega hedge' },
  { value: 'Customer flow', label: 'Customer flow' },
  { value: 'Time spread', label: 'Time spread' },
  { value: 'Skew Trade', label: 'Skew Trade' },
  { value: 'Structure repair', label: 'Structure repair' },
  { value: 'Other', label: 'Other' },
]
import {
  useColumnFilters,
  useFocusedTrade,
  useRowExpansion,
  useSelectionContext,
  useTradeSelection,
  useTradeTapeData,
} from '../hooks'
import { COLUMN_FILTER_QUERY_KEY } from '../hooks/useColumnFilters'
import { normalizeFocusedTrade } from '../hooks/useFocusedTrade'

export default function UsdSwapsTradeTape(): JSX.Element {
  const expansion = useRowExpansion()
  // Leg-level tape selection replaces the legacy package-row selection. It
  // feeds the RegroupActionBar enablement + the structural-override commit.
  const tradeSelection = useTradeSelection()

  const [analyticsOpen, setAnalyticsOpen] = useState<boolean>(false)
  const [onboardingOpen, setOnboardingOpen] = useState(false)
  // Detail-modal state. Opened when the trader clicks a row's manual-link
  // badge; closed via the modal's close button. The admin password and
  // user inputs live here so they survive the modal open/close cycle.
  const [detailLinkId, setDetailLinkId] = useState<string | null>(null)
  const [adminPassword, setAdminPassword] = useState('')
  const [savedUser, setSavedUser] = useSavedUser()
  const focus = useFocusedTrade()
  const isMobile = useIsMobile()

  // Structural-override + note orchestration state.
  // `overridePassword` persists across popovers (like `adminPassword`).
  const [overridePassword, setOverridePassword] = useState('')
  // The Group/Split/Detach action that opened the commit popover.
  const [commitAction, setCommitAction] = useState<
    null | { type: OverrideType; tradeIds: string[]; manualPackageId?: string | null }
  >(null)
  const [noteTarget, setNoteTarget] = useState<NoteTarget | null>(null)
  const [overridesPanelOpen, setOverridesPanelOpen] = useState(false)
  // Undo affordance: the contract has no reactivate endpoint, so undo-of-revert
  // re-POSTs an equivalent override and undo-of-create deactivates the just-
  // created override.
  const [lastAction, setLastAction] = useState<
    | null
    | {
        kind: 'created' | 'deactivated'
        overrideId: string
        recreate?: Parameters<typeof createOverride>[0]
      }
  >(null)

  // Volume-grid modal click-through: writes a package_id URL filter so
  // the tape narrows to the clicked package. Mirrors the AnalyticsPanel
  // onBinBrush pattern.
  const router = useRouter()
  const pathname = usePathname()
  const searchParams = useSearchParams()
  const onSelectPackageFromGrid = useCallback((packageId: string) => {
    const next = new URLSearchParams(searchParams?.toString() ?? '')
    next.set(
      COLUMN_FILTER_QUERY_KEY,
      JSON.stringify({
        package_id: { value: packageId, matchMode: FilterMatchMode.EQUALS },
      }),
    )
    router.replace(`${pathname}?${next.toString()}`, { scroll: false })
  }, [pathname, router, searchParams])

  const handleOpenManualLink = useCallback((linkId: string) => {
    setDetailLinkId(linkId)
  }, [])
  const handleCloseManualLink = useCallback(() => {
    setDetailLinkId(null)
  }, [])
  const openOnboarding = useCallback(() => {
    setOnboardingOpen(true)
  }, [])
  const closeOnboarding = useCallback(() => {
    if (typeof window !== 'undefined') {
      try {
        markUsdSwapsOnboardingSeen(window.localStorage)
      } catch {
        setOnboardingOpen(false)
        return
      }
    }
    setOnboardingOpen(false)
  }, [])

  useEffect(() => {
    if (typeof window === 'undefined') return
    try {
      if (hasSeenUsdSwapsOnboarding(window.localStorage)) return
      setOnboardingOpen(true)
    } catch {
      setOnboardingOpen(false)
    }
  }, [])

  // Per-column filters live in the URL via useColumnFilters; thread the
  // serialised payload into the data hook so the route applies the
  // filter via WHERE clauses. When no filter is active the value is
  // null and the unfiltered initial fetch keeps its Cache-Control hit.
  const orchestratorColumnFilters = useColumnFilters()
  const tape = useTradeTapeData({
    columnFilters: orchestratorColumnFilters.serializedColumnFilters,
  })

  // Resolve view-time structural overrides into render rows: SPLIT explodes
  // into per-leg rows, DETACH pulls legs out leaving a remnant, GROUP clusters
  // contiguously. MEMOIZE on `tape.rows` identity — applyOverrides output is
  // NOT reference-stable, so never key downstream memos on its result.
  const displayRows = useMemo(() => applyOverrides(tape.rows), [tape.rows])
  // Contextual-action enablement matrix off the current leg selection + the
  // ORIGINAL (pre-override) rows so package membership resolves correctly.
  const selCtx = useSelectionContext(tape.rows, tradeSelection.selectedTradeIds)

  // When the user checks a leg, make the first-selected row the focus so
  // the analytics dock tracks their attention without a separate click.
  // Auto-opens the dock on first selection so analytics surface as soon
  // as there's something real to render.
  const firstSelectedRow = useMemo(() => {
    const first = tradeSelection.selectedTradeIds.values().next().value
    if (!first) return null
    return (
      tape.rows.find((r) =>
        (r.legs_json ?? []).some((l) => l.trade_id === first),
      ) ?? null
    )
  }, [tradeSelection.selectedTradeIds, tape.rows])
  const selectedRows = useMemo(
    () =>
      tape.rows.filter((r) =>
        (r.legs_json ?? []).some(
          (l) => l.trade_id && tradeSelection.selectedTradeIds.has(l.trade_id),
        ),
      ),
    [tape.rows, tradeSelection.selectedTradeIds],
  )
  // FocusedTrade carries the package_id under `id` (set by
  // useFocusedTrade.normalizeFocusedTrade). Reading `.package_id` here
  // silently produced `undefined`, which meant the indigo focused-row
  // highlight in the tape was never applied — the dock + tape diverged
  // on which row the trader was inspecting.
  const focusedPackageId = focus.focused?.id ?? null
  const derivedFocused = useMemo(
    () => normalizeFocusedTrade(firstSelectedRow),
    [firstSelectedRow],
  )
  // Do NOT depend on the whole `focus` object here — useFocusedTrade
  // returns a fresh object every render, which previously fired this
  // effect on every render and loop-triggered re-fetches. Pull the
  // stable callback out of the hook and depend on it directly.
  const setFocusedRaw = focus.setFocusedRaw
  useEffect(() => {
    if (derivedFocused) {
      setFocusedRaw(derivedFocused)
      setAnalyticsOpen(true)
    }
  }, [derivedFocused, setFocusedRaw])

  // Action-bar dispatch. NOTE opens the note popover on the first selected
  // trade; GROUP/SPLIT/DETACH open the commit popover with the selected trade
  // ids (and, for SPLIT/DETACH, the informational source manual_package_id).
  const handleRegroupAction = useCallback(
    (action: 'GROUP' | 'SPLIT' | 'DETACH' | 'NOTE') => {
      const tradeIds = Array.from(tradeSelection.selectedTradeIds)
      if (action === 'NOTE') {
        if (tradeIds[0]) {
          setNoteTarget({ target_type: 'TRADE', target_id: tradeIds[0] })
        }
        return
      }
      const srcPkgId =
        action === 'SPLIT'
          ? selCtx.splitPackageId
          : action === 'DETACH'
            ? selCtx.detachPackageId
            : undefined
      const srcRow = srcPkgId
        ? tape.rows.find((r) => r.package_id === srcPkgId)
        : undefined
      setCommitAction({
        type: action,
        tradeIds,
        manualPackageId: srcRow?.manual_package_id ?? null,
      })
    },
    [tradeSelection.selectedTradeIds, selCtx, tape.rows],
  )

  const handleUndo = useCallback(async () => {
    if (!lastAction) return
    try {
      if (lastAction.kind === 'created') {
        await deactivateOverride(lastAction.overrideId, {
          user: savedUser,
          admin_password: overridePassword,
        })
      } else if (lastAction.recreate) {
        await createOverride(lastAction.recreate)
      }
      setLastAction(null)
      tape.refetch()
    } catch {
      /* keep the affordance; the error surfaces on the next explicit action */
    }
  }, [lastAction, savedUser, overridePassword, tape])

  // Commit popover is an absolute dropdown; render it once inside whichever
  // (mutually-exclusive) toolbar is active so it anchors under the action bar.
  const commitPopoverNode = commitAction ? (
    <OverrideCommitPopover
      overrideType={commitAction.type}
      tradeIds={commitAction.tradeIds}
      manualPackageId={commitAction.manualPackageId}
      user={savedUser}
      onUserChange={setSavedUser}
      password={overridePassword}
      onPasswordChange={setOverridePassword}
      onCancel={() => setCommitAction(null)}
      onSuccess={(result) => {
        setLastAction({ kind: 'created', overrideId: result.override_id })
        setCommitAction(null)
        tradeSelection.clear()
        tape.refetch()
      }}
    />
  ) : null

  return (
    <PrimeReactProvider>
      <div
        className={`usd-swaps-tape-shell flex h-full min-h-0 flex-col bg-slate-950 text-slate-100 ${isMobile ? 'pb-20' : 'pb-12'}`}
        data-mobile={isMobile || undefined}
      >
        <VolumeGridCard onSelectPackage={onSelectPackageFromGrid} />
        <div className="flex flex-1 min-h-0 overflow-hidden">
          <TradeTapeTable
            rows={displayRows}
            columnFilters={orchestratorColumnFilters}
            loading={tape.loading}
            refreshing={tape.refreshing}
            loadingMore={tape.loadingMore}
            onLoadMore={tape.loadMore}
            hasMore={tape.hasMore}
            expandedRows={expansion.expandedRows}
            onRowToggle={expansion.onRowToggle}
            onToggleRow={expansion.toggleOne}
            selectedTradeIds={tradeSelection.selectedTradeIds}
            selectedByPackage={tradeSelection.selectedByPackage}
            onTogglePackage={tradeSelection.togglePackage}
            onToggleTrade={tradeSelection.toggleTrade}
            onOpenNote={setNoteTarget}
            onOpenOverride={() => setOverridesPanelOpen(true)}
            focusedPackageId={focusedPackageId}
            onOpenManualLink={handleOpenManualLink}
            actionSlot={isMobile ? undefined : (
              <div className="relative flex items-center gap-2">
                {tradeSelection.count > 0 ? (
                  <RegroupActionBar
                    selectedTradeIds={tradeSelection.selectedTradeIds}
                    context={selCtx}
                    onAction={handleRegroupAction}
                    onClear={tradeSelection.clear}
                  />
                ) : null}
                {lastAction ? (
                  <button
                    type="button"
                    onClick={handleUndo}
                    className="whitespace-nowrap rounded border border-amber-700/50 bg-amber-900/30 px-2 py-1 text-[11px] text-amber-200 hover:bg-amber-900/50"
                  >
                    Undo {lastAction.kind === 'created' ? 'group/split/detach' : 'revert'}
                  </button>
                ) : null}
                <button
                  type="button"
                  onClick={() => setOverridesPanelOpen(true)}
                  className="inline-flex items-center rounded border border-slate-700 px-2.5 py-1 font-mono text-[10.5px] text-slate-200 hover:bg-slate-800"
                >
                  Overrides
                </button>
                {commitPopoverNode}
                <button
                  type="button"
                  onClick={openOnboarding}
                  title="Open the how-to guide"
                  aria-label="Open the how-to guide"
                  className="inline-flex items-center gap-1 rounded border border-slate-700 px-2.5 py-1 font-mono text-[10.5px] text-slate-200 ring-1 ring-transparent hover:bg-slate-800"
                >
                  <HelpCircle className="h-3.5 w-3.5" aria-hidden="true" />
                  <span>How to use</span>
                </button>
                <button
                  type="button"
                  onClick={() => setAnalyticsOpen((v) => !v)}
                  title="Open the per-trade analytics dock"
                  className={`rounded px-2.5 py-1 font-mono text-[10.5px] ring-1 transition-colors ${
                    analyticsOpen
                      ? 'bg-indigo-500/20 text-indigo-100 ring-indigo-400/40'
                      : 'border border-slate-700 text-slate-200 ring-transparent hover:bg-slate-800'
                  }`}
                >
                  {analyticsOpen ? '▼ Hide Analytics' : '▲ Show Analytics'}
                </button>
              </div>
            )}
          />
        </div>
        {analyticsOpen ? (
          <div className="fixed inset-x-0 bottom-0 z-40 shadow-2xl shadow-black/50">
            <AnalyticsPanel
              rows={tape.rows}
              selected={selectedRows}
              focused={focus.focused}
              onClose={() => setAnalyticsOpen(false)}
              onClearFocused={() => {
                focus.clear()
                tradeSelection.clear()
              }}
            />
          </div>
        ) : null}
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
          .usd-swaps-tape-filter-menu,
          .usd-swaps-tape-filter-menu * {
            font-size: 0.7rem !important;
          }
          .usd-swaps-tape-filter-menu {
            width: 10rem !important;
            min-width: 10rem !important;
            border-radius: 0.5rem !important;
          }
          .usd-swaps-tape-filter-menu
            .p-column-filter-row-items {
            padding: 0.25rem 0 !important;
          }
          .usd-swaps-tape-filter-menu
            .p-column-filter-row-items
            .p-column-filter-row-item {
            padding: 0.35rem 0.55rem !important;
          }
          .usd-swaps-tape-filter-menu
            .p-column-filter-operator {
            padding: 0.45rem 0.65rem !important;
          }
          .usd-swaps-tape-filter-menu
            .p-column-filter-constraint {
            padding: 0.5rem !important;
          }
          .usd-swaps-tape-filter-menu
            .p-column-filter-constraint
            .p-column-filter-matchmode-dropdown {
            margin-bottom: 0.25rem !important;
          }
          .usd-swaps-tape-filter-menu
            .p-column-filter-constraint
            .p-column-filter-remove-button {
            margin-top: 0.25rem !important;
          }
          .usd-swaps-tape-filter-menu
            .p-column-filter-add-rule {
            padding: 0.45rem 0.65rem !important;
          }
          .usd-swaps-tape-filter-menu
            .p-column-filter-buttonbar {
            gap: 0.35rem !important;
            padding: 0.5rem !important;
          }
          .usd-swaps-tape-filter-menu .p-inputtext,
          .usd-swaps-tape-filter-menu .p-dropdown,
          .usd-swaps-tape-filter-menu .p-button {
            border-radius: 0.4rem !important;
            font-size: 0.7rem !important;
          }
          .usd-swaps-tape-filter-menu .p-inputtext,
          .usd-swaps-tape-filter-menu .p-dropdown-label {
            padding: 0.35rem 0.45rem !important;
          }
          .usd-swaps-tape-filter-menu .p-dropdown,
          .usd-swaps-tape-filter-menu .p-button {
            min-height: 1.7rem !important;
          }
          .usd-swaps-tape-filter-menu .p-dropdown-trigger {
            width: 1.5rem !important;
          }
          .usd-swaps-tape-filter-menu .p-button {
            min-width: 3.1rem !important;
            padding: 0.3rem 0.5rem !important;
          }
          /* Make the funnel-icon button low-key — only really visible when a
             filter is active (the active state class is added by PrimeReact).

             Hit-area sizing: the icon itself stays small (font-size keeps the
             glyph at ~0.7rem) but the button is a 1.6rem x 1.6rem square with
             extra padding, so clicking "near" the funnel no longer lands on
             the sortable header label and flips the sort by accident. */
          .usd-swaps-tape-shell .p-column-filter-menu-button {
            min-width: 1.6rem !important;
            min-height: 1.6rem !important;
            width: 1.6rem !important;
            height: 1.6rem !important;
            padding: 0.35rem !important;
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
          /* ---------------------------------------------------------------
           * Analytics Dock visual language alignment
           *
           * The Analytics Dock prototype uses a specific dense, mono-typed
           * tape: slate-900/60 header bar, slate-500 9.5px uppercase
           * tracking-wider column titles, mono 11px body cells, ~30px row
           * height with 5px vertical padding, and a tinted indigo
           * treatment on the focused row. Apply those rules here so the
           * table reads consistently with the dock that lives below it.
           * --------------------------------------------------------------- */
          .usd-swaps-tape-shell
            .usd-swaps-tape-table
            .p-datatable-thead
            > tr
            > th {
            background-color: rgba(15, 23, 42, 0.6) !important;
            border-bottom: 1px solid rgb(30, 41, 59) !important;
            padding: 0.25rem 0.5rem !important;
          }
          .usd-swaps-tape-shell
            .usd-swaps-tape-table
            .p-datatable-thead
            > tr
            > th
            .p-column-header-content {
            font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
          }
          /* The renderHeader helper produces its own label markup; the
             rule above only sets the header cell chrome. */
          .usd-swaps-tape-shell
            .usd-swaps-tape-table
            .p-datatable-tbody
            > tr {
            font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
          }
          .usd-swaps-tape-shell
            .usd-swaps-tape-table
            .p-datatable-tbody
            > tr
            > td {
            padding: 5px 0.5rem !important;
            font-size: 11px !important;
          }
          .usd-swaps-tape-shell
            .usd-swaps-tape-table
            .p-datatable-tbody
            > tr.focused-trade-row > td {
            background-color: rgba(99, 102, 241, 0.15) !important;
            box-shadow:
              inset 0 1px 0 rgba(129, 140, 248, 0.5),
              inset 0 -1px 0 rgba(129, 140, 248, 0.5) !important;
          }
          .usd-swaps-tape-shell
            .usd-swaps-tape-table
            .p-datatable-tbody
            > tr.focused-trade-row > td:first-child {
            box-shadow:
              inset 1px 0 0 rgba(129, 140, 248, 0.5),
              inset 0 1px 0 rgba(129, 140, 248, 0.5),
              inset 0 -1px 0 rgba(129, 140, 248, 0.5) !important;
          }
          .usd-swaps-tape-shell
            .usd-swaps-tape-table
            .p-datatable-tbody
            > tr.focused-trade-row > td:last-child {
            box-shadow:
              inset -1px 0 0 rgba(129, 140, 248, 0.5),
              inset 0 1px 0 rgba(129, 140, 248, 0.5),
              inset 0 -1px 0 rgba(129, 140, 248, 0.5) !important;
          }
          /* Mobile device overrides — activated by data-mobile attr
             set via useIsMobile() (UA + viewport < 1024px). */
          .usd-swaps-tape-shell[data-mobile] {
            --usd-swaps-tape-scale: 1;
            zoom: 1;
            transform: none;
            width: 100%;
          }
          .usd-swaps-tape-shell[data-mobile] [data-testid="volume-grid-card"] button,
          .usd-swaps-tape-shell[data-mobile] [data-testid="volume-grid-card"] select {
            min-height: 2.75rem;
            min-width: 2.75rem;
          }
        `}</style>
        <NotePopover
          target={noteTarget}
          author={savedUser}
          onAuthorChange={setSavedUser}
          onClose={() => setNoteTarget(null)}
          onSaved={() => tape.refetch()}
        />
        {overridesPanelOpen ? (
          <OverridesPanel
            user={savedUser}
            adminPassword={overridePassword}
            onClose={() => setOverridesPanelOpen(false)}
            onReverted={(overrideId, recreate) => {
              setLastAction({ kind: 'deactivated', overrideId, recreate })
              tape.refetch()
            }}
          />
        ) : null}
        <ManualLinkDetailModal
          isOpen={detailLinkId !== null}
          linkId={detailLinkId}
          onClose={handleCloseManualLink}
          onUpdated={() => {
            tape.refetch()
          }}
          onDeactivated={() => {
            tape.refetch()
          }}
          apiBasePath={V2_LINKS_BASE}
          currentUser={savedUser}
          onUserChange={setSavedUser}
          adminPassword={adminPassword}
          onAdminPasswordChange={setAdminPassword}
          packageTypeOptions={PACKAGE_TYPE_OPTIONS}
          linkReasonOptions={LINK_REASON_OPTIONS}
        />
        <UsdSwapsOnboardingGuide
          open={onboardingOpen}
          onClose={closeOnboarding}
        />
        {isMobile && (
          <div className="fixed inset-x-0 bottom-0 z-50 flex items-center justify-around gap-2 border-t border-slate-700 bg-slate-900/95 px-3 py-2 backdrop-blur-sm">
            {tradeSelection.count > 0 && (
              <div className="relative flex flex-1 items-center">
                <RegroupActionBar
                  selectedTradeIds={tradeSelection.selectedTradeIds}
                  context={selCtx}
                  onAction={handleRegroupAction}
                  onClear={tradeSelection.clear}
                />
                {commitPopoverNode}
              </div>
            )}
            <button
              type="button"
              onClick={openOnboarding}
              className="min-h-[44px] rounded-lg border border-slate-700 px-4 py-2 font-mono text-xs text-slate-200 active:bg-slate-700"
            >
              Help
            </button>
            <button
              type="button"
              onClick={() => setAnalyticsOpen((v) => !v)}
              className={`min-h-[44px] flex-1 rounded-lg px-3 py-2 font-mono text-xs ${
                analyticsOpen
                  ? 'bg-indigo-500/20 text-indigo-100 ring-1 ring-indigo-400/40'
                  : 'border border-slate-700 text-slate-200 active:bg-slate-700'
              }`}
            >
              {analyticsOpen ? 'Hide Analytics' : 'Analytics'}
            </button>
          </div>
        )}
      </div>
    </PrimeReactProvider>
  )
}
