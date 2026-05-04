'use client'
// AnalyticsPanel — collapsible, resizable dock that mounts below the
// tape table and hosts the Timeseries / Trade Rarity / Traded Levels tabs
// for a focused trade.
import type { JSX } from 'react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { FilterMatchMode, FilterOperator } from 'primereact/api'
import { usePathname, useRouter, useSearchParams } from 'next/navigation'
import {
  deriveAnalyticsSelection,
  useAnalyticsSequence,
  useAnalyticsTimeseries,
  useExtremesData,
  useRarityData,
} from '../../hooks'
import { COLUMN_FILTER_QUERY_KEY } from '../../hooks/useColumnFilters'
import { CardsDrawer } from './CardsDrawer'
import { FocusedTradeBar } from './FocusedTradeBar'
import { SequenceBar } from './SequenceBar'
import { computeSequenceAggregate } from './sequence-aggregate'
import { TimeseriesTab } from './TimeseriesTab'
import { TradeRarityTab } from './TradeRarityTab'
import { TradedLevelsTab } from './TradedLevelsTab'
import { Tabs } from './controls'
import {
  DOCK_DEFAULT_VH,
  DOCK_MAX_RESERVE_PX,
  DOCK_MIN_PX,
  LEVELS_DEFAULT_STATE,
  RARITY_DEFAULT_STATE,
  RARITY_PREFS_STORAGE_KEY,
  TIMESERIES_DEFAULT_STATE,
} from './constants'
import { parsePositiveNumberInput } from './TradedLevelsTab.helpers'
import type {
  AnalyticsTab,
  FocusedTrade,
  LevelsState,
  RarityState,
  TimeseriesState,
} from './analytics-types'
import type { UsdSwapTapeRow } from '../../types'

export interface AnalyticsPanelProps {
  // Phase A (multi-trade dock): the panel now receives the full loaded
  // row set + the current multi-row selection alongside the legacy
  // single-trade `focused` prop. `rows` powers the always-on cards
  // drawer (PR-#286 underlier-mix / RFR adoption / swap-spread VWAP /
  // CCP-switch). `selected` powers sequence-mode rendering (N≥2). The
  // body still renders single-mode UX from `focused` byte-for-byte;
  // sequence-mode branches land in Phase D.
  rows: readonly UsdSwapTapeRow[]
  selected: readonly UsdSwapTapeRow[]
  focused: FocusedTrade | null
  onClose: () => void
  onClearFocused: () => void
  chartHeight?: number
  histogramHeight?: number
  panelHeightVh?: number
}

export function AnalyticsPanel(props: AnalyticsPanelProps): JSX.Element {
  const {
    rows,
    selected,
    focused, onClose, onClearFocused,
    chartHeight = 340, histogramHeight = 280,
    panelHeightVh = DOCK_DEFAULT_VH,
  } = props

  // Phase D — mode-branch render. We derive {mode, sequence} off the
  // `selected` prop so the panel stays in sync with the trader's
  // multi-row selection without stamping a new state field. The
  // legacy `focused` prop continues to drive the single-trade tab
  // hooks below; sequence mode wires its own per-trade hooks via
  // the useAnalyticsSequence wrapper (Phase E).
  const derived = deriveAnalyticsSelection(selected)
  const mode = derived.mode
  const sequence = derived.sequence

  // Phase E — wrapper hook fans out to the per-trade analytics
  // hooks for each member of the sequence (no-op when sequence is
  // null) and aggregates the sequence-level summary. The aggregate
  // is also computed eagerly in Phase D's branch below for consumers
  // that don't need the per-trade timeseries / rarity / extremes;
  // when both are computed, prefer the wrapper's aggregate so the
  // SequenceBar's warning chip stays consistent with the cap.
  const seqAnalytics = useAnalyticsSequence(sequence, {})

  const [activeTab, setActiveTab] = useState<AnalyticsTab>('timeseries')
  const [tsState, setTsState] = useState<TimeseriesState>(TIMESERIES_DEFAULT_STATE)
  const [levelsState, setLevelsState] = useState<LevelsState>(LEVELS_DEFAULT_STATE)
  // Rarity prefs persist to localStorage so the trader doesn't have to
  // reconfigure the basis / similarity thresholds on every dock open.
  // Initial mount reads server-side default; useEffect below restores
  // any saved prefs after hydration so SSR + CSR markup matches.
  const [rarityState, setRarityState] = useState<RarityState>(RARITY_DEFAULT_STATE)
  useEffect(() => {
    if (typeof window === 'undefined') return
    try {
      const raw = window.localStorage.getItem(RARITY_PREFS_STORAGE_KEY)
      if (!raw) return
      const parsed = JSON.parse(raw) as Partial<RarityState>
      setRarityState((s) => ({
        ...s,
        basis: parsed.basis ?? s.basis,
        histogramMetric: parsed.histogramMetric ?? s.histogramMetric,
        primaryTol: typeof parsed.primaryTol === 'number' ? parsed.primaryTol : s.primaryTol,
        sizeTol: typeof parsed.sizeTol === 'number' ? parsed.sizeTol : s.sizeTol,
      }))
    } catch {
      /* ignore corrupt storage payloads */
    }
  }, [])
  useEffect(() => {
    if (typeof window === 'undefined') return
    const persisted = {
      basis: rarityState.basis,
      histogramMetric: rarityState.histogramMetric,
      primaryTol: rarityState.primaryTol,
      sizeTol: rarityState.sizeTol,
    }
    try {
      window.localStorage.setItem(
        RARITY_PREFS_STORAGE_KEY,
        JSON.stringify(persisted),
      )
    } catch {
      /* quota or private mode — fall back to in-memory */
    }
  }, [
    rarityState.basis,
    rarityState.histogramMetric,
    rarityState.primaryTol,
    rarityState.sizeTol,
  ])

  // Resizable panel height — ns-resize handle drags the top edge up/down.
  // Start null on both server + client to avoid a SSR/CSR mismatch when
  // window.innerHeight isn't known; useEffect fills in the viewport-relative
  // pixel value after mount.
  const [panelHeight, setPanelHeight] = useState<number | null>(null)
  useEffect(() => {
    setPanelHeight(Math.round((panelHeightVh / 100) * window.innerHeight))
  }, [panelHeightVh])

  const onStartResize = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault()
      const startY = e.clientY
      const startH = panelHeight ?? Math.round((panelHeightVh / 100) * window.innerHeight)
      function onMove(ev: MouseEvent) {
        const dy = startY - ev.clientY
        const next = Math.max(
          DOCK_MIN_PX,
          Math.min(window.innerHeight - DOCK_MAX_RESERVE_PX, startH + dy),
        )
        setPanelHeight(next)
      }
      function onUp() {
        window.removeEventListener('mousemove', onMove)
        window.removeEventListener('mouseup', onUp)
      }
      window.addEventListener('mousemove', onMove)
      window.addEventListener('mouseup', onUp)
    },
    [panelHeight, panelHeightVh],
  )

  // Keyboard: Esc closes dock — but only when no PrimeReact Dialog or
  // similar focus-trapping modal is open. Without this scope, Esc on
  // ManualLinksDialog would close both the dialog and the dock at the
  // same time, dropping the trader's row selection state.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      const dialogOpen =
        document.querySelector('.p-dialog:not(.p-dialog-hidden)') !== null
      if (dialogOpen) return
      onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  // Data — all hooks gracefully no-op when focused is null. Intraday
  // only fires when the user actually switches to the intraday view.
  const ts = useAnalyticsTimeseries(focused, tsState.range, tsState.view, {
    useGrossDv01: tsState.useGrossDv01,
    excludeLargeCusty: tsState.excludeComicallyLargeCusty,
    // Phase 4: when the user pivots to canonical bucketing, switch the
    // groupBy + override the SQL `value` to the canonical key. The
    // canonical key (e.g. "USD/SOFR-OIS/COMPOUND") replaces the
    // focused-trade tape_label as the bucket identifier.
    groupBy: tsState.groupBy,
    groupValueOverride:
      tsState.groupBy === 'canonical' ? tsState.canonicalKey : null,
  })
  const rarity = useRarityData(focused, {
    lookback: 90,
    primaryTol: rarityState.primaryTol,
    sizeTol: rarityState.sizeTol,
    // UX-02: pipe the trader-selected histogram metric so the server
    // re-bins the distribution in the right units (rate-bps / DV01 /
    // notional-MM) instead of always returning rate-bps bins.
    binMetric: rarityState.histogramMetric === 'dv01'
      ? 'dv01'
      : rarityState.histogramMetric === 'notional'
        ? 'notional'
        : 'fixed_rate',
  })
  const extremes = useExtremesData(focused, {
    primaryTol: parsePositiveNumberInput(levelsState.primaryTol, 2),
    sizeTol: parsePositiveNumberInput(levelsState.sizeTolPct, 25) / 100,
  })

  const focusedPercentile =
    rarityState.basis === 'custy' ? rarity.focusedPercentile.custy
    : rarityState.basis === 'idb' ? rarity.focusedPercentile.idb
    : rarity.focusedPercentile.combined
  const rarityPrimaryPercentile =
    rarity.metricRows.find((row) => row.primary)?.percentile ?? focusedPercentile

  // Histogram brushing — clicking a bar on the Trade Rarity tab writes
  // a per-column filter to the URL so the tape below filters down to
  // packages whose weighted_fixed_rate falls in the bin's [start, end]
  // bps range. Only fires for the fixed_rate histogram metric; DV01 /
  // notional bins fall through to a no-op (the package-level metrics
  // those would filter on aren't symmetric with the leg-level series
  // the histogram pulls from).
  const router = useRouter()
  const pathname = usePathname()
  const searchParams = useSearchParams()
  const onBinBrush = useCallback(
    (binStartBps: number, binEndBps: number, metric: 'fixed_rate' | 'dv01' | 'notional') => {
      if (metric !== 'fixed_rate') return
      // Tape's `weighted_fixed_rate` column lives as a decimal (0.03842
      // = 3.842% = 384.2 bps). Convert the histogram bin's bps bounds
      // before writing the filter or the trader sees an empty tape.
      const start = binStartBps / 10_000
      const end = binEndBps / 10_000
      const next = new URLSearchParams(searchParams?.toString() ?? '')
      const payload = {
        weighted_fixed_rate: {
          operator: FilterOperator.AND,
          constraints: [
            { value: start, matchMode: FilterMatchMode.GREATER_THAN_OR_EQUAL_TO },
            { value: end, matchMode: FilterMatchMode.LESS_THAN },
          ],
        },
      }
      next.set(COLUMN_FILTER_QUERY_KEY, JSON.stringify(payload))
      router.replace(`${pathname}?${next.toString()}`, { scroll: false })
    },
    [pathname, router, searchParams],
  )

  return (
    <div
      className="flex min-h-0 flex-col border-t-2 border-indigo-500/40 bg-slate-950"
      // SSR renders with a viewport-relative height (no window access);
      // post-mount the state swaps to a pixel value so drag-resize works.
      style={panelHeight == null ? { height: `${panelHeightVh}vh` } : { height: panelHeight }}
    >
      <div
        onMouseDown={onStartResize}
        className="group relative h-1 w-full cursor-ns-resize bg-slate-900 hover:bg-indigo-500/30"
        title="Drag to resize analytics dock"
      >
        <div className="absolute left-1/2 top-1/2 h-[2px] w-8 -translate-x-1/2 -translate-y-1/2 rounded-full bg-slate-700 group-hover:bg-indigo-400" />
      </div>

      <div className="flex items-center gap-2 border-b border-slate-800 bg-slate-900/40 px-3 py-1.5">
        <span className="text-[10.5px] font-mono uppercase tracking-wider text-slate-400">
          Analytics dock
        </span>
        <span className="rounded bg-indigo-500/15 px-1.5 py-[1px] font-mono text-[9.5px] text-indigo-200 ring-1 ring-indigo-500/30">
          v2
        </span>
        {ts.loading || rarity.loading || extremes.loading ? (
          <span className="rounded bg-sky-500/15 px-1.5 py-[1px] font-mono text-[9.5px] text-sky-200 ring-1 ring-sky-500/30">
            loading…
          </span>
        ) : null}
        {ts.error ? (
          <span
            className="rounded bg-rose-500/15 px-1.5 py-[1px] font-mono text-[9.5px] text-rose-200 ring-1 ring-rose-500/30"
            title={ts.error}
          >
            timeseries error
          </span>
        ) : null}
        {rarity.error ? (
          <span
            className="rounded bg-rose-500/15 px-1.5 py-[1px] font-mono text-[9.5px] text-rose-200 ring-1 ring-rose-500/30"
            title={rarity.error}
          >
            rarity error
          </span>
        ) : null}
        {extremes.error ? (
          <span
            className="rounded bg-rose-500/15 px-1.5 py-[1px] font-mono text-[9.5px] text-rose-200 ring-1 ring-rose-500/30"
            title={extremes.error}
          >
            extremes error
          </span>
        ) : null}
        <span className="ml-auto flex items-center gap-1 font-mono text-[10px] text-slate-500">
          <kbd className="rounded border border-slate-700 px-1 py-[1px] text-slate-400">↑↓</kbd>
          <span>switch row</span>
          <span className="mx-1 text-slate-700">·</span>
          <kbd className="rounded border border-slate-700 px-1 py-[1px] text-slate-400">Esc</kbd>
          <span>close</span>
        </span>
        <button
          type="button"
          onClick={onClose}
          className="ml-1 rounded border border-slate-700 px-2 py-[3px] font-mono text-[10px] text-slate-300 hover:bg-slate-800"
        >
          ▼ Hide
        </button>
      </div>

      <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-auto px-3 pb-3 pt-2">
        {mode === 'empty' ? (
          <div className="flex flex-1 items-center justify-center rounded border border-dashed border-slate-800 bg-slate-900/40 px-4 py-8">
            <div className="flex flex-col items-center gap-2 text-center font-mono">
              <span className="h-2 w-2 animate-pulse rounded-full bg-indigo-400" />
              <div className="text-[12px] uppercase tracking-wider text-slate-300">
                Select a tape row
              </div>
              <div className="max-w-[480px] text-[10.5px] text-slate-500">
                The analytics dock renders real timeseries, distribution, and extremes for a
                focused bucket. Check a row in the table above to populate the three tabs.
                Cmd/Shift-click multiple rows to switch the dock into sequence mode.
              </div>
            </div>
          </div>
        ) : null}
        {mode === 'single' && focused ? (
          <FocusedTradeBar trade={focused} onClear={onClearFocused} />
        ) : null}
        {mode === 'sequence' && sequence ? (
          <SequenceBar
            sequence={sequence}
            aggregate={seqAnalytics.aggregate ?? computeSequenceAggregate(sequence)}
            onClear={onClearFocused}
            warning={seqAnalytics.warning}
          />
        ) : null}

        {focused == null ? null : (
        <Tabs<AnalyticsTab>
          active={activeTab}
          onChange={setActiveTab}
          tabs={[
            { key: 'timeseries', label: 'Timeseries', icon: '◠' },
            {
              key: 'rarity',
              label: 'Trade Rarity',
              icon: '◉',
              // Only display the percentile badge once the rarity API
              // has settled. Before then `focusedPercentile` defaults
              // to 50, which the trader could mis-read as a real "P50"
              // result. Ellipsis communicates "in flight" instead.
              badge: rarity.stats.count > 0 ? `P${Math.round(rarityPrimaryPercentile)}` : '…',
            },
            { key: 'levels', label: 'Traded Levels', icon: '◈', badge: String(extremes.extremes.length) },
          ]}
        />
        )}

        {focused == null ? null : (
        <div className="mt-0.5">
          {activeTab === 'timeseries' ? (
            <TimeseriesTab
              focused={focused}
              state={tsState}
              setState={setTsState}
              dailyClose={ts.dailyClose}
              intraday={ts.intraday}
              stats={rarity.stats}
              focusedPercentile={focusedPercentile}
              chartHeight={chartHeight}
            />
          ) : null}
          {activeTab === 'rarity' ? (
            <TradeRarityTab
              focused={focused}
              state={rarityState}
              setState={setRarityState}
              bins={rarity.bins}
              binMetric={rarity.binMetric}
              binWidth={rarity.binWidth}
              stats={rarity.stats}
              binStats={rarity.binStats}
              metricRows={rarity.metricRows}
              recency={rarity.recency}
              focusedPercentile={focusedPercentile}
              histogramHeight={histogramHeight}
              loading={rarity.loading}
              onBinBrush={onBinBrush}
            />
          ) : null}
          {activeTab === 'levels' ? (
            <TradedLevelsTab
              focused={focused}
              state={levelsState}
              setState={setLevelsState}
              extremes={extremes.extremes}
              recentSimilar={extremes.recentSimilar}
              stats={rarity.stats}
              focusedPercentile={focusedPercentile}
              onSeek={(extreme) => {
                setActiveTab('timeseries')
                const rangeByScope: Record<string, TimeseriesState['range']> = {
                  'All-time': '1Y',
                  '52 weeks': '1Y',
                  '30 days': '1M',
                }
                setTsState((s) => ({
                  ...s,
                  range: rangeByScope[extreme.scope] ?? '1Y',
                  metric: 'fixed_rate',
                  view: 'DAILY_CLOSE',
                }))
              }}
            />
          ) : null}
        </div>
        )}
      </div>

      {/*
        Always-on PR-#286 cards drawer. Sits below the tab content in
        both single and sequence modes (and when nothing is selected
        yet). Default state is collapsed; the drawer's own
        localStorage handling persists the trader's preference.
      */}
      <CardsDrawer rows={rows} />
    </div>
  )
}
