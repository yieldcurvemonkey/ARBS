'use client'
// ABOUTME: Lifecycle pill row — Strip 3 of the three-strip header.
import type { JSX } from 'react'
import { LIFECYCLE_LABELS, LIFECYCLE_ORDER, LIFECYCLE_TONES } from '../../constants'
import type { LifecycleType } from '../../types'

export interface FlagChipsProps {
  counts: Partial<Record<LifecycleType, number>>
  selected: Set<LifecycleType>
  onToggle: (type: LifecycleType) => void
}

export function FlagChips(props: FlagChipsProps): JSX.Element {
  return (
    <div className="flex items-center gap-1" data-testid="flag-chips">
      {LIFECYCLE_ORDER.map((type) => {
        const active = props.selected.has(type)
        const count = props.counts[type] ?? 0
        const tone = LIFECYCLE_TONES[type]
        return (
          <button
            key={type}
            type="button"
            aria-pressed={active}
            aria-label={`toggle lifecycle ${LIFECYCLE_LABELS[type]}`}
            onClick={() => props.onToggle(type)}
            className={`px-1.5 py-0.5 rounded text-[11px] font-semibold uppercase tracking-wide ${
              active ? tone : 'bg-slate-900/40 text-slate-500 line-through'
            }`}
          >
            {LIFECYCLE_LABELS[type]}
            {count > 0 ? ` ${count.toLocaleString()}` : ''}
          </button>
        )
      })}
    </div>
  )
}
