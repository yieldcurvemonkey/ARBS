'use client'
// ABOUTME: Expanded package detail panel — per-leg breakdown only.
import type { JSX } from 'react'
import { EMPTY_VALUE, LIFECYCLE_LABELS, LIFECYCLE_TONES } from '../../constants'
import type { UsdSwapTapeLeg, UsdSwapTapeRow } from '../../types'
import {
  formatDate,
  formatDv01,
  formatExecutionWindow,
  formatNotional,
  formatRate,
} from '../../utils/format'

function lifecycleBody(leg: UsdSwapTapeLeg) {
  const type = leg.lifecycle_type
  if (!type) return EMPTY_VALUE
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-semibold ${LIFECYCLE_TONES[type] ?? ''}`}
    >
      {LIFECYCLE_LABELS[type] ?? type}
    </span>
  )
}

function tradeIdBody(leg: UsdSwapTapeLeg) {
  const tid = leg.trade_id ?? EMPTY_VALUE
  return (
    <button
      type="button"
      className="font-mono text-[11px] text-slate-300 hover:text-slate-100"
      onClick={() => {
        try {
          navigator.clipboard?.writeText(String(tid))
        } catch {
          /* ignore */
        }
      }}
      aria-label={`copy trade id ${tid}`}
    >
      {tid}
    </button>
  )
}

function maturityDateOf(leg: UsdSwapTapeLeg): string | null | undefined {
  return leg.swap_maturity_date ?? leg.expiration_date
}

function crossDayProgress(leg: UsdSwapTapeLeg) {
  const pct = leg.xd_notional_pct_remaining
  if (pct === null || pct === undefined || pct >= 0.999) {
    return <span className="text-slate-500">{EMPTY_VALUE}</span>
  }
  const bounded = Math.max(0, Math.min(1, Number(pct)))
  return (
    <div className="flex items-center gap-2">
      <div
        className="h-1 w-16 overflow-hidden rounded bg-slate-800"
        aria-label="cross-day notional remaining"
      >
        <div className="h-full bg-emerald-500" style={{ width: `${bounded * 100}%` }} />
      </div>
      <span className="text-[10px] text-slate-400">{(bounded * 100).toFixed(0)}%</span>
    </div>
  )
}

function flagBadge(
  key: string,
  label: string,
  className: string,
  ariaLabel: string,
) {
  return { key, label, className, ariaLabel }
}

function legBadges(leg: UsdSwapTapeLeg) {
  const badges = []
  if (leg.is_ufro) {
    badges.push(
      flagBadge('ufro', 'UFRO', 'bg-orange-900/40 text-orange-200', 'ufro reported'),
    )
  }
  if (leg.is_off_market) {
    badges.push(
      flagBadge(
        'off-market',
        'OFF-MKT',
        'bg-yellow-900/40 text-yellow-200',
        'off-market trade',
      ),
    )
  }
  if (leg.is_block) {
    badges.push(
      flagBadge('block', 'BLK', 'bg-orange-900/40 text-orange-200', 'block trade'),
    )
  }
  if (leg.is_capped) {
    badges.push(
      flagBadge('capped', 'CAP', 'bg-rose-900/40 text-rose-200', 'notional capped'),
    )
  }
  if (leg.is_off_date) {
    badges.push(
      flagBadge('off-date', '~', 'bg-yellow-900/40 text-yellow-200', 'off-date'),
    )
  }
  if (leg.is_non_standard_term) {
    badges.push(
      flagBadge(
        'non-standard',
        'NSTD',
        'bg-purple-900/40 text-purple-200',
        'non-standard term',
      ),
    )
  }
  for (const value of leg.quality_flags ?? []) {
    badges.push(
      flagBadge(
        `quality-${value}`,
        value,
        'bg-zinc-800/60 text-zinc-300',
        `quality flag ${value}`,
      ),
    )
  }
  return badges
}

function qualityFlagsBody(leg: UsdSwapTapeLeg) {
  const flags = legBadges(leg)
  if (!flags.length) return <span className="text-slate-500">{EMPTY_VALUE}</span>
  return (
    <div className="flex flex-wrap gap-1">
      {flags.map((flag) => (
        <span
          key={flag.key}
          className={`rounded px-1 py-0.5 text-[10px] font-semibold ${flag.className}`}
          aria-label={flag.ariaLabel}
        >
          {flag.label}
        </span>
      ))}
    </div>
  )
}

export function LegsSubTable({ row }: { row: UsdSwapTapeRow }): JSX.Element {
  const legs = (row.legs_json ?? []) as UsdSwapTapeLeg[]

  return (
    <div
      className="rounded-xl border border-slate-800/80 bg-slate-950/70 px-4 py-3"
      data-testid={`legs-subtable-${row.package_id}`}
    >
      <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">
        Leg Details
      </div>
      <div className="mt-2 overflow-x-auto">
        <table className="min-w-full text-xs">
          <thead>
            <tr className="text-[10px] uppercase tracking-wide text-slate-400">
              <th className="px-2 py-1 text-left">#</th>
              <th className="px-2 py-1 text-left">Action</th>
              <th className="px-2 py-1 text-left">Time</th>
              <th className="px-2 py-1 text-left">Platform</th>
              <th className="px-2 py-1 text-left">Trade ID</th>
              <th className="px-2 py-1 text-left">Tape Label</th>
              <th className="px-2 py-1 text-left">Effective</th>
              <th className="px-2 py-1 text-left">Maturity</th>
              <th className="px-2 py-1 text-right">Notional</th>
              <th className="px-2 py-1 text-right">DV01</th>
              <th className="px-2 py-1 text-right">Rate</th>
              <th className="px-2 py-1 text-left">Flags</th>
              <th className="px-2 py-1 text-left">X-Day</th>
            </tr>
          </thead>
          <tbody>
            {legs.map((leg, index) => (
              <tr
                key={leg.trade_id ?? `${row.package_id}-${index}`}
                className="border-t border-slate-800/90 text-slate-200"
              >
                <td className="whitespace-nowrap px-2 py-1">{leg.leg_order ?? index + 1}</td>
                <td className="whitespace-nowrap px-2 py-1">{lifecycleBody(leg)}</td>
                <td className="whitespace-nowrap px-2 py-1">
                  {formatExecutionWindow(leg.execution_timestamp, leg.execution_timestamp)}
                </td>
                <td className="whitespace-nowrap px-2 py-1">
                  {leg.platform_identifier ?? EMPTY_VALUE}
                </td>
                <td className="whitespace-nowrap px-2 py-1">{tradeIdBody(leg)}</td>
                <td className="max-w-[360px] px-2 py-1 font-mono text-[11px] text-slate-100">
                  {leg.tape_label ?? EMPTY_VALUE}
                </td>
                <td className="whitespace-nowrap px-2 py-1">
                  {formatDate(leg.effective_date)}
                </td>
                <td className="whitespace-nowrap px-2 py-1">
                  {formatDate(maturityDateOf(leg))}
                </td>
                <td className="whitespace-nowrap px-2 py-1 text-right font-mono">
                  {formatNotional(leg.notional ?? null, { compact: true })}
                </td>
                <td className="whitespace-nowrap px-2 py-1 text-right font-mono">
                  {formatDv01(leg.risk ?? null, { signed: true })}
                </td>
                <td className="whitespace-nowrap px-2 py-1 text-right font-mono">
                  {formatRate(leg.fixed_rate ?? null)}
                </td>
                <td className="px-2 py-1">{qualityFlagsBody(leg)}</td>
                <td className="whitespace-nowrap px-2 py-1">{crossDayProgress(leg)}</td>
              </tr>
            ))}
            {legs.length === 0 ? (
              <tr className="border-t border-slate-800/90 text-slate-400">
                <td className="px-2 py-2" colSpan={13}>
                  No leg data available.
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </div>
  )
}
