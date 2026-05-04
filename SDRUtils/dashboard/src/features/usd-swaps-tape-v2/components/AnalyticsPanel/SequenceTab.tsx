'use client'
// ABOUTME: Multi-trade dock — the new "Sequence" tab. Surfaces
// mechanical signals about the selected sequence (timeline, inter-
// trade gaps, lightweight chain detection, lifecycle context).
// Game-theoretic interpretation lives in tooltips/help, not in the
// UI; per the design doc this is a v1 surface with deeper analytics
// flagged as separate workstreams.
import type { JSX } from 'react'
import {
  fmtBps,
  fmtDv01Compact,
  fmtNotionalMM,
  sequenceColor,
} from './analytics-format'
import { InterTradeGaps } from './InterTradeGaps'
import { SequenceChainDetector } from './SequenceChainDetector'
import { SequenceTimeline } from './SequenceTimeline'
import type {
  FocusedTrade,
  SequenceAggregate,
} from './analytics-types'
import type { UsdSwapTapeRow } from '../../types'

function formatSpan(ms: number | null): string {
  if (ms == null) return '—'
  if (ms < 60_000) return `${Math.round(ms / 1000)}s`
  if (ms < 3_600_000) return `${Math.round(ms / 60_000)}m`
  const h = Math.floor(ms / 3_600_000)
  const m = Math.round((ms % 3_600_000) / 60_000)
  return m === 0 ? `${h}h` : `${h}h ${m}m`
}

function SummaryCell(props: { label: string; value: string; sub?: string }): JSX.Element {
  return (
    <div className="rounded border border-slate-800 bg-slate-950/60 p-2 font-mono">
      <div className="text-[9.5px] uppercase tracking-wider text-slate-500">{props.label}</div>
      <div className="mt-0.5 text-[14px] text-slate-100 tabular-nums">{props.value}</div>
      {props.sub ? <div className="mt-0.5 text-[10px] text-slate-500">{props.sub}</div> : null}
    </div>
  )
}

export interface SequenceTabProps {
  sequence: readonly FocusedTrade[]
  rows: readonly UsdSwapTapeRow[]
  aggregate: SequenceAggregate
}

export function SequenceTab({
  sequence,
  rows,
  aggregate,
}: SequenceTabProps): JSX.Element {
  return (
    <div className="flex flex-col gap-3 p-1">
      {/* Aggregate summary card — full-width, chart-friendly. */}
      <div data-testid="sequence-summary-card">
        <div className="mb-1 flex items-center justify-between">
          <span className="font-mono text-[10px] uppercase tracking-wider text-slate-500">
            Sequence summary
          </span>
          <span className="font-mono text-[10px] text-slate-500">
            {aggregate.count} trade{aggregate.count === 1 ? '' : 's'}
          </span>
        </div>
        <div className="grid grid-cols-2 gap-2 lg:grid-cols-5">
          <SummaryCell
            label="Aggregate DV01"
            value={fmtDv01Compact(aggregate.totalDv01Usd)}
            sub="USD/bp"
          />
          <SummaryCell
            label="Wtd Rate"
            value={`${fmtBps(aggregate.weightedFixedRateBps)} bps`}
          />
          <SummaryCell
            label="Total Notional"
            value={`${fmtNotionalMM(aggregate.totalNotionalUsd)} MM`}
          />
          <SummaryCell
            label="Time span"
            value={formatSpan(aggregate.timeSpanMs)}
            sub={
              aggregate.startTs && aggregate.endTs
                ? `${aggregate.startTs.slice(11, 16)} → ${aggregate.endTs.slice(11, 16)}`
                : undefined
            }
          />
          <SummaryCell
            label="Mix"
            value={`${aggregate.sideMix.pay} PAY / ${aggregate.sideMix.rcv} RCV`}
            sub={
              Object.entries(aggregate.venueMix)
                .map(([v, n]) => `${v}: ${n}`)
                .join(' · ') || undefined
            }
          />
        </div>
      </div>

      {/* Timeline strip. */}
      <SequenceTimeline sequence={sequence} />

      {/* Inter-trade gaps table. */}
      <InterTradeGaps sequence={sequence} />

      {/* Chain detection. */}
      <SequenceChainDetector sequence={sequence} rows={rows} />

      {/* Lifecycle context strip — compact per-trade lifecycle summary. */}
      <div
        data-testid="lifecycle-context-strip"
        className="flex flex-col gap-1 rounded border border-slate-800 bg-slate-950/40 p-2"
      >
        <span className="font-mono text-[10px] uppercase tracking-wider text-slate-500">
          Lifecycle context
        </span>
        <div className="flex flex-wrap gap-1 font-mono text-[10px] text-slate-300">
          {sequence.map((trade, i) => {
            const colour = sequenceColor(i)
            return (
              <span
                key={`lc-strip-${trade.id}`}
                className="inline-flex items-center gap-1 rounded border border-slate-700 bg-slate-900/40 px-1.5 py-[1px]"
                title={`${trade.tape_label} — ${trade.lifecycle_type ?? 'lifecycle: ?'}`}
              >
                <span
                  className="inline-block h-[6px] w-[6px] rounded-full"
                  style={{ backgroundColor: colour }}
                />
                <span className="truncate max-w-[120px]">{trade.tape_label}</span>
                <span className="text-slate-500">·</span>
                <span className="text-slate-200">{trade.lifecycle_type ?? '—'}</span>
                <span className="text-slate-500">·</span>
                <span className="text-slate-400">{trade.trade_type}</span>
              </span>
            )
          })}
        </div>
      </div>

      {/*
        Allocation chain stub. The dashboard schema today does not
        project `prior_uti` onto UsdSwapTapeRow, so this surface
        renders an empty state acknowledging the placeholder. The
        plan accepts this as v1; the field upgrade is scheduled in
        the v2 schema follow-up.
      */}
      <div
        data-testid="allocation-chain-stub"
        className="rounded border border-dashed border-slate-800 bg-slate-950/40 px-3 py-3 font-mono text-[11px] text-slate-500"
      >
        Allocation chain · waiting on prior_uti projection from the v2 row
        schema. When the column lands, this surface will list per-trade
        allocation links.
      </div>
    </div>
  )
}
