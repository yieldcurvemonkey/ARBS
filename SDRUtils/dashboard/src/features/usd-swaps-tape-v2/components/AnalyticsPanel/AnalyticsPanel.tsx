'use client'
// AnalyticsPanel — collapsible, resizable dock that mounts below the
// tape table and hosts the Timeseries / Trade Rarity / Traded Levels tabs
// for a focused trade.
import type { JSX } from 'react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
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
import { IntradayPrintsPanel } from './IntradayPrintsPanel'
import { MmsTab } from './MmsTab'
import { SequenceBar } from './SequenceBar'
import { SequenceTab } from './SequenceTab'
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
  MMS_DEFAULT_STATE,
  RARITY_DEFAULT_STATE,
  RARITY_PREFS_STORAGE_KEY,
  TIMESERIES_DEFAULT_STATE,
} from './constants'
import { parsePositiveNumberInput } from './TradedLevelsTab.helpers'
import type {
  AnalyticsTab,
  FocusedTrade,
  LevelsState,
  MmsState,
  RarityState,
  TimeseriesState,
} from './analytics-types'
import type { UsdSwapTapeRow } from '../../types'
import { computeMmsSummary } from '../../utils/mmsAnalytics'
import { useIsMobile } from '@/lib/hooks/useIsMobile'

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
  const isMobile = useIsMobile()
  const derived = deriveAnalyticsSelection(selected)
  const mode = derived.mode
  const sequence = derived.sequence

  // MMS tab — badge count + tab body both read off the full loaded
  // row set (not gated on a focused trade), same pattern as CardsDrawer.
  const mmsSummary = useMemo(() => computeMmsSummary(rows), [rows])

  // The base tab hooks (single-trade Timeseries / Rarity / Levels)
  // need a non-null `focused` to fire fetches. In sequence mode we
  // anchor on the first sequence entry so the chart base series is
  // a real bucket; subsequent sequence trades layer in via the
  // multi-overlay reference lines + dots.
  const baseTrade: FocusedTrade | null =
    focused ?? (sequence?.[0] ?? null)

  const [activeTab, setActiveTab] = useState<AnalyticsTab>('timeseries')
  const [tsState, setTsState] = useState<TimeseriesState>(TIMESERIES_DEFAULT_STATE)
  const [levelsState, setLevelsState] = useState<LevelsState>(LEVELS_DEFAULT_STATE)
  const [mmsState, setMmsState] = useState<MmsState>(MMS_DEFAULT_STATE)
  // Rarity prefs persist to localStorage so the trader doesn't have to
  // reconfigure the basis / similarity thresholds on every dock open.
  // Read synchronously on first render — a hydrate-in-effect pattern
  // would force the rarity hook to fetch twice per row click (once
  // with defaults, once with the loaded prefs) because the cache key
  // depends on histogramMetric. The dock's heavy controls don't render
  // until a row is focused, so the SSR / CSR markup mismatch the
  // effect-based pattern was guarding against doesn't apply.
  const [rarityState, setRarityState] = useState<RarityState>(() => {
    if (typeof window === 'undefined') return RARITY_DEFAULT_STATE
    try {
      const raw = window.localStorage.getItem(RARITY_PREFS_STORAGE_KEY)
      if (!raw) return RARITY_DEFAULT_STATE
      const parsed = JSON.parse(raw) as Partial<RarityState>
      return {
        ...RARITY_DEFAULT_STATE,
        basis: parsed.basis ?? RARITY_DEFAULT_STATE.basis,
        histogramMetric: parsed.histogramMetric ?? RARITY_DEFAULT_STATE.histogramMetric,
        primaryTol:
          typeof parsed.primaryTol === 'number' ? parsed.primaryTol : RARITY_DEFAULT_STATE.primaryTol,
        sizeTol:
          typeof parsed.sizeTol === 'number' ? parsed.sizeTol : RARITY_DEFAULT_STATE.sizeTol,
      }
    } catch {
      return RARITY_DEFAULT_STATE
    }
  })
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

  // Phase E — wrapper hook fans out to the per-trade analytics hooks
  // for each member of the sequence (no-op when sequence is null) and
  // aggregates the sequence-level summary. We pass the same per-tab
  // options the single-trade hooks below use so the wrapper's inner
  // useRarityData / useExtremesData calls hit the same SWR cache keys
  // — without this, the wrapper's defaults (binMetric=fixed_rate)
  // would diverge from the dock's user-driven binMetric and double
  // the rarity request count on first row click.
  const seqRarityBinMetric =
    rarityState.histogramMetric === 'dv01'
      ? ('dv01' as const)
      : rarityState.histogramMetric === 'notional'
        ? ('notional' as const)
        : ('fixed_rate' as const)
  const seqAnalytics = useAnalyticsSequence(sequence, {
    range: tsState.range,
    view: tsState.view,
    tsOptions: {
      groupBy: tsState.groupBy,
      groupValueOverride:
        tsState.groupBy === 'canonical' ? tsState.canonicalKey : null,
      removeZeroRates: tsState.removeZeroRates,
    },
    rarityOptions: {
      lookback: 90,
      primaryTol: rarityState.primaryTol,
      sizeTol: rarityState.sizeTol,
      binMetric: seqRarityBinMetric,
    },
    extremesOptions: {
      primaryTol: parsePositiveNumberInput(levelsState.primaryTol, 2),
      sizeTol: parsePositiveNumberInput(levelsState.sizeTolPct, 25) / 100,
    },
  })

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
  //
  // Phase H — sequence-mode guard. Arrow-up / arrow-down are
  // intercepted and silenced when mode === 'sequence' so any
  // upstream ↑↓ row-navigation handler doesn't accidentally
  // re-enter single-row focus behaviour while a multi-row sequence
  // is active. The kbd hint above renders the chip strikethrough
  // with a tooltip so the trader sees the disabled state.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        const dialogOpen =
          document.querySelector('.p-dialog:not(.p-dialog-hidden)') !== null
        if (dialogOpen) return
        onClose()
        return
      }
      if (mode === 'sequence' && (e.key === 'ArrowUp' || e.key === 'ArrowDown')) {
        // No preventDefault — we don't want to interfere with focus
        // movement on form fields inside the dock. We just ensure
        // any future row-nav handler dispatched at window-level
        // sees the guard.
        e.stopPropagation()
        return
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose, mode])

  // Data — all hooks gracefully no-op when focused is null. Intraday
  // only fires when the user actually switches to the intraday view.
  // In sequence mode, baseTrade falls back to sequence[0] so the
  // tab base series renders against a real bucket; the multi-overlay
  // reference lines layer the rest of the sequence on top.
  const ts = useAnalyticsTimeseries(baseTrade, tsState.range, tsState.view, {
    useGrossDv01: tsState.useGrossDv01,
    excludeLargeCusty: tsState.excludeComicallyLargeCusty,
    // Phase 4: when the user pivots to canonical bucketing, switch the
    // groupBy + override the SQL `value` to the canonical key. The
    // canonical key (e.g. "USD/SOFR-OIS/COMPOUND") replaces the
    // focused-trade tape_label as the bucket identifier.
    groupBy: tsState.groupBy,
    groupValueOverride:
      tsState.groupBy === 'canonical' ? tsState.canonicalKey : null,
    removeZeroRates: tsState.removeZeroRates,
  })
  const rarity = useRarityData(baseTrade, {
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
  const extremes = useExtremesData(baseTrade, {
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
      style={
        isMobile
          ? { height: '50vh' }
          : panelHeight == null
            ? { height: `${panelHeightVh}vh` }
            : { height: panelHeight }
      }
    >
      {!isMobile && (
        <div
          onMouseDown={onStartResize}
          className="group relative h-1 w-full cursor-ns-resize bg-slate-900 hover:bg-indigo-500/30"
          title="Drag to resize analytics dock"
        >
          <div className="absolute left-1/2 top-1/2 h-[2px] w-8 -translate-x-1/2 -translate-y-1/2 rounded-full bg-slate-700 group-hover:bg-indigo-400" />
        </div>
      )}

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
        {!isMobile && (
          <span
            className="ml-auto flex items-center gap-1 font-mono text-[10px] text-slate-500"
            data-testid="dock-keyboard-hints"
          >
            <kbd
              className={`rounded border px-1 py-[1px] ${
                mode === 'sequence'
                  ? 'border-slate-800 text-slate-600 line-through'
                  : 'border-slate-700 text-slate-400'
              }`}
              title={
                mode === 'sequence'
                  ? 'Arrow-key navigation is disabled in sequence mode — clear the selection to re-enable.'
                  : undefined
              }
              data-disabled={mode === 'sequence' ? 'true' : 'false'}
            >
              ↑↓
            </kbd>
            <span className={mode === 'sequence' ? 'text-slate-600 line-through' : ''}>
              switch row
            </span>
            <span className="mx-1 text-slate-700">·</span>
            <kbd className="rounded border border-slate-700 px-1 py-[1px] text-slate-400">Esc</kbd>
            <span>close</span>
          </span>
        )}
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

        {/*
          Phase F + G — tab strip. In sequence mode we anchor the
          tab data hooks to the first sequence trade so the chart
          base series renders against a real bucket (subsequent
          trades layer in via the multi-overlay reference lines).
          The `Sequence` tab only appears in sequence mode.

          MMS tab workstream — the strip itself is no longer gated on
          focused/sequence: the MMS tab aggregates over the full loaded
          `rows` set (like CardsDrawer) so it must stay reachable even
          when mode === 'empty' (nothing focused/selected). Only the
          `Sequence` entry keeps its mode-scoped visibility below.
        */}
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
            { key: 'mms', label: 'MMS', icon: '⬡', badge: String(mmsSummary.mmsCount) },
            { key: 'prints', label: 'Intraday Prints', icon: '◰' },
            ...(mode === 'sequence' && sequence
              ? ([{ key: 'sequence' as const, label: 'Sequence', icon: '⇉', badge: String(sequence.length) }])
              : []),
          ]}
        />

        {baseTrade == null ? null : (
        <div className="mt-0.5">
          {activeTab === 'timeseries' ? (
            <TimeseriesTab
              focused={baseTrade}
              sequence={sequence ?? undefined}
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
              focused={baseTrade}
              sequence={sequence ?? undefined}
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
              focused={baseTrade}
              sequence={sequence ?? undefined}
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
          {activeTab === 'sequence' && mode === 'sequence' && sequence ? (
            <SequenceTab
              sequence={sequence}
              rows={rows}
              aggregate={seqAnalytics.aggregate ?? computeSequenceAggregate(sequence)}
            />
          ) : null}
        </div>
        )}

        {/*
          MMS tab renders OUTSIDE the baseTrade guard above — it
          aggregates over the full loaded `rows` set (like CardsDrawer)
          rather than a focused trade, so it must stay usable even when
          nothing is selected (mode === 'empty', baseTrade == null).
        */}
        {activeTab === 'mms' ? (
          <div className="mt-0.5">
            <MmsTab
              rows={rows}
              state={mmsState}
              setState={setMmsState}
            />
          </div>
        ) : null}

        {/*
          Intraday prints renders OUTSIDE the baseTrade guard for the same
          reason MMS does, and one more: it does not read  at all. It
          queries one session of one tenor from its own endpoint and carries
          its own filters, so a focused trade is neither needed nor used.
        */}
        {activeTab === 'prints' ? (
          <div className="mt-0.5">
            {/* The panel FOLLOWS this row: tenor, rate index, venue class and
                tape day all come from the tape's selection. `source` is the
                raw tape row, which is where tenor_display and
                rate_index_clean live. */}
            {/* `source` is the raw tape row and carries legs_json, but
                package_structure is only GUARANTEED on the FocusedTrade —
                useFocusedTrade defaults it from package_type when the display
                row lacks it. Passing the raw row alone made every CURVE and
                FLY fall through to the outright chart. Merge, so the structure
                switch sees a name and the leg tenors both. */}
            <IntradayPrintsPanel
              focused={
                baseTrade
                  ? {
                      ...(baseTrade.source ?? {}),
                      package_structure: baseTrade.package_structure,
                      execution_start: baseTrade.execution_start,
                    }
                  : null
              }
            />
          </div>
        ) : null}
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
