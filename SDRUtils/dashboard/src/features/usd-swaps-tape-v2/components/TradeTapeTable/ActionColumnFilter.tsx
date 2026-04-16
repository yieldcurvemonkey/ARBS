'use client'
// ABOUTME: Multi-select filter element for the lifecycle "action" column.
// Replaces the removed header FlagChips (feedback round 1).
import type { JSX } from 'react'
import { MultiSelect } from 'primereact/multiselect'
import { LIFECYCLE_LABELS, LIFECYCLE_ORDER } from '../../constants'
import type { LifecycleType } from '../../types'

export interface ActionColumnFilterProps {
  value: LifecycleType[] | null
  filterCallback: (value: LifecycleType[]) => void
}

export function ActionColumnFilter({
  value,
  filterCallback,
}: ActionColumnFilterProps): JSX.Element {
  return (
    <MultiSelect
      value={value ?? []}
      options={LIFECYCLE_ORDER.map((k) => ({
        value: k,
        label: LIFECYCLE_LABELS[k],
      }))}
      optionLabel="label"
      optionValue="value"
      onChange={(e) => filterCallback((e.value ?? []) as LifecycleType[])}
      placeholder="Lifecycle"
      className="text-[11px]"
    />
  )
}

export { matchActionSelection } from './ActionColumnFilter.helpers'
