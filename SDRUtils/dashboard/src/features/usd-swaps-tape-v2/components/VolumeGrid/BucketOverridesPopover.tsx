'use client'
import { useCallback, useRef, useState, type JSX } from 'react'
import type { BucketOverrides } from '../../types/volume-grid-views.types'

export interface BucketOverridesPopoverProps {
  buckets: ReadonlyArray<{ id: string; label: string }>
  overrides: BucketOverrides
  onChange: (overrides: BucketOverrides) => void
}

export function BucketOverridesPopover({ buckets, overrides, onChange }: BucketOverridesPopoverProps): JSX.Element {
  const [open, setOpen] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)

  const toggleHidden = useCallback((bucketId: string) => {
    const isHidden = overrides.hidden.includes(bucketId)
    const next = isHidden
      ? overrides.hidden.filter((id) => id !== bucketId)
      : [...overrides.hidden, bucketId]
    onChange({ ...overrides, hidden: next })
  }, [overrides, onChange])

  const reset = useCallback(() => {
    onChange({ hidden: [], merged: [] })
  }, [onChange])

  return (
    <div className="relative" ref={containerRef}>
      <button
        type="button"
        aria-label="Customize buckets"
        onClick={() => setOpen((v) => !v)}
        className="rounded border border-slate-700 px-1.5 py-[2px] font-mono text-[10.5px] text-slate-400 hover:bg-slate-800 hover:text-slate-200"
      >
        ⚙
      </button>
      {open && (
        <div className="absolute right-0 top-full z-50 mt-1 w-64 rounded border border-slate-700 bg-slate-900 p-3 shadow-xl">
          <div className="mb-2 flex items-center justify-between">
            <span className="font-mono text-[10px] uppercase tracking-wider text-slate-400">
              Customize buckets
            </span>
            <button
              type="button"
              onClick={reset}
              className="font-mono text-[10px] text-indigo-300 hover:text-indigo-200"
            >
              Reset
            </button>
          </div>
          <div className="grid grid-cols-2 gap-1">
            {buckets.map((b) => (
              <label key={b.id} className="flex items-center gap-1.5 font-mono text-[10px] text-slate-300">
                <input
                  type="checkbox"
                  aria-label={b.label}
                  checked={!overrides.hidden.includes(b.id)}
                  onChange={() => toggleHidden(b.id)}
                  className="h-3 w-3 rounded border-slate-600 bg-slate-800"
                />
                {b.label}
              </label>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
