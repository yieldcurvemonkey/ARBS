'use client'
// ABOUTME: Horizontal time-axis marker strip showing one marker
// per trade in the sequence. Marker shape encodes side (▲ PAY / ▼
// RCV); marker size encodes DV01 magnitude; marker colour follows
// the sequence palette index. Trades without an execution_start
// render off to the side as a 'missing-ts' chip rather than
// disrupting the time scale.
import type { JSX } from 'react'
import { useMemo } from 'react'
import { sequenceColor } from './analytics-format'
import type { FocusedTrade } from './analytics-types'

export interface SequenceTimelineProps {
  sequence: readonly FocusedTrade[]
  height?: number
}

function tsMs(ts: string | null | undefined): number | null {
  if (!ts) return null
  const ms = Date.parse(ts)
  return Number.isFinite(ms) ? ms : null
}

export function SequenceTimeline({
  sequence,
  height = 90,
}: SequenceTimelineProps): JSX.Element {
  // Sort by execution_start ascending so the markers read left-to-
  // right in time order. Trades without a timestamp aren't placed
  // on the axis; we surface them as a small 'missing-ts' badge at
  // the right edge so the trader still sees them.
  const { sorted, missingTs, minMs, maxMs } = useMemo(() => {
    const withTs: { trade: FocusedTrade; ms: number }[] = []
    const missing: FocusedTrade[] = []
    for (const t of sequence) {
      const ms = tsMs(t.execution_start)
      if (ms == null) {
        missing.push(t)
      } else {
        withTs.push({ trade: t, ms })
      }
    }
    withTs.sort((a, b) => a.ms - b.ms)
    let lo = Number.POSITIVE_INFINITY
    let hi = Number.NEGATIVE_INFINITY
    for (const { ms } of withTs) {
      if (ms < lo) lo = ms
      if (ms > hi) hi = ms
    }
    return {
      sorted: withTs,
      missingTs: missing,
      minMs: lo === Number.POSITIVE_INFINITY ? null : lo,
      maxMs: hi === Number.NEGATIVE_INFINITY ? null : hi,
    }
  }, [sequence])

  if (sequence.length === 0) {
    return (
      <div
        data-testid="sequence-timeline-empty"
        className="rounded border border-dashed border-slate-800 bg-slate-950/40 px-3 py-4 text-center font-mono text-[11px] text-slate-500"
      >
        No trades selected — pick rows in the table above to see them on a timeline.
      </div>
    )
  }

  const span = minMs != null && maxMs != null && maxMs > minMs ? maxMs - minMs : 1

  // DV01-based marker size scaling — find the max DV01 and clamp
  // each marker between 8px and 20px so a tiny tail trade doesn't
  // collapse to invisibility.
  const maxDv01 = sequence.reduce(
    (acc, t) => Math.max(acc, Math.abs(t.dv01_usd_per_bp ?? 0)),
    1,
  )

  function markerSize(dv01: number): number {
    const r = Math.abs(dv01) / maxDv01
    return Math.max(8, Math.min(20, 8 + r * 12))
  }

  return (
    <div
      data-testid="sequence-timeline"
      className="relative rounded border border-slate-800 bg-slate-950/40 px-3 pb-2 pt-3"
      style={{ minHeight: height }}
    >
      <div className="mb-2 flex items-center justify-between font-mono text-[10px] uppercase tracking-wider text-slate-500">
        <span>Timeline · {sorted.length} trade{sorted.length === 1 ? '' : 's'}</span>
        {missingTs.length > 0 ? (
          <span className="text-amber-300">
            {missingTs.length} missing timestamp
          </span>
        ) : null}
      </div>
      <div className="relative h-[44px] rounded border border-slate-800 bg-slate-900/40">
        <div className="absolute inset-y-1/2 left-2 right-2 h-px bg-slate-800" />
        {sorted.map(({ trade, ms }, i) => {
          const pct = span > 0 ? ((ms - (minMs ?? ms)) / span) * 100 : 50
          const colour = sequenceColor(i)
          const size = markerSize(trade.dv01_usd_per_bp ?? 0)
          // Encode side as a CSS-rendered triangle so we don't need
          // SVG. PAY is upward (▲), RCV is downward (▼).
          const isPay = trade.side === 'PAY'
          return (
            <div
              key={`marker-${trade.id}`}
              data-testid={`sequence-marker-${trade.id}`}
              data-side={trade.side}
              data-venue={trade.venue}
              title={`${trade.side} ${trade.tape_label} @ ${trade.fixed_rate_bps.toFixed(1)} bps · ${trade.venue} · ${trade.execution_start ?? '?'}`}
              className="absolute -translate-x-1/2 -translate-y-1/2"
              style={{
                left: `calc(${pct}% + 8px)`,
                top: '50%',
                width: size,
                height: size,
                color: colour,
              }}
            >
              {isPay ? (
                <span style={{ display: 'inline-block', fontSize: size, lineHeight: 1, color: colour }}>
                  ▲
                </span>
              ) : (
                <span style={{ display: 'inline-block', fontSize: size, lineHeight: 1, color: colour }}>
                  ▼
                </span>
              )}
            </div>
          )
        })}
      </div>
      {missingTs.length > 0 ? (
        <div className="mt-2 flex flex-wrap gap-1 font-mono text-[10px] text-slate-400">
          {missingTs.map((trade) => (
            <span
              key={`missing-${trade.id}`}
              data-testid={`sequence-marker-${trade.id}`}
              data-missing-ts="true"
              className="rounded border border-amber-500/30 bg-amber-500/10 px-1.5 py-[1px] text-amber-200"
            >
              {trade.tape_label} (no ts)
            </span>
          ))}
        </div>
      ) : null}
    </div>
  )
}
