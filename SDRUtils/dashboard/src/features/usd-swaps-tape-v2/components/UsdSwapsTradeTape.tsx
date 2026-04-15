'use client'
// ABOUTME: Main orchestrator for the USD swap tape v2 feature.
import type { JSX } from 'react'
import { useCallback, useMemo, useState } from 'react'
import 'primereact/resources/themes/lara-dark-indigo/theme.css'
import 'primereact/resources/primereact.min.css'
import 'primeicons/primeicons.css'
import { TradeTapeHeader } from './TradeTapeHeader/TradeTapeHeader'
import { FilterChips } from './TradeTapeFilters/FilterChips'
import { TradeTapeFilters } from './TradeTapeFilters/TradeTapeFilters'
import { TradeTapeTable } from './TradeTapeTable/TradeTapeTable'
import { ClusterTimelineStrip } from './Sidecars/TemporalClusterTimeline/ClusterTimelineStrip'
import { SidecarDrawer, type SidecarName } from './Sidecars/SidecarDrawer'
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
  const columnFilters = useColumnFilters()
  const expansion = useRowExpansion()
  const selection = useRowSelection()

  const [search, setSearch] = useState('')
  const [activeModal, setActiveModal] = useState<ModalName>(null)
  const [activeSidecar, setActiveSidecar] = useState<SidecarName>('risk')
  const [timelineVisible, setTimelineVisible] = useState(true)

  const tape = useTradeTapeData({
    // search is handled client-side via fuzzy filter in TradeTapeTable — do NOT
    // forward it to the server. The server still receives column filters and
    // the URL-synced filter payload so power-user SQL-style filters keep working.
    columnFilterPayloadKey:
      Object.keys(columnFilters.filters).length > 0
        ? JSON.stringify(columnFilters.filters)
        : undefined,
    columnFilterOperator: columnFilters.operator,
    flagFilters: flagFilters.state,
  })

  // Pick the as-of date from the latest row we actually have data for, so
  // the sidecar aggregates query the same day the tape is showing. Falls
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

  const handleFilterByFomc = useCallback(
    (label: string) => {
      flagFilters.setFomcMeeting(label)
    },
    [flagFilters],
  )

  const liveStatus: 'live' | 'amber' | 'offline' = tape.pollError
    ? 'amber'
    : tape.initialError
      ? 'offline'
      : 'live'

  return (
    <div className="flex flex-col h-screen bg-slate-950 text-slate-100">
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
      <TradeTapeFilters
        search={search}
        onSearch={setSearch}
        operator={columnFilters.operator}
        onOperatorChange={columnFilters.setOperator}
        onReset={() => {
          setSearch('')
          columnFilters.reset()
          flagFilters.resetAll()
        }}
      />
      {timelineVisible ? (
        <ClusterTimelineStrip
          date={asOf}
          onSelectCluster={(id) => {
            // Reserved — cluster filter can be wired to columnFilters when
            // the column-filter mapping for cluster_id is added.
            void id
          }}
        />
      ) : null}
      <div className="flex items-center justify-between px-3 py-1 text-xs text-slate-400 border-b border-slate-800">
        <span>
          {tape.rows.length} rows{tape.hasMore ? ' (more available)' : ''}
        </span>
        <div className="flex items-center gap-2">
          <button
            type="button"
            className="text-xs text-slate-400 hover:text-slate-100"
            onClick={() => setTimelineVisible((v) => !v)}
          >
            {timelineVisible ? 'Hide' : 'Show'} timeline
          </button>
          {selection.count > 0 ? (
            <button
              type="button"
              className="text-xs text-sky-200 hover:text-sky-100"
              onClick={() => setActiveModal('links')}
            >
              Link {selection.count} selected
            </button>
          ) : null}
        </div>
      </div>
      <div className="flex flex-1 overflow-hidden">
        <TradeTapeTable
          rows={tape.rows}
          loading={tape.loading}
          onLoadMore={tape.loadMore}
          hasMore={tape.hasMore}
          expandedRows={expansion.expandedRows}
          onRowToggle={expansion.onRowToggle}
          selected={selection.selected}
          onSelectionChange={selection.onSelectionChange}
          onOpenTimeseries={() => setActiveModal('timeseries')}
          search={search}
        />
        {activeSidecar ? (
          <SidecarDrawer
            active={activeSidecar}
            date={asOf}
            clean={flagFilters.state.clean}
            onChange={setActiveSidecar}
            onFilterByGroupValue={(groupBy, value) => {
              if (groupBy === 'tape_label') return // reserved
              if (groupBy === 'trade_type') flagFilters.toggleTradeType(value)
              if (groupBy === 'venue') flagFilters.toggleVenue(value)
              if (groupBy === 'ccp') flagFilters.toggleCcp(value)
              if (groupBy === 'session') flagFilters.toggleSession(value)
              if (groupBy === 'rate_index') flagFilters.toggleRateIndex(value)
              if (groupBy === 'tenor') flagFilters.toggleTenor(value)
              if (groupBy === 'fomc_meeting') flagFilters.setFomcMeeting(value)
            }}
            onFilterByPackageId={(pid) => {
              setSearch(pid)
            }}
            onFilterByFomcMeeting={handleFilterByFomc}
          />
        ) : null}
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
