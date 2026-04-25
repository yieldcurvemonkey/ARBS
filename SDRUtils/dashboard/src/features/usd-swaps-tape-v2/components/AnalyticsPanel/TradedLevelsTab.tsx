'use client'
// Tab 3 — Database of Traded Levels. All-time / 52w / 30d extremes for
// the focused bucket. Row click seeks the Timeseries tab to that print.
import type { JSX } from 'react'
import {
  fmtCompactUSD,
  fmtDaysAgo,
  fmtDv01Compact,
  fmtNotionalMM,
  fmtTs,
} from './analytics-format'
import { PlatformDot } from './controls'
import { AssumptionsStrip } from './AssumptionsStrip'
import type {
  ExtremeRow,
  ExtremeScope,
  FocusedTrade,
  RecentSimilarRow,
} from './analytics-types'

function extremeGroupColor(scope: ExtremeScope): string {
  if (scope === 'All-time') return 'text-indigo-300'
  if (scope === '52 weeks') return 'text-sky-300'
  return 'text-emerald-300'
}

export interface TradedLevelsTabProps {
  focused: FocusedTrade
  extremes: ExtremeRow[]
  recentSimilar: RecentSimilarRow[]
  onSeek?: (extreme: ExtremeRow) => void
}

export function TradedLevelsTab(props: TradedLevelsTabProps): JSX.Element {
  const { focused, extremes, recentSimilar, onSeek } = props
  const focusedRate = focused.fixed_rate_bps

  const deltaRate = (r: number): string => {
    const d = r - focusedRate
    const sign = d > 0 ? '+' : d < 0 ? '−' : ''
    return `${sign}${Math.abs(d).toFixed(1)}`
  }

  return (
    <div className="flex flex-col gap-2.5">
      <AssumptionsStrip
        items={[
          { label: 'Bucket', value: focused.tape_label },
          { label: 'Rate units', value: 'bps', dim: true },
          { label: 'DV01 units', value: 'USD/bp', dim: true },
          { label: 'Notional units', value: 'USD mm', dim: true },
          { label: 'Scopes', value: 'all-time · 52w · 30d' },
          {
            label: 'Focused trade',
            value: `${focusedRate.toFixed(1)} bps · ${fmtDv01Compact(focused.dv01_usd_per_bp)} DV01 · ${fmtNotionalMM(focused.notional_usd)} MM`,
          },
        ]}
        source="/api/usd-swaps-tape-v2/extremes"
      />

      <div className="rounded border border-slate-800 bg-slate-950/60">
        <div className="grid grid-cols-[220px_72px_120px_100px_140px_180px_130px_100px_60px] items-center gap-2 border-b border-slate-800 bg-slate-900/40 px-2.5 py-1.5 font-mono text-[9.5px] uppercase tracking-wider text-slate-500">
          <div>Extreme</div>
          <div>Scope</div>
          <div className="text-right">
            Rate<span className="text-slate-600"> (bps)</span>
          </div>
          <div className="text-right">
            Δ vs focus<span className="text-slate-600"> (bps)</span>
          </div>
          <div className="text-right">
            DV01<span className="text-slate-600"> (USD/bp)</span>
          </div>
          <div className="text-right">
            Notional<span className="text-slate-600"> (USD)</span>
          </div>
          <div>
            When <span className="text-slate-600">(NY)</span>
          </div>
          <div>Venue</div>
          <div>Platform</div>
        </div>

        {extremes.length === 0 ? (
          <div className="px-3 py-4 text-center font-mono text-[10.5px] text-slate-500">
            No prints yet for this bucket — the rarity / extremes engine
            needs at least one settled trade in the lookback to populate
            this list. Pin the trade and check back after the next
            ingest run.
          </div>
        ) : null}
        {extremes.map((r) => {
          const isHigh = r.label.includes('high')
          const isLow = r.label.includes('low')
          const isSize = r.label.includes('largest')
          const bullet = isHigh ? '▲' : isLow ? '▼' : isSize ? '◈' : '—'
          const bulletColor = isHigh ? 'text-rose-400' : isLow ? 'text-emerald-400' : 'text-indigo-300'
          const delta = r.rate - focusedRate
          return (
            <button
              key={r.label}
              type="button"
              onClick={() => onSeek?.(r)}
              className="grid w-full grid-cols-[220px_72px_120px_100px_140px_180px_130px_100px_60px] items-center gap-2 border-b border-slate-800/60 px-2.5 py-[7px] text-left font-mono text-[11px] transition-colors hover:bg-slate-800/40"
            >
              <div className="flex items-center gap-2">
                <span className={`text-[13px] ${bulletColor}`}>{bullet}</span>
                <span className="text-slate-200">{r.label}</span>
              </div>
              <div className={`text-[10px] ${extremeGroupColor(r.scope)}`}>{r.scope}</div>
              <div className="text-right text-slate-100 tabular-nums">{r.rate.toFixed(1)}</div>
              <div
                className={`text-right tabular-nums ${
                  delta > 0 ? 'text-rose-300' : delta < 0 ? 'text-emerald-300' : 'text-slate-400'
                }`}
              >
                {deltaRate(r.rate)}
              </div>
              <div className="text-right text-slate-200 tabular-nums">{fmtDv01Compact(r.dv01)}</div>
              <div className="text-right text-slate-200 tabular-nums">{fmtCompactUSD(r.notional)}</div>
              <div className="text-slate-300">{fmtTs(r.ts)}</div>
              <div className="text-slate-300">{r.venue}</div>
              <div className="flex items-center gap-1.5">
                <PlatformDot platform={r.platform} size={6} />
                <span className={r.platform === 'CUSTY' ? 'text-amber-200' : 'text-sky-200'}>
                  {r.platform}
                </span>
              </div>
            </button>
          )
        })}
      </div>

      <div className="rounded border border-slate-800 bg-slate-900/40 px-3 py-2 font-mono text-[10.5px] text-slate-400">
        <span className="text-[9.5px] uppercase tracking-wider text-slate-500">Why this tab exists</span>
        <div className="mt-1 italic text-slate-300">
          “What was the all-time low print of 10y10y? What was the all-time high print of 1m10y? That kind of thing — what and when.”
        </div>
        <div className="mt-1 text-slate-500">
          Click any row to seek the Timeseries tab to that print and pulse the reference dot.
        </div>
      </div>

      <div className="rounded border border-slate-800 bg-slate-950/60">
        <div className="flex items-center justify-between border-b border-slate-800 bg-slate-900/40 px-2.5 py-1.5">
          <span className="font-mono text-[10px] uppercase tracking-wider text-slate-500">
            Recent similar trades · within ±2 bps, ±25% size
          </span>
          <span className="font-mono text-[10px] text-slate-500">
            {recentSimilar.length} shown
          </span>
        </div>
        <div className="grid grid-cols-[80px_100px_120px_140px_180px_100px_1fr] items-center gap-2 border-b border-slate-800 bg-slate-900/20 px-2.5 py-1 font-mono text-[9.5px] uppercase tracking-wider text-slate-500">
          <div>Days ago</div>
          <div>Date</div>
          <div className="text-right">Rate (bps)</div>
          <div className="text-right">DV01 (USD/bp)</div>
          <div className="text-right">Notional (USD)</div>
          <div>Platform</div>
          <div>Venue</div>
        </div>
        {recentSimilar.map((r, i) => (
          <div
            key={`${r.date}-${r.rate}-${r.platform}-${i}`}
            className="grid grid-cols-[80px_100px_120px_140px_180px_100px_1fr] items-center gap-2 border-b border-slate-800/60 px-2.5 py-[6px] font-mono text-[11px]"
          >
            <div className="text-slate-300">{fmtDaysAgo(r.daysAgo)}</div>
            <div className="text-slate-400">{r.date}</div>
            <div className="text-right text-slate-100 tabular-nums">{r.rate.toFixed(2)}</div>
            <div className="text-right text-slate-200 tabular-nums">{fmtDv01Compact(r.dv01)}</div>
            <div className="text-right text-slate-200 tabular-nums">{fmtCompactUSD(r.notional)}</div>
            <div className="flex items-center gap-1.5">
              <PlatformDot platform={r.platform} size={6} />
              <span className={r.platform === 'CUSTY' ? 'text-amber-200' : 'text-sky-200'}>
                {r.platform}
              </span>
            </div>
            <div className="text-slate-400">{r.venue}</div>
          </div>
        ))}
      </div>
    </div>
  )
}
