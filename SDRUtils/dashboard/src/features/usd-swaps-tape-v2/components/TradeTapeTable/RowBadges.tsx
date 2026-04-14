'use client'
// ABOUTME: Lifecycle mix pill stack and flag badge stack for the main tape rows.
import type { JSX } from 'react'
import type { UsdSwapTapeRow } from '../../types'
import { flagBadgesFor, lifecyclePillsFor } from './RowBadges.helpers'

export { flagBadgesFor, lifecyclePillsFor } from './RowBadges.helpers'

export function LifecyclePills({ row }: { row: UsdSwapTapeRow }): JSX.Element {
  const pills = lifecyclePillsFor(row)
  if (pills.length === 0) return <span className="text-slate-500 text-xs">—</span>
  return (
    <div className="flex items-center gap-1" data-testid="lifecycle-pills">
      {pills.map((p) => (
        <span
          key={p.type}
          className={`px-1 py-0.5 rounded text-[10px] font-semibold ${p.className}`}
          aria-label={`${p.label} x ${p.count}`}
        >
          {p.label}
          {p.count > 1 ? ` ${p.count}` : ''}
        </span>
      ))}
    </div>
  )
}

export function FlagBadges({ row }: { row: UsdSwapTapeRow }): JSX.Element {
  const badges = flagBadgesFor(row)
  if (badges.length === 0) return <span className="text-slate-500 text-xs">—</span>
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
