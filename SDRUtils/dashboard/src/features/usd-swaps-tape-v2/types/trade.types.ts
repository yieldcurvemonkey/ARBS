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
  // Phase 2-3 additions: the canonical Economic-vs-Admin matrix
  // distinguishes amendments from null-fills, scheduled amortization
  // from amendments, and EROR/REVI from straight terminations.
  | 'AMENDMENT'
  | 'NULL_FILL'
  | 'SCHED_AMORT'
  | 'ERROR'
  | 'ERROR_RECOVERY'
  | 'PORT_TRANSFER'
  | 'VALUATION'
  | 'OTHER'

/**
 * Coarse SDR Economic-vs-Administrative classification (matrix kind).
 * Aggregators read ``contributes_to_*`` gates instead of branching on this
 * enum; rendered in the dashboard as a column badge.
 */
export type EconomicClass =
  | 'ECONOMIC_FLOW'
  | 'ECONOMIC_UNWIND'
  | 'ECONOMIC_AMENDMENT'
  | 'RESTATEMENT'
  | 'ADMINISTRATIVE'
  | 'VALUATION'
  | 'ERROR'
  | 'ERROR_RECOVERY'
  | 'UNKNOWN'

export type UsdSwapTapeLeg = SofrSwapTapeLeg & {
  tape_label?: string | null
  // Per-leg tape label — for CURVE/FLY packages this is the leg's own
  // outright description (e.g. "USD-SOFR 5Y Outright"), while `tape_label`
  // remains the package-level structure label ("5Y/10Y CURVE"). Undefined on
  // older rows ingested before the column was added.
  leg_tape_label?: string | null
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
  upi_reset_freq?: string | null
  upi_notional_schedule?: string | null
  upi_delivery_type?: string | null
  xd_status?: string | null
  xd_is_terminated?: boolean | null
  xd_has_partial_unwind?: boolean | null
  xd_notional_pct_remaining?: number | null
  quality_flags?: string[] | null
  // Phase 1: timestamp split + notional source. ``original_execution_timestamp``
  // is the event-study anchor (alpha exec for β/γ clearing rows);
  // ``clearing_accepted_timestamp`` is non-null only on β/γ NEWT-CLRG legs.
  original_execution_timestamp?: string | null
  clearing_accepted_timestamp?: string | null
  notional_source?: 'p43_capped' | 'p43_uncapped' | 'p45' | string | null
  is_notional_capped?: boolean | null
  // Phase 2: dual-chain lifecycle + state-machine validator.
  lc_n_events_economic?: number | null
  lc_n_valuation_events?: number | null
  lc_was_amended?: boolean | null
  lc_was_null_filled?: boolean | null
  lc_was_scheduled_amortization?: boolean | null
  lc_has_economics_change?: boolean | null
  state_machine_violation?: boolean | null
  violation_reason?: string | null
  // Phase 3: Economic-vs-Admin matrix (per-leg).
  economic_class?: EconomicClass | string | null
  contributes_to_flow?: boolean | null
  contributes_to_volume?: boolean | null
  contributes_to_pnl?: boolean | null
  contributes_to_pnl_as_delta?: boolean | null
  on_p43?: boolean | null
  economic_class_reason?: string | null
  // Phase 5: cross-cutting structural columns.
  schedule_truncated?: boolean | null
  schedule_row_count?: number | null
  schedule_notional_series?: number[] | null
  missing_required_fields?: string[] | null
  cap_band_violation?: boolean | null
  rc_timeline_json?: string | null
  other_payment_ufro?: number | null
  other_payment_uwin?: number | null
  other_payment_pexh?: number | null
  frequency_anomaly?: boolean | null
  d2_missing?: boolean | null
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
  // Package-level rollups of the Phase 3/4 matrix + Phase 1 timestamp
  // split. ``*_any`` follow the existing convention: True if any leg
  // contributes; False otherwise. Null when ingest hasn't backfilled yet.
  original_execution_start?: string | null
  clearing_accepted_start?: string | null
  economic_class_primary?: string | null
  contributes_to_flow_any?: boolean | null
  contributes_to_volume_any?: boolean | null
  contributes_to_pnl_any?: boolean | null
  on_p43_any?: boolean | null
  state_machine_violation_any?: boolean | null
  legs_json: UsdSwapTapeLeg[]
}

export type UsdSwapTapeResponse = {
  rows: UsdSwapTapeRow[]
  nextCursor: string | null
  hasMore: boolean
  latestExecutionStart: string | null
}
