'use client'
// ABOUTME: From/to time-of-day filter element for the execution_start column.
// NOTE(feedback-round-1): SwaptionTradeTape.tsx.bak didn't ship an explicit
// TimestampColumnFilter component (it relied on the default text filter on
// the "time" column), so this is a fresh minimal build — two text inputs
// driving FilterMatchMode.BETWEEN semantics via a [from, to] tuple.
import type { JSX } from 'react'
export { matchTimestampRange } from './TimestampColumnFilter.helpers'
export type { TimestampRange } from './TimestampColumnFilter.helpers'

export interface TimestampColumnFilterProps {
  value: [string | null, string | null] | null
  filterCallback: (value: [string | null, string | null]) => void
}

function asTuple(
  value: TimestampColumnFilterProps['value'],
): [string | null, string | null] {
  if (!Array.isArray(value)) return [null, null]
  return [value[0] ?? null, value[1] ?? null]
}

export function TimestampColumnFilter({
  value,
  filterCallback,
}: TimestampColumnFilterProps): JSX.Element {
  const [from, to] = asTuple(value)
  return (
    <div className="flex flex-col gap-1 p-1 text-[11px]">
      <label className="flex items-center gap-1 text-slate-300">
        <span className="w-8 text-[10px] uppercase tracking-wide text-slate-400">From</span>
        <input
          type="time"
          step="1"
          className="rounded border border-slate-700 bg-slate-900/70 px-1 py-0.5 text-slate-100"
          value={from ?? ''}
          aria-label="filter from time"
          onChange={(e) => filterCallback([e.target.value || null, to])}
        />
      </label>
      <label className="flex items-center gap-1 text-slate-300">
        <span className="w-8 text-[10px] uppercase tracking-wide text-slate-400">To</span>
        <input
          type="time"
          step="1"
          className="rounded border border-slate-700 bg-slate-900/70 px-1 py-0.5 text-slate-100"
          value={to ?? ''}
          aria-label="filter to time"
          onChange={(e) => filterCallback([from, e.target.value || null])}
        />
      </label>
    </div>
  )
}

