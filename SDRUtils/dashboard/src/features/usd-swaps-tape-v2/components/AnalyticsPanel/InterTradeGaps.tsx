'use client'
// ABOUTME: Sub-component of SequenceTab — renders a small table of
// consecutive Δt + Δrate gaps between selected trades. Trades are
// sorted by execution_start ascending before pairing so the table
// reads chronologically. Trades without an execution_start are
// silently dropped from the gap computation (the SequenceTimeline
// surfaces them via a missing-ts chip).
import type { JSX } from 'react'
import { useMemo } from 'react'
import type { FocusedTrade } from './analytics-types'

export interface InterTradeGap {
  fromId: string
  toId: string
  deltaMs: number
  deltaRateBps: number
}

function tsMs(ts: string | null | undefined): number | null {
  if (!ts) return null
  const ms = Date.parse(ts)
  return Number.isFinite(ms) ? ms : null
}

export function computeInterTradeGaps(
  sequence: readonly FocusedTrade[],
): InterTradeGap[] {
  const withTs = sequence
    .map((t) => ({ trade: t, ms: tsMs(t.execution_start) }))
    .filter((x): x is { trade: FocusedTrade; ms: number } => x.ms != null)
    .sort((a, b) => a.ms - b.ms)

  if (withTs.length < 2) return []
  const gaps: InterTradeGap[] = []
  for (let i = 1; i < withTs.length; i += 1) {
    const prev = withTs[i - 1]
    const curr = withTs[i]
    gaps.push({
      fromId: prev.trade.id,
      toId: curr.trade.id,
      deltaMs: curr.ms - prev.ms,
      deltaRateBps: curr.trade.fixed_rate_bps - prev.trade.fixed_rate_bps,
    })
  }
  return gaps
}

function formatMs(ms: number): string {
  if (ms < 1000) return `${ms}ms`
  if (ms < 60_000) return `${(ms / 1000).toFixed(0)}s`
  if (ms < 3_600_000) return `${(ms / 60_000).toFixed(1)}m`
  return `${(ms / 3_600_000).toFixed(2)}h`
}

export interface InterTradeGapsProps {
  sequence: readonly FocusedTrade[]
}

export function InterTradeGaps({ sequence }: InterTradeGapsProps): JSX.Element {
  const gaps = useMemo(() => computeInterTradeGaps(sequence), [sequence])

  if (gaps.length === 0) {
    return (
      <div
        data-testid="inter-trade-gaps-empty"
        className="rounded border border-dashed border-slate-800 bg-slate-950/40 px-3 py-3 font-mono text-[11px] text-slate-500"
      >
        No gaps yet — need at least 2 trades with timestamps.
      </div>
    )
  }

  return (
    <div
      data-testid="inter-trade-gaps"
      className="overflow-x-auto rounded border border-slate-800 bg-slate-950/40"
    >
      <table className="min-w-full border-collapse font-mono text-[11px] text-slate-200">
        <thead className="bg-slate-900/40 text-[10px] uppercase tracking-wider text-slate-500">
          <tr>
            <th className="px-2 py-1 text-left">From</th>
            <th className="px-2 py-1 text-left">To</th>
            <th className="px-2 py-1 text-right">Δt</th>
            <th className="px-2 py-1 text-right">Δrate (bps)</th>
          </tr>
        </thead>
        <tbody>
          {gaps.map((gap) => (
            <tr key={`${gap.fromId}-${gap.toId}`}>
              <td className="px-2 py-1 truncate max-w-[180px]">{gap.fromId}</td>
              <td className="px-2 py-1 truncate max-w-[180px]">{gap.toId}</td>
              <td className="px-2 py-1 text-right tabular-nums">{formatMs(gap.deltaMs)}</td>
              <td
                className={`px-2 py-1 text-right tabular-nums ${
                  gap.deltaRateBps > 0 ? 'text-rose-200' : gap.deltaRateBps < 0 ? 'text-emerald-200' : 'text-slate-300'
                }`}
              >
                {gap.deltaRateBps > 0 ? '+' : ''}
                {gap.deltaRateBps.toFixed(2)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
