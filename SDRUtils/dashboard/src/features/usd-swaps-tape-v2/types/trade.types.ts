import type { SofrSwapTapeLeg, SofrSwapTapeRow } from '@/features/sofr-swaps-tape/types'

export type LifecycleType =
  | 'NEW_RISK'
  | 'UNWIND'
  | 'COMPRESSION'
  | 'TERMINATION'
  | 'NOVATION'
  | 'RESET_OPT'
  | 'CORRECTION'
  | 'CLEARING_TERM'
  | 'EXERCISE_BORN'
  | 'OTHER'

export type UsdSwapTapeLeg = SofrSwapTapeLeg & {
  tape_label?: string | null
  trade_type?: string | null
  tenor_display?: string | null
  venue?: string | null
  ccp?: string | null
  rate_index_clean?: string | null
  execution_session?: string | null
  lifecycle_type?: LifecycleType | null
  fomc_meeting_label?: string | null
  fomc_proximity?: string | null
  cluster_id?: string | null
  is_new_risk?: boolean | null
  is_unwind?: boolean | null
  is_compression?: boolean | null
  is_reset_optimization?: boolean | null
  is_ufro?: boolean | null
  is_off_market?: boolean | null
  is_capped?: boolean | null
  is_block?: boolean | null
  is_off_date?: boolean | null
  is_novation_born?: boolean | null
  is_novation_terminated?: boolean | null
  is_exercise_born?: boolean | null
  is_clearing_termination?: boolean | null
  is_non_standard_term?: boolean | null
  xd_status?: string | null
  xd_is_terminated?: boolean | null
  xd_has_partial_unwind?: boolean | null
  xd_notional_pct_remaining?: number | null
  quality_flags?: string[] | null
}

export type UsdSwapTapeRow = SofrSwapTapeRow & {
  package_structure?: string | null
  package_tenors?: string | null
  n_package_legs?: number | null
  trade_type?: string | null
  venue?: string | null
  ccp?: string | null
  rate_index_clean?: string | null
  execution_session?: string | null
  tape_label?: string | null
  fomc_meeting_label?: string | null
  is_fomc_dated?: boolean | null
  is_unwind?: boolean | null
  is_block_any?: boolean | null
  is_capped_any?: boolean | null
  is_off_date_any?: boolean | null
  is_compression_any?: boolean | null
  is_ufro_any?: boolean | null
  is_termination_any?: boolean | null
  is_novation_any?: boolean | null
  is_reset_optimization_any?: boolean | null
  is_clearing_termination_any?: boolean | null
  is_correction_any?: boolean | null
  is_new_risk?: boolean | null
  has_spread?: boolean | null
  cluster_id?: string | null
  cluster_size?: number | null
  lifecycle_mix?: Record<string, number> | null
  legs_json: UsdSwapTapeLeg[]
}

export type UsdSwapTapeResponse = {
  rows: UsdSwapTapeRow[]
  nextCursor: string | null
  hasMore: boolean
  latestExecutionStart: string | null
}
