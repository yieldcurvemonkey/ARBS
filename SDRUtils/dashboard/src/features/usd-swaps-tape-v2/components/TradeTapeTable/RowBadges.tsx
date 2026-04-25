'use client'
// ABOUTME: Lifecycle mix pill stack and flag badge stack for the main tape rows.
import type { JSX } from 'react'
import type { UsdSwapTapeRow } from '../../types'
import {
  economicClassBadgeFor,
  extendedLifecyclePillsFor,
  flagBadgesFor,
  lifecyclePillsFor,
  qualityBadgesFor,
} from './RowBadges.helpers'

export {
  economicClassBadgeFor,
  extendedLifecyclePillsFor,
  flagBadgesFor,
  lifecyclePillsFor,
  qualityBadgesFor,
} from './RowBadges.helpers'

export function LifecyclePills({ row }: { row: UsdSwapTapeRow }): JSX.Element {
  // Use the extended set so AMEND / NULL_FILL / SCHED_AMORT / EROR
  // pills surface alongside the mix-derived pills. Falls back to the
  // legacy set when no leg-level lc_was_* flags are populated.
  const pills = extendedLifecyclePillsFor(row)
  if (pills.length === 0) return <span className="text-slate-500 text-[12px]">-</span>
  return (
    <div className="flex flex-wrap items-center gap-1" data-testid="lifecycle-pills">
      {pills.map((p) => (
        <span
          key={p.type}
          className={`px-1 py-0.5 rounded text-[11px] font-semibold ${p.className}`}
          aria-label={`${p.label} x ${p.count}`}
        >
          {p.label}
        </span>
      ))}
    </div>
  )
}

export function FlagBadges({ row }: { row: UsdSwapTapeRow }): JSX.Element {
  const badges = flagBadgesFor(row)
  if (badges.length === 0) return <span className="text-slate-500 text-xs">-</span>
  return (
    <div className="flex items-center gap-1" data-testid="flag-badges">
      {badges.map((b) => (
        <span
          key={b.key}
          className={`px-1 py-0.5 rounded text-[10px] font-semibold ${b.className}`}
          aria-label={b.ariaLabel}
        >
          {b.label}
        </span>
      ))}
    </div>
  )
}


/**
 * Phase 3 economic-class badge — single inline badge for the new
 * "Class" column. Returns a dash when the row has no class signal.
 */
export function EconomicClassBadge({
  row,
}: {
  row: UsdSwapTapeRow
}): JSX.Element {
  const meta = economicClassBadgeFor(row)
  if (!meta) return <span className="text-slate-500 text-[12px]">-</span>
  return (
    <span
      className={`inline-flex items-center rounded px-1 py-0.5 text-[10px] font-semibold ${meta.className}`}
      title={meta.title}
      data-testid="economic-class-badge"
    >
      {meta.label}
    </span>
  )
}


/**
 * Phase 4-5 compliance / data-quality badges. Stacks state-machine
 * violation, cap-band, freq-anomaly, schedule truncation, D2-missing
 * etc. Renders nothing when the row is clean (the common case).
 */
export function QualityBadges({ row }: { row: UsdSwapTapeRow }): JSX.Element {
  const badges = qualityBadgesFor(row)
  if (badges.length === 0) return <span className="text-slate-600 text-[10px]">·</span>
  return (
    <div className="flex flex-wrap items-center gap-1" data-testid="quality-badges">
      {badges.map((b) => (
        <span
          key={b.key}
          className={`px-1 py-0.5 rounded text-[10px] font-semibold ${b.className}`}
          aria-label={b.ariaLabel}
          title={b.title}
        >
          {b.label}
        </span>
      ))}
    </div>
  )
}
