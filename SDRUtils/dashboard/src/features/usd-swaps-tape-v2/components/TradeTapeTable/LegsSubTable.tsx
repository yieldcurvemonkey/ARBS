'use client'
// ABOUTME: Expanded package detail panel with richer package and per-leg fields.
import type { JSX, ReactNode } from 'react'
import { EMPTY_VALUE, LIFECYCLE_LABELS, LIFECYCLE_TONES } from '../../constants'
import type { UsdSwapTapeLeg, UsdSwapTapeRow } from '../../types'
import {
  formatDate,
  formatDv01,
  formatExecutionWindow,
  formatNotional,
  formatRate,
  formatRateRange,
} from '../../utils/format'
import { FlagBadges, LifecyclePills } from './RowBadges'
import { displayTapeLabel } from './TapeLabelCell.helpers'

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

function firstLeg(row: UsdSwapTapeRow): UsdSwapTapeLeg | undefined {
  return row.legs_json?.[0]
}

function uniqueStrings(values: Array<string | null | undefined>): string[] {
  const seen = new Set<string>()
  const out: string[] = []
  for (const value of values) {
    if (typeof value !== 'string') continue
    const trimmed = value.trim()
    if (!trimmed || seen.has(trimmed)) continue
    seen.add(trimmed)
    out.push(trimmed)
  }
  return out
}

function summarizeStrings(values: Array<string | null | undefined>): string {
  const unique = uniqueStrings(values)
  return unique.length ? unique.join(' / ') : EMPTY_VALUE
}

function summarizeDates(values: Array<string | null | undefined>): string {
  const formatted = uniqueStrings(
    values.map((value) => {
      const display = formatDate(value)
      return display === EMPTY_VALUE ? null : display
    }),
  )
  return formatted.length ? formatted.join(' / ') : EMPTY_VALUE
}

function summarizeRates(values: Array<number | null | undefined>): string {
  const formatted = uniqueStrings(
    values.map((value) =>
      value === null || value === undefined ? null : formatRate(value),
    ),
  )
  return formatted.length ? formatted.join(' / ') : EMPTY_VALUE
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

function DetailItem({
  label,
  value,
  wide = false,
}: {
  label: string
  value: ReactNode
  wide?: boolean
}) {
  return (
    <div
      className={`rounded-lg border border-slate-800 bg-slate-950/60 px-3 py-2 ${
        wide ? 'md:col-span-2 xl:col-span-2' : ''
      }`}
    >
      <div className="text-[10px] uppercase tracking-wide text-slate-500">
        {label}
      </div>
      <div className="mt-1 break-words text-xs text-slate-100">{value}</div>
    </div>
  )
}

export function LegsSubTable({ row }: { row: UsdSwapTapeRow }): JSX.Element {
  const legs = (row.legs_json ?? []) as UsdSwapTapeLeg[]
  const primaryLeg = firstLeg(row)
  const effectiveDates = summarizeDates([
    row.effective_date,
    ...legs.map((leg) => leg.effective_date),
  ])
  const maturityDates = summarizeDates([
    row.expiration_date,
    ...legs.map((leg) => maturityDateOf(leg)),
  ])
  const platforms = summarizeStrings([
    row.platform_identifier,
    ...legs.map((leg) => leg.platform_identifier),
  ])
  const ufroReported = summarizeRates(
    legs.filter((leg) => leg.is_ufro).map((leg) => leg.fixed_rate),
  )
  const venueCcpSession = summarizeStrings([
    [row.venue, row.ccp, row.execution_session].filter(Boolean).join(' / ') || null,
  ])

  return (
    <div
      className="rounded-xl border border-slate-800/80 bg-slate-950/70 px-4 py-3"
      data-testid={`legs-subtable-${row.package_id}`}
    >
      <div className="mb-3">
        <div className="mb-2 text-[10px] font-semibold uppercase tracking-wide text-slate-400">
          Package Details
        </div>
        <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-4">
          <DetailItem label="Tape Label" value={displayTapeLabel(row)} wide />
          <DetailItem label="Package ID" value={row.package_id} />
          <DetailItem
            label="Type"
            value={row.trade_type ?? primaryLeg?.trade_type ?? row.package_type ?? EMPTY_VALUE}
          />
          <DetailItem label="Action Mix" value={<LifecyclePills row={row} />} />
          <DetailItem label="Platform" value={platforms} />
          <DetailItem
            label="Execution Window"
            value={formatExecutionWindow(row.execution_start, row.execution_end)}
          />
          <DetailItem label="Effective Date" value={effectiveDates} />
          <DetailItem label="Maturity Date" value={maturityDates} />
          <DetailItem
            label="Weighted Rate"
            value={formatRate(row.weighted_fixed_rate ?? null)}
          />
          <DetailItem
            label="Rate Range"
            value={formatRateRange(row.min_fixed_rate ?? null, row.max_fixed_rate ?? null)}
          />
          <DetailItem
            label="Notional"
            value={formatNotional(row.total_notional ?? null, { compact: true })}
          />
          <DetailItem
            label="DV01"
            value={formatDv01(row.total_risk ?? null, { signed: true })}
          />
          <DetailItem label="Venue / CCP / Session" value={venueCcpSession} />
          <DetailItem
            label="UFRO Reported"
            value={ufroReported !== EMPTY_VALUE ? ufroReported : row.is_ufro_any ? 'Flagged' : EMPTY_VALUE}
          />
          <DetailItem
            label="Structure"
            value={row.package_structure ?? row.package_tenors ?? EMPTY_VALUE}
          />
          <DetailItem label="Flags" value={<FlagBadges row={row} />} />
        </div>
      </div>
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
              <th className="px-2 py-1 text-left">Tenor</th>
              <th className="px-2 py-1 text-left">Effective</th>
              <th className="px-2 py-1 text-left">Maturity</th>
              <th className="px-2 py-1 text-right">Notional</th>
              <th className="px-2 py-1 text-right">DV01</th>
              <th className="px-2 py-1 text-right">Rate</th>
              <th className="px-2 py-1 text-left">UFRO</th>
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
                  {leg.tenor_display ?? leg.tenor_label ?? EMPTY_VALUE}
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
                <td className="whitespace-nowrap px-2 py-1">
                  {leg.is_ufro
                    ? leg.fixed_rate === null || leg.fixed_rate === undefined
                      ? 'Flagged'
                      : formatRate(leg.fixed_rate)
                    : EMPTY_VALUE}
                </td>
                <td className="px-2 py-1">{qualityFlagsBody(leg)}</td>
                <td className="whitespace-nowrap px-2 py-1">{crossDayProgress(leg)}</td>
              </tr>
            ))}
            {legs.length === 0 ? (
              <tr className="border-t border-slate-800/90 text-slate-400">
                <td className="px-2 py-2" colSpan={15}>
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
