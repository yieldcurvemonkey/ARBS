'use client'
// Focused-trade context bar — sticky strip at the top of the analytics
// dock reminding the trader which row drives the tabs. Shows key fields
// (rate / DV01 / notional / venue / platform) + Pin + Clear actions.
import type { JSX } from 'react'
import { PlatformDot } from './controls'
import {
  fmtBps,
  fmtDv01Compact,
  fmtNotionalMM,
} from './analytics-format'
import type { FocusedTrade } from './analytics-types'

export function FocusedTradeBar(props: {
  trade: FocusedTrade
  isDemo?: boolean
  onClear: () => void
}): JSX.Element {
  const { trade, isDemo, onClear } = props
  const platformTint =
    trade.platform === 'CUSTY'
      ? 'bg-amber-500/15 text-amber-100 ring-1 ring-amber-500/30'
      : 'bg-sky-500/15 text-sky-100 ring-1 ring-sky-500/30'
  const sideTint =
    trade.side === 'PAY'
      ? 'bg-emerald-500/15 text-emerald-200 ring-1 ring-emerald-500/30'
      : 'bg-rose-500/15 text-rose-200 ring-1 ring-rose-500/30'
  return (
    <div className="flex items-center gap-3 rounded border border-indigo-500/30 bg-gradient-to-r from-indigo-500/10 to-transparent px-3 py-2">
      <div className="flex items-center gap-1.5">
        <span className="h-1.5 w-1.5 rounded-full bg-indigo-400 animate-pulse" />
        <span className="text-[9.5px] uppercase tracking-wider text-indigo-300">
          {isDemo ? 'Demo trade' : 'Focused trade'}
        </span>
      </div>
      <div className="flex items-baseline gap-2">
        <span className="font-mono text-[13px] text-slate-100">{trade.tape_label}</span>
        <span className="font-mono text-[10.5px] text-slate-500">{trade.id}</span>
      </div>
      <span className={`rounded px-1.5 py-[2px] font-mono text-[10px] ${sideTint}`}>
        {trade.side}
      </span>
      <div className="h-4 w-px bg-slate-800" />
      <div className="flex items-center gap-3 font-mono text-[11px]">
        <span>
          <span className="mr-1 text-[9.5px] uppercase tracking-wide text-slate-500">Rate</span>
          <span className="text-slate-100">{fmtBps(trade.fixed_rate_bps)}</span>
          <span className="text-slate-500"> bps</span>
        </span>
        <span>
          <span className="mr-1 text-[9.5px] uppercase tracking-wide text-slate-500">DV01</span>
          <span className="text-slate-100">{fmtDv01Compact(trade.dv01_usd_per_bp)}</span>
          <span className="text-slate-500"> USD/bp</span>
        </span>
        <span>
          <span className="mr-1 text-[9.5px] uppercase tracking-wide text-slate-500">Notional</span>
          <span className="text-slate-100">{fmtNotionalMM(trade.notional_usd)}</span>
          <span className="text-slate-500"> MM</span>
        </span>
        <span>
          <span className="mr-1 text-[9.5px] uppercase tracking-wide text-slate-500">Venue</span>
          <span className="text-slate-200">{trade.venue}</span>
        </span>
        <span className={`inline-flex items-center gap-1 rounded px-1.5 py-[2px] text-[10px] ${platformTint}`}>
          <PlatformDot platform={trade.platform} size={6} />
          <span>{trade.platform}</span>
        </span>
      </div>
      <div className="ml-auto flex items-center gap-1">
        <button
          type="button"
          className="rounded border border-slate-700 px-2 py-[3px] font-mono text-[10px] text-slate-300 hover:bg-slate-800"
          title="Pin this trade so it survives table refresh"
        >
          ◈ Pin
        </button>
        <button
          type="button"
          onClick={onClear}
          className="rounded border border-slate-700 px-2 py-[3px] font-mono text-[10px] text-slate-400 hover:bg-slate-800 hover:text-slate-200"
          title="Clear focused trade"
        >
          ✕ Clear
        </button>
      </div>
    </div>
  )
}
