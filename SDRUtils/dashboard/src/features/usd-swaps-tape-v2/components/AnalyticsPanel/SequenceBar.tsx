'use client'
// ABOUTME: Multi-trade equivalent of FocusedTradeBar. When the dock
// is in sequence mode (N≥2 selected rows), the SequenceBar replaces
// the focused-trade strip and surfaces a count chip + aggregate
// DV01 / weighted rate / notional / time span / side mix / venue
// mix. The visual cadence mirrors FocusedTradeBar so the swap is
// non-disruptive.
import type { JSX } from 'react'
import {
  fmtBps,
  fmtDv01Compact,
  fmtNotionalMM,
} from './analytics-format'
import type {
  FocusedTrade,
  SequenceAggregate,
} from './analytics-types'

function formatSpan(ms: number | null): string {
  if (ms == null) return '—'
  if (ms < 60_000) return `${Math.round(ms / 1000)}s`
  if (ms < 3_600_000) return `${Math.round(ms / 60_000)}m`
  const h = Math.floor(ms / 3_600_000)
  const m = Math.round((ms % 3_600_000) / 60_000)
  return m === 0 ? `${h}h` : `${h}h ${m}m`
}

export interface SequenceBarProps {
  sequence: readonly FocusedTrade[]
  aggregate: SequenceAggregate
  onClear: () => void
  // When the upstream sequence cap (N=20) trips, the wrapper hook
  // surfaces a soft warning the bar renders next to the count chip.
  // Optional so single-mode callers don't have to thread it.
  warning?: string | null
}

export function SequenceBar({
  sequence,
  aggregate,
  onClear,
  warning = null,
}: SequenceBarProps): JSX.Element {
  const { count, totalDv01Usd, weightedFixedRateBps, totalNotionalUsd, timeSpanMs, sideMix, venueMix } = aggregate
  void sequence // reserved for hover-to-disambiguate features in a follow-up

  const sideTint =
    sideMix.pay > sideMix.rcv
      ? 'bg-emerald-500/15 text-emerald-200 ring-1 ring-emerald-500/30'
      : sideMix.rcv > sideMix.pay
        ? 'bg-rose-500/15 text-rose-200 ring-1 ring-rose-500/30'
        : 'bg-slate-500/15 text-slate-200 ring-1 ring-slate-500/30'

  return (
    <div
      data-testid="sequence-bar"
      className="flex flex-wrap items-center gap-3 rounded border border-indigo-500/30 bg-gradient-to-r from-indigo-500/10 to-transparent px-3 py-2"
    >
      <div className="flex items-center gap-1.5">
        <span className="h-1.5 w-1.5 rounded-full bg-indigo-400 animate-pulse" />
        <span
          className="text-[9.5px] uppercase tracking-wider text-indigo-300"
          title="Multi-row selection — keyboard ↑↓ navigation is disabled in sequence mode"
        >
          Sequence ({count})
        </span>
      </div>

      {warning ? (
        <span
          className="rounded bg-amber-500/15 px-1.5 py-[2px] font-mono text-[10px] text-amber-200 ring-1 ring-amber-500/30"
          title={warning}
        >
          ⚠ {warning}
        </span>
      ) : null}

      <span
        className={`rounded px-1.5 py-[2px] font-mono text-[10px] ${sideTint}`}
        data-testid="sequence-side-mix"
      >
        {sideMix.pay} PAY / {sideMix.rcv} RCV
      </span>

      <div className="h-4 w-px bg-slate-800" />

      <div className="flex flex-wrap items-center gap-3 font-mono text-[11px]">
        <span>
          <span className="mr-1 text-[9.5px] uppercase tracking-wide text-slate-500">DV01</span>
          <span className="text-slate-100">{fmtDv01Compact(totalDv01Usd)}</span>
          <span className="text-slate-500"> USD/bp</span>
        </span>
        <span>
          <span className="mr-1 text-[9.5px] uppercase tracking-wide text-slate-500">Wtd Rate</span>
          <span className="text-slate-100">{fmtBps(weightedFixedRateBps)}</span>
          <span className="text-slate-500"> bps</span>
        </span>
        <span>
          <span className="mr-1 text-[9.5px] uppercase tracking-wide text-slate-500">Notional</span>
          <span className="text-slate-100">{fmtNotionalMM(totalNotionalUsd)}</span>
          <span className="text-slate-500"> MM</span>
        </span>
        <span>
          <span className="mr-1 text-[9.5px] uppercase tracking-wide text-slate-500">Span</span>
          <span className="text-slate-100">{formatSpan(timeSpanMs)}</span>
        </span>
      </div>

      <div className="flex flex-wrap items-center gap-1" data-testid="sequence-venue-mix">
        {Object.keys(venueMix).map((venue) => (
          <span
            key={venue}
            className="rounded bg-slate-700/40 px-1.5 py-[2px] font-mono text-[10px] text-slate-200 ring-1 ring-slate-600/40"
          >
            {venue}: {venueMix[venue]}
          </span>
        ))}
      </div>

      <div className="ml-auto flex items-center gap-1">
        <button
          type="button"
          onClick={onClear}
          className="rounded border border-slate-700 px-2 py-[3px] font-mono text-[10px] text-slate-400 hover:bg-slate-800 hover:text-slate-200"
          title="Clear selection"
        >
          ✕ Clear
        </button>
      </div>
    </div>
  )
}
