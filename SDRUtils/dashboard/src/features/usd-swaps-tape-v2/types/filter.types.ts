import type { LifecycleType } from './trade.types'

export type FilterConstraint = {
  value?: unknown
  matchMode?: string
}

export type ColumnFilterMeta = {
  operator?: string
  constraints?: FilterConstraint[]
  value?: unknown
  matchMode?: string
}

export type ColumnFilterPayload = Record<string, ColumnFilterMeta>

export interface FlagFilterState {
  lifecycle: Set<LifecycleType>
  tradeTypes: Set<string>
  venues: Set<string>
  ccps: Set<string>
  sessions: Set<string>
  rateIndex: Set<string>
  tenors: Set<string>
  fomcMeeting: string | null
  clean: boolean
}

export type LifecycleChipState = {
  type: LifecycleType
  count: number
  selected: boolean
}

export type CategoryFilterKey =
  | 'lifecycle'
  | 'tradeTypes'
  | 'venues'
  | 'ccps'
  | 'sessions'
  | 'rateIndex'
  | 'tenors'
