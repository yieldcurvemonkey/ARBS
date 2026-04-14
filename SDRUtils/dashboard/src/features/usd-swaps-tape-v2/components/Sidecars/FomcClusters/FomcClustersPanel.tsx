'use client'
// ABOUTME: FOMC meeting rollup cards; click filters main table by fomcMeeting.
import type { JSX } from 'react'
import { useFomcClusters } from '../../../hooks/useFomcClusters'
import { formatDv01, formatNotional } from '../../../utils/format'

export interface FomcClustersPanelProps {
  date: string
  onSelect?: (fomcMeetingLabel: string) => void
}

export function FomcClustersPanel(props: FomcClustersPanelProps): JSX.Element {
  const { data, isLoading, error } = useFomcClusters({ date: props.date })
  const meetings = data?.meetings ?? []
  return (
    <div className="flex flex-col gap-2 p-3">
      {error ? <p className="text-red-300 text-sm">{error.message}</p> : null}
      {isLoading ? <p className="text-slate-400 text-sm">Loading…</p> : null}
      {!isLoading && meetings.length === 0 ? (
        <p className="text-slate-500 text-sm">No FOMC-dated trades today.</p>
      ) : null}
      <div className="grid grid-cols-2 gap-2">
        {meetings.map((m) => (
          <button
            key={m.fomc_meeting_label}
            type="button"
            onClick={() => props.onSelect?.(m.fomc_meeting_label)}
            className="text-left rounded bg-amber-950/20 border border-amber-700/20 hover:bg-amber-900/30 p-2"
          >
            <div className="flex items-center justify-between">
              <span className="font-mono text-sm text-amber-200">{m.fomc_meeting_label}</span>
              {m.has_multi_meeting_flow ? (
                <span className="px-1 py-0.5 text-[10px] rounded bg-amber-900/60 text-amber-100">
                  multi
                </span>
              ) : null}
            </div>
            <div className="text-xs text-slate-300 mt-1">{m.trade_count} trades</div>
            <div className="text-xs text-slate-300">
              Net {formatDv01(m.net_risk, { signed: true })} · Gross{' '}
              {formatNotional(m.gross_notional, { compact: true })}
            </div>
          </button>
        ))}
      </div>
    </div>
  )
}
