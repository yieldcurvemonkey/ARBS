'use client'
// ABOUTME: Three-strip tape header — title, summary stats, lifecycle mix.
import type { JSX } from 'react'
import { formatDv01, formatNotional } from '../../utils/format'
import type { FlagFilterState, LifecycleType, UsdSwapTapeRow } from '../../types'
import { CleanTapeToggle } from './CleanTapeToggle'
import { FlagChips } from './FlagChips'
import { summarize } from './TradeTapeHeader.helpers'

export { summarize } from './TradeTapeHeader.helpers'

export interface TradeTapeHeaderProps {
  asOfDate: string | null
  liveStatus: 'live' | 'amber' | 'offline'
  rows: UsdSwapTapeRow[]
  flagFilters: FlagFilterState
  onRefresh: () => void
  onOpenFlowHistory: () => void
  onOpenMethodology: () => void
  onToggleLifecycle: (type: LifecycleType) => void
  onApplyClean: () => void
  onResetClean: () => void
  onFilterByLifecycle: (type: LifecycleType) => void
}

function StatButton({
  label,
  value,
  onClick,
}: {
  label: string
  value: string
  onClick?: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex flex-col items-start rounded px-1 py-0 text-left leading-none hover:bg-slate-800/40"
    >
      <span className="text-[9px] uppercase tracking-wide text-slate-400">{label}</span>
      <span className="font-mono tabular-nums text-[13px] text-slate-100">{value}</span>
    </button>
  )
}

export function TradeTapeHeader(props: TradeTapeHeaderProps): JSX.Element {
  const summary = summarize(props.rows)
  const liveColor =
    props.liveStatus === 'live'
      ? 'bg-emerald-500'
      : props.liveStatus === 'amber'
        ? 'bg-amber-500'
        : 'bg-red-500'
  return (
    <header className="flex flex-col gap-px border-b border-slate-800 bg-slate-900/70 px-3 py-1">
      {/* Strip 1: title + controls */}
      <div className="flex items-center gap-2.5">
        <h1 className="text-sm font-semibold text-slate-100">USD swap tape</h1>
        {props.asOfDate ? (
          <span className="font-mono text-[11px] text-slate-400">as of {props.asOfDate}</span>
        ) : null}
        <span
          title={`live status: ${props.liveStatus}`}
          aria-label={`live status ${props.liveStatus}`}
          className={`inline-block w-2 h-2 rounded-full ${liveColor}`}
        />
        <div className="flex-1" />
        <button
          type="button"
          className="rounded bg-slate-800/70 px-2 py-0.5 text-[11px] text-slate-200 hover:bg-slate-700/70"
          onClick={props.onRefresh}
        >
          Refresh
        </button>
        <button
          type="button"
          className="rounded bg-slate-800/70 px-2 py-0.5 text-[11px] text-slate-200 hover:bg-slate-700/70"
          onClick={props.onOpenFlowHistory}
        >
          Flow history
        </button>
        <button
          type="button"
          className="rounded bg-slate-800/70 px-2 py-0.5 text-[11px] text-slate-200 hover:bg-slate-700/70"
          onClick={props.onOpenMethodology}
        >
          Methodology
        </button>
      </div>
      {/* Strip 2: summary stats */}
      <div className="flex items-center gap-0.5">
        <StatButton
          label="Trades"
          value={summary.tradeCount.toLocaleString()}
        />
        <StatButton
          label="New risk"
          value={summary.newRisk.toLocaleString()}
          onClick={() => props.onFilterByLifecycle('NEW_RISK')}
        />
        <StatButton
          label="Gross DV01"
          value={formatDv01(summary.grossDv01)}
        />
        <StatButton
          label="Gross notional"
          value={formatNotional(summary.grossNotional, { compact: true })}
        />
        <StatButton
          label="Packages"
          value={summary.packageCount.toLocaleString()}
        />
        <StatButton
          label="Clusters"
          value={summary.clusterCount.toLocaleString()}
        />
        <div className="flex-1" />
        <CleanTapeToggle
          clean={props.flagFilters.clean}
          onApply={props.onApplyClean}
          onReset={props.onResetClean}
        />
      </div>
      {/* Strip 3: lifecycle pills */}
      <div className="flex items-center overflow-x-auto pb-px">
        <FlagChips
          counts={summary.lifecycleCounts}
          selected={props.flagFilters.lifecycle}
          onToggle={props.onToggleLifecycle}
        />
      </div>
    </header>
  )
}
