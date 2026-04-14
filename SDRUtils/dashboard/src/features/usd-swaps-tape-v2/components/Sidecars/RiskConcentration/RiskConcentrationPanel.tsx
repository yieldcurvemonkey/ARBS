'use client'
// ABOUTME: Risk concentration sidecar — horizontal divergent bar list.
import type { JSX } from 'react'
import { useState } from 'react'
import { useRiskConcentration } from '../../../hooks/useRiskConcentration'
import { formatDv01 } from '../../../utils/format'
import type { RiskConcentrationGroup } from '../../../types'

const GROUP_BY_OPTIONS = [
  { key: 'tape_label', label: 'Tape label' },
  { key: 'trade_type', label: 'Trade type' },
  { key: 'venue', label: 'Venue' },
  { key: 'ccp', label: 'CCP' },
  { key: 'session', label: 'Session' },
  { key: 'tenor', label: 'Tenor' },
  { key: 'rate_index', label: 'Rate index' },
  { key: 'fomc_meeting', label: 'FOMC meeting' },
] as const

export interface RiskConcentrationPanelProps {
  date: string
  clean?: boolean
  onSelect?: (groupBy: string, value: string) => void
}

export function RiskConcentrationPanel(
  props: RiskConcentrationPanelProps,
): JSX.Element {
  const [groupBy, setGroupBy] = useState<(typeof GROUP_BY_OPTIONS)[number]['key']>(
    'tape_label',
  )
  const { data, isLoading, error } = useRiskConcentration({
    date: props.date,
    groupBy,
    clean: props.clean,
  })
  const groups: RiskConcentrationGroup[] = data?.groups ?? []
  const maxAbs = Math.max(1, ...groups.map((g) => Math.abs(Number(g.total_dv01 ?? 0))))

  return (
    <div className="flex flex-col gap-2 p-3">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-[10px] uppercase text-slate-400">Group by</span>
        {GROUP_BY_OPTIONS.map((o) => (
          <button
            key={o.key}
            type="button"
            aria-pressed={groupBy === o.key}
            onClick={() => setGroupBy(o.key)}
            className={`px-2 py-0.5 rounded text-[11px] ${
              groupBy === o.key
                ? 'bg-sky-900/50 text-sky-100'
                : 'bg-slate-800/60 text-slate-400 hover:text-slate-200'
            }`}
          >
            {o.label}
          </button>
        ))}
      </div>
      {error ? <p className="text-red-300 text-sm">{error.message}</p> : null}
      {isLoading ? <p className="text-slate-400 text-sm">Loading…</p> : null}
      {!isLoading && groups.length === 0 ? (
        <p className="text-slate-500 text-sm">No data.</p>
      ) : null}
      <div className="flex flex-col gap-0.5">
        {groups.map((g) => {
          const dv = Number(g.total_dv01 ?? 0)
          const pct = (Math.abs(dv) / maxAbs) * 100
          const tone = dv >= 0 ? 'bg-emerald-700/60' : 'bg-red-700/60'
          return (
            <button
              key={g.value}
              type="button"
              onClick={() => props.onSelect?.(groupBy, g.value)}
              className="flex items-center gap-2 text-left hover:bg-slate-800/40 px-1 py-0.5 rounded"
            >
              <span className="w-36 truncate text-xs text-slate-200">{g.value}</span>
              <div className="flex-1 h-2 bg-slate-900 relative rounded overflow-hidden">
                <div className={`h-full ${tone}`} style={{ width: `${pct}%` }} />
              </div>
              <span className="w-20 text-right text-[11px] font-mono text-slate-200">
                {formatDv01(dv, { signed: true })}
              </span>
            </button>
          )
        })}
      </div>
    </div>
  )
}
