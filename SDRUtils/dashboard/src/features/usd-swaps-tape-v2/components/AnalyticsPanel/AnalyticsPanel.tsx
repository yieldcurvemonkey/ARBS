'use client'
// AnalyticsPanel — collapsible, resizable dock that mounts below the
// tape table and hosts the Timeseries / Trade Rarity / Traded Levels tabs
// for a focused trade.
import type { JSX } from 'react'
import { useCallback, useEffect, useRef, useState } from 'react'
import {
  useAnalyticsTimeseries,
  useExtremesData,
  useRarityData,
} from '../../hooks'
import { FocusedTradeBar } from './FocusedTradeBar'
import { TimeseriesTab } from './TimeseriesTab'
import { TradeRarityTab } from './TradeRarityTab'
import { TradedLevelsTab } from './TradedLevelsTab'
import { Tabs } from './controls'
import {
  DOCK_DEFAULT_VH,
  DOCK_MAX_RESERVE_PX,
  DOCK_MIN_PX,
  RARITY_DEFAULT_STATE,
  TIMESERIES_DEFAULT_STATE,
} from './constants'
import type {
  AnalyticsTab,
  FocusedTrade,
  RarityState,
  TimeseriesState,
} from './analytics-types'

export interface AnalyticsPanelProps {
  focused: FocusedTrade | null
  onClose: () => void
  onClearFocused: () => void
  chartHeight?: number
  histogramHeight?: number
  panelHeightVh?: number
}

export function AnalyticsPanel(props: AnalyticsPanelProps): JSX.Element {
  const {
    focused, onClose, onClearFocused,
    chartHeight = 340, histogramHeight = 280,
    panelHeightVh = DOCK_DEFAULT_VH,
  } = props

  const [activeTab, setActiveTab] = useState<AnalyticsTab>('timeseries')
  const [tsState, setTsState] = useState<TimeseriesState>(TIMESERIES_DEFAULT_STATE)
  const [rarityState, setRarityState] = useState<RarityState>(RARITY_DEFAULT_STATE)

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

  // Keyboard: Esc closes dock.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  // Data — all hooks gracefully no-op when focused is null. Intraday
  // only fires when the user actually switches to the intraday view.
  const ts = useAnalyticsTimeseries(focused, tsState.range, tsState.view)
  const rarity = useRarityData(focused, {
    lookback: 90,
    primaryTol: rarityState.primaryTol,
    sizeTol: rarityState.sizeTol,
  })
  const extremes = useExtremesData(focused, {
    primaryTol: rarityState.primaryTol,
    sizeTol: rarityState.sizeTol,
  })

  const focusedPercentile =
    rarityState.basis === 'custy' ? rarity.focusedPercentile.custy
    : rarityState.basis === 'idb' ? rarity.focusedPercentile.idb
    : rarity.focusedPercentile.combined

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
        {ts.error || rarity.error || extremes.error ? (
          <span
            className="rounded bg-rose-500/15 px-1.5 py-[1px] font-mono text-[9.5px] text-rose-200 ring-1 ring-rose-500/30"
            title={ts.error ?? rarity.error ?? extremes.error ?? ''}
          >
            fetch error
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
        {focused == null ? (
          <div className="flex flex-1 items-center justify-center rounded border border-dashed border-slate-800 bg-slate-900/40 px-4 py-8">
            <div className="flex flex-col items-center gap-2 text-center font-mono">
              <span className="h-2 w-2 animate-pulse rounded-full bg-indigo-400" />
              <div className="text-[12px] uppercase tracking-wider text-slate-300">
                Select a tape row
              </div>
              <div className="max-w-[480px] text-[10.5px] text-slate-500">
                The analytics dock renders real timeseries, distribution, and extremes for a
                focused bucket. Check a row in the table above to populate the three tabs.
              </div>
            </div>
          </div>
        ) : (
          <FocusedTradeBar trade={focused} onClear={onClearFocused} />
        )}

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
              badge: rarity.stats.count > 0 ? `P${Math.round(focusedPercentile)}` : '…',
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
              stats={rarity.stats}
              metricRows={rarity.metricRows}
              recency={rarity.recency}
              focusedPercentile={focusedPercentile}
              histogramHeight={histogramHeight}
            />
          ) : null}
          {activeTab === 'levels' ? (
            <TradedLevelsTab
              focused={focused}
              extremes={extremes.extremes}
              recentSimilar={extremes.recentSimilar}
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
    </div>
  )
}
