'use client'
// Tab 3 — Database of Traded Levels. All-time / 52w / 30d extremes for
// the focused bucket. Row click seeks the Timeseries tab to that print.
import type { JSX } from 'react'
import { useEffect, useMemo, useState } from 'react'
import {
  fmtCompactUSD,
  fmtDaysAgo,
  fmtDv01Compact,
  fmtNotionalMM,
  fmtTs,
  sequenceColor,
} from './analytics-format'
import { NumberInput, PlatformDot, Pill, SegGroup } from './controls'
import { AssumptionsStrip } from './AssumptionsStrip'
import {
  filterAndSortExtremes,
  filterAndSortRecentSimilar,
  formatSignedBpsDelta,
  parsePositiveNumberInput,
  summarizeRecentLevels,
} from './TradedLevelsTab.helpers'
import type {
  DistributionStats,
  ExtremeRow,
  ExtremeScope,
  FocusedTrade,
  LevelsRecentSortKey,
  LevelsScopeFilter,
  LevelsSortKey,
  LevelsState,
  RecentSimilarRow,
} from './analytics-types'
import type { Dispatch, SetStateAction } from 'react'

function extremeGroupColor(scope: ExtremeScope): string {
  if (scope === 'All-time') return 'text-indigo-300'
  if (scope === '52 weeks') return 'text-sky-300'
  return 'text-emerald-300'
}

const SCOPE_OPTIONS: Array<{ key: LevelsScopeFilter; label: string }> = [
  { key: 'all', label: 'All' },
  { key: '30d', label: '30D' },
  { key: '52w', label: '52W' },
  { key: 'all-time', label: 'All-time' },
]

const EXTREME_SORT_OPTIONS: Array<{ key: LevelsSortKey; label: string }> = [
  { key: 'relevance', label: 'Desk' },
  { key: 'closest', label: 'Closest' },
  { key: 'time', label: 'Newest' },
  { key: 'dv01', label: 'DV01' },
  { key: 'notional', label: 'Notional' },
  { key: 'rate', label: 'Rate' },
]

const RECENT_SORT_OPTIONS: Array<{ key: LevelsRecentSortKey; label: string }> = [
  { key: 'newest', label: 'Newest' },
  { key: 'closest', label: 'Closest' },
  { key: 'largest', label: 'Largest' },
]

function LevelSummaryCard(props: {
  label: string
  value: string
  sub?: string
  accent?: 'sky' | 'amber' | 'emerald' | 'fuchsia'
}): JSX.Element {
  const accent =
    props.accent === 'amber' ? 'border-l-amber-500/60'
    : props.accent === 'emerald' ? 'border-l-emerald-500/60'
    : props.accent === 'fuchsia' ? 'border-l-fuchsia-500/60'
    : 'border-l-sky-500/60'
  return (
    <div className={`rounded border border-slate-800 border-l-[3px] ${accent} bg-slate-950/60 px-2.5 py-2 font-mono`}>
      <div className="text-[9.5px] uppercase tracking-wider text-slate-500">{props.label}</div>
      <div className="mt-0.5 text-[15px] text-slate-100 tabular-nums">{props.value}</div>
      {props.sub ? <div className="mt-0.5 text-[10px] text-slate-500">{props.sub}</div> : null}
    </div>
  )
}

export interface TradedLevelsTabProps {
  focused: FocusedTrade
  // Multi-trade dock — supplied in sequence mode. Phase F3 wires
  // the side-by-side / aggregated toggle against this list. Single-
  // mode rendering is byte-for-byte unchanged when sequence is
  // undefined.
  sequence?: readonly FocusedTrade[]
  state: LevelsState
  setState: Dispatch<SetStateAction<LevelsState>>
  extremes: ExtremeRow[]
  recentSimilar: RecentSimilarRow[]
  stats: DistributionStats
  focusedPercentile: number
  onSeek?: (extreme: ExtremeRow) => void
}

const LEVELS_VIEW_STORAGE_KEY = 'levels-multi-view'

type LevelsMultiView = 'side-by-side' | 'aggregated'

export function TradedLevelsTab(props: TradedLevelsTabProps): JSX.Element {
  const { focused, sequence, state, setState, extremes, recentSimilar, stats, focusedPercentile, onSeek } = props
  const overlayTrades = sequence ?? []
  const isSequenceMode = overlayTrades.length > 0

  // Multi-trade dock — toggle between side-by-side N-column and an
  // aggregated extremes view scoped to the union of all selected
  // rates. Default is side-by-side. State persists to localStorage
  // under LEVELS_VIEW_STORAGE_KEY so the trader's preference
  // survives reload. SSR-safe: server render starts at 'side-by-
  // side' and useEffect rehydrates from storage post-mount.
  const [multiView, setMultiView] = useState<LevelsMultiView>('side-by-side')
  useEffect(() => {
    if (typeof localStorage === 'undefined') return
    try {
      const raw = localStorage.getItem(LEVELS_VIEW_STORAGE_KEY)
      if (raw === 'aggregated' || raw === 'side-by-side') {
        setMultiView(raw)
      }
    } catch {
      /* ignore corrupt storage payload */
    }
  }, [])
  useEffect(() => {
    if (typeof localStorage === 'undefined') return
    try {
      localStorage.setItem(LEVELS_VIEW_STORAGE_KEY, multiView)
    } catch {
      /* quota or private mode — fall back to in-memory */
    }
  }, [multiView])

  const focusedRate = focused.fixed_rate_bps
  const primaryTol = parsePositiveNumberInput(state.primaryTol, 2)
  const sizeTolPct = parsePositiveNumberInput(state.sizeTolPct, 25)
  const filteredExtremes = useMemo(
    () => filterAndSortExtremes(extremes, {
      platform: state.platform,
      scope: state.scope,
      sortBy: state.sortBy,
      focusedRate,
    }),
    [extremes, focusedRate, state.platform, state.scope, state.sortBy],
  )
  const filteredRecent = useMemo(
    () => filterAndSortRecentSimilar(recentSimilar, {
      platform: state.platform,
      sortBy: state.recentSortBy,
      focusedRate,
    }),
    [focusedRate, recentSimilar, state.platform, state.recentSortBy],
  )
  const recentSummary = useMemo(
    () => summarizeRecentLevels(filteredRecent, focusedRate),
    [filteredRecent, focusedRate],
  )
  const focusedZ =
    stats.stddev > 0 ? (focusedRate - stats.mean) / stats.stddev : null

  // Multi-mode aggregated extremes — union of rate / DV01 /
  // notional bounds across the selected trades. Used by the
  // 'aggregated' view variant.
  const sequenceAggregateBounds = useMemo(() => {
    if (!isSequenceMode) return null
    let minRate = Number.POSITIVE_INFINITY
    let maxRate = Number.NEGATIVE_INFINITY
    let minDv01 = Number.POSITIVE_INFINITY
    let maxDv01 = Number.NEGATIVE_INFINITY
    let minNotional = Number.POSITIVE_INFINITY
    let maxNotional = Number.NEGATIVE_INFINITY
    for (const t of overlayTrades) {
      if (Number.isFinite(t.fixed_rate_bps)) {
        if (t.fixed_rate_bps < minRate) minRate = t.fixed_rate_bps
        if (t.fixed_rate_bps > maxRate) maxRate = t.fixed_rate_bps
      }
      const dv01 = Math.abs(t.dv01_usd_per_bp ?? 0)
      if (Number.isFinite(dv01)) {
        if (dv01 < minDv01) minDv01 = dv01
        if (dv01 > maxDv01) maxDv01 = dv01
      }
      const notional = Math.abs(t.notional_usd ?? 0)
      if (Number.isFinite(notional)) {
        if (notional < minNotional) minNotional = notional
        if (notional > maxNotional) maxNotional = notional
      }
    }
    return {
      rate: {
        min: minRate === Number.POSITIVE_INFINITY ? null : minRate,
        max: maxRate === Number.NEGATIVE_INFINITY ? null : maxRate,
      },
      dv01: {
        min: minDv01 === Number.POSITIVE_INFINITY ? null : minDv01,
        max: maxDv01 === Number.NEGATIVE_INFINITY ? null : maxDv01,
      },
      notional: {
        min: minNotional === Number.POSITIVE_INFINITY ? null : minNotional,
        max: maxNotional === Number.NEGATIVE_INFINITY ? null : maxNotional,
      },
    }
  }, [isSequenceMode, overlayTrades])

  return (
    <div className="flex flex-col gap-2.5">
      {/*
        Multi-trade dock — view toggle (side-by-side / aggregated)
        sits above the existing controls. Single-mode renders no
        toggle so the legacy layout stays identical.
      */}
      {isSequenceMode ? (
        <div
          data-testid="levels-multi-toggle"
          className="flex items-center gap-2 rounded border border-slate-800 bg-slate-950/40 px-2 py-1"
        >
          <span className="text-[10px] uppercase tracking-wider text-slate-500">
            Sequence view
          </span>
          <div className="flex gap-1">
            <button
              type="button"
              onClick={() => setMultiView('side-by-side')}
              className={`rounded border px-1.5 py-0.5 font-mono text-[10px] ${
                multiView === 'side-by-side'
                  ? 'border-indigo-400 bg-indigo-500/20 text-indigo-200'
                  : 'border-slate-700 bg-transparent text-slate-400 hover:border-slate-500'
              }`}
            >
              Side-by-side
            </button>
            <button
              type="button"
              onClick={() => setMultiView('aggregated')}
              className={`rounded border px-1.5 py-0.5 font-mono text-[10px] ${
                multiView === 'aggregated'
                  ? 'border-indigo-400 bg-indigo-500/20 text-indigo-200'
                  : 'border-slate-700 bg-transparent text-slate-400 hover:border-slate-500'
              }`}
            >
              Aggregated
            </button>
          </div>
          <span className="ml-auto text-[10px] text-slate-500">
            {overlayTrades.length} trades
          </span>
        </div>
      ) : null}

      {isSequenceMode && multiView === 'side-by-side' ? (
        <div
          data-testid="levels-side-by-side"
          className="overflow-x-auto rounded border border-slate-800"
        >
          <table className="min-w-full border-collapse font-mono text-[11px] text-slate-200">
            <thead>
              <tr className="bg-slate-900/40">
                <th className="sticky left-0 bg-slate-900/40 px-2 py-1 text-left text-[10px] uppercase tracking-wider text-slate-500">
                  Field
                </th>
                {overlayTrades.map((trade, i) => (
                  <th
                    key={`hdr-${trade.id}`}
                    className="px-2 py-1 text-left text-[10px] uppercase tracking-wider text-slate-300"
                  >
                    <span
                      className="inline-block h-[6px] w-[6px] rounded-full"
                      style={{ backgroundColor: sequenceColor(i) }}
                    />{' '}
                    {trade.tape_label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              <tr>
                <td className="sticky left-0 bg-slate-950 px-2 py-1 text-slate-500">Rate (bps)</td>
                {overlayTrades.map((trade) => (
                  <td key={`rate-${trade.id}`} className="px-2 py-1 tabular-nums">
                    {trade.fixed_rate_bps.toFixed(2)}
                  </td>
                ))}
              </tr>
              <tr>
                <td className="sticky left-0 bg-slate-950 px-2 py-1 text-slate-500">DV01</td>
                {overlayTrades.map((trade) => (
                  <td key={`dv01-${trade.id}`} className="px-2 py-1 tabular-nums">
                    {fmtDv01Compact(trade.dv01_usd_per_bp)}
                  </td>
                ))}
              </tr>
              <tr>
                <td className="sticky left-0 bg-slate-950 px-2 py-1 text-slate-500">Notional</td>
                {overlayTrades.map((trade) => (
                  <td key={`notional-${trade.id}`} className="px-2 py-1 tabular-nums">
                    {fmtNotionalMM(trade.notional_usd)}
                  </td>
                ))}
              </tr>
              <tr>
                <td className="sticky left-0 bg-slate-950 px-2 py-1 text-slate-500">Side</td>
                {overlayTrades.map((trade) => (
                  <td key={`side-${trade.id}`} className="px-2 py-1">
                    {trade.side}
                  </td>
                ))}
              </tr>
              <tr>
                <td className="sticky left-0 bg-slate-950 px-2 py-1 text-slate-500">Venue</td>
                {overlayTrades.map((trade) => (
                  <td key={`venue-${trade.id}`} className="px-2 py-1">
                    {trade.venue}
                  </td>
                ))}
              </tr>
              <tr>
                <td className="sticky left-0 bg-slate-950 px-2 py-1 text-slate-500">Time</td>
                {overlayTrades.map((trade) => (
                  <td key={`time-${trade.id}`} className="px-2 py-1">
                    {trade.execution_start ? fmtTs(trade.execution_start) : '—'}
                  </td>
                ))}
              </tr>
            </tbody>
          </table>
        </div>
      ) : null}

      {isSequenceMode && multiView === 'aggregated' && sequenceAggregateBounds ? (
        <div
          data-testid="levels-aggregated"
          className="grid grid-cols-2 gap-2 rounded border border-slate-800 p-2 lg:grid-cols-3"
        >
          <div className="rounded border border-slate-800 bg-slate-950/60 p-2 font-mono text-[11px] text-slate-200">
            <div className="text-[10px] uppercase tracking-wider text-slate-500">Rate range (bps)</div>
            <div className="mt-1 tabular-nums">
              {sequenceAggregateBounds.rate.min?.toFixed(2) ?? '—'} →{' '}
              {sequenceAggregateBounds.rate.max?.toFixed(2) ?? '—'}
            </div>
          </div>
          <div className="rounded border border-slate-800 bg-slate-950/60 p-2 font-mono text-[11px] text-slate-200">
            <div className="text-[10px] uppercase tracking-wider text-slate-500">DV01 range (USD/bp)</div>
            <div className="mt-1 tabular-nums">
              {sequenceAggregateBounds.dv01.min != null ? fmtDv01Compact(sequenceAggregateBounds.dv01.min) : '—'} →{' '}
              {sequenceAggregateBounds.dv01.max != null ? fmtDv01Compact(sequenceAggregateBounds.dv01.max) : '—'}
            </div>
          </div>
          <div className="rounded border border-slate-800 bg-slate-950/60 p-2 font-mono text-[11px] text-slate-200">
            <div className="text-[10px] uppercase tracking-wider text-slate-500">Notional range (USD MM)</div>
            <div className="mt-1 tabular-nums">
              {sequenceAggregateBounds.notional.min != null ? fmtNotionalMM(sequenceAggregateBounds.notional.min) : '—'} →{' '}
              {sequenceAggregateBounds.notional.max != null ? fmtNotionalMM(sequenceAggregateBounds.notional.max) : '—'}
            </div>
          </div>
        </div>
      ) : null}

      <div className="flex flex-wrap items-start gap-x-3 gap-y-2">
        <div className="flex flex-col gap-1">
          <div className="text-[10px] uppercase tracking-wide text-slate-500">Market</div>
          <div className="flex gap-1">
            <Pill active={state.platform === 'all'} onClick={() => setState((s) => ({ ...s, platform: 'all' }))}>
              All
            </Pill>
            <Pill
              active={state.platform === 'custy'}
              onClick={() => setState((s) => ({ ...s, platform: 'custy' }))}
              accent="amber"
            >
              <PlatformDot platform="CUSTY" size={6} />
              <span className="ml-1">Custy</span>
            </Pill>
            <Pill
              active={state.platform === 'idb'}
              onClick={() => setState((s) => ({ ...s, platform: 'idb' }))}
              accent="sky"
            >
              <PlatformDot platform="IDB" size={6} />
              <span className="ml-1">IDB</span>
            </Pill>
          </div>
        </div>

        <SegGroup<LevelsScopeFilter>
          label="Records"
          value={state.scope}
          onChange={(scope) => setState((s) => ({ ...s, scope }))}
          options={SCOPE_OPTIONS}
        />

        <SegGroup<LevelsSortKey>
          label="Sort"
          value={state.sortBy}
          onChange={(sortBy) => setState((s) => ({ ...s, sortBy }))}
          options={EXTREME_SORT_OPTIONS}
          accent="cyan"
        />

        <SegGroup<LevelsRecentSortKey>
          label="Similar prints"
          value={state.recentSortBy}
          onChange={(recentSortBy) => setState((s) => ({ ...s, recentSortBy }))}
          options={RECENT_SORT_OPTIONS}
        />

        <div className="ml-auto flex items-center gap-1.5 pt-5">
          <NumberInput
            label="Rate tol"
            value={state.primaryTol}
            onChange={(primaryTol) => setState((s) => ({ ...s, primaryTol }))}
            width={44}
          />
          <NumberInput
            label="Size tol %"
            value={state.sizeTolPct}
            onChange={(sizeTolPct) => setState((s) => ({ ...s, sizeTolPct }))}
            width={44}
          />
        </div>
      </div>

      <AssumptionsStrip
        items={[
          { label: 'Bucket', value: focused.tape_label },
          { label: 'Rate units', value: 'bps', dim: true },
          { label: 'DV01 units', value: 'USD/bp', dim: true },
          { label: 'Notional units', value: 'USD mm', dim: true },
          { label: 'Filter', value: state.platform === 'all' ? 'Custy + IDB' : state.platform.toUpperCase() },
          { label: 'Similarity', value: `+/-${primaryTol.toFixed(1)} bps / ${sizeTolPct.toFixed(0)}% size` },
          { label: 'Scopes', value: 'all-time · 52w · 30d' },
          {
            label: 'Focused trade',
            value: `${focusedRate.toFixed(1)} bps · ${fmtDv01Compact(focused.dv01_usd_per_bp)} DV01 · ${fmtNotionalMM(focused.notional_usd)} MM`,
          },
        ]}
        source="/api/usd-swaps-tape-v2/extremes"
      />

      <div className="grid grid-cols-4 gap-2">
        <LevelSummaryCard
          label="Recent VWAP"
          value={recentSummary.vwap == null ? '-' : `${recentSummary.vwap.toFixed(2)} bps`}
          sub={
            recentSummary.focusDelta == null
              ? 'No comparable prints shown'
              : `focus ${formatSignedBpsDelta(recentSummary.focusDelta)} bps vs sample`
          }
          accent="sky"
        />
        <LevelSummaryCard
          label="Comparable range"
          value={
            recentSummary.low == null || recentSummary.high == null
              ? '-'
              : `${recentSummary.low.toFixed(1)} / ${recentSummary.high.toFixed(1)}`
          }
          sub={`${recentSummary.count} shown within tolerance`}
          accent="emerald"
        />
        <LevelSummaryCard
          label="Risk traded"
          value={fmtDv01Compact(recentSummary.totalDv01)}
          sub={`${fmtCompactUSD(recentSummary.totalNotional)} notional in shown prints`}
          accent="amber"
        />
        <LevelSummaryCard
          label="90d rate context"
          value={focusedZ == null ? `P${Math.round(focusedPercentile)}` : `z ${focusedZ.toFixed(2)}`}
          sub={`P${Math.round(focusedPercentile)} rate percentile / ${focused.is_block ? 'block print' : 'standard print'}`}
          accent="fuchsia"
        />
      </div>

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

        {filteredExtremes.length === 0 ? (
          <div className="px-3 py-4 text-center font-mono text-[10.5px] text-slate-500">
            No prints yet for this bucket — the rarity / extremes engine
            needs at least one settled trade in the lookback to populate
            this list. Pin the trade and check back after the next
            ingest run.
          </div>
        ) : null}
        {filteredExtremes.map((r) => {
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
                {formatSignedBpsDelta(delta)}
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

      <div className="rounded border border-slate-800 bg-slate-950/60">
        <div className="flex items-center justify-between border-b border-slate-800 bg-slate-900/40 px-2.5 py-1.5">
          <span className="font-mono text-[10px] uppercase tracking-wider text-slate-500">
            Recent comparable prints
          </span>
          <span className="font-mono text-[10px] text-slate-500">
            {filteredRecent.length} shown / {recentSimilar.length} fetched
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
        {filteredRecent.map((r, i) => (
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
