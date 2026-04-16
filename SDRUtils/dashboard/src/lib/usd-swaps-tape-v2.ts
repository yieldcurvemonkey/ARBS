// ABOUTME: Resolver for the USD swap tape v2 display view and column list.
import { query } from '@/lib/db'

export const DISPLAY_VIEW = 'arbs_usd_swap_tape_display_v1'
export const PACKAGES_TABLE = 'arbs_usd_swap_tape_packages_v1'
export const LEGS_TABLE = 'arbs_usd_swap_tape_legs_v1'

const COLUMNS = [
  'd.package_id',
  'd.manual_link_id',
  'd.as_of_date',
  'd.execution_start',
  'd.execution_end',
  'd.package_structure',
  'd.package_type',
  'd.package_indicator',
  'd.package_tenors',
  'd.n_package_legs',
  'd.legs_count',
  'd.total_notional',
  'd.gross_notional',
  'd.total_risk',
  'd.gross_risk',
  'd.weighted_fixed_rate',
  'd.min_fixed_rate',
  'd.max_fixed_rate',
  'd.has_spread',
  'd.package_transaction_spread',
  'd.package_transaction_price',
  'd.package_transaction_price_currency',
  'd.rate_index_clean',
  'd.venue',
  'd.ccp',
  'd.execution_session',
  'd.is_new_risk',
  'd.is_unwind',
  'd.is_compression_any',
  'd.is_ufro_any',
  'd.is_block_any',
  'd.is_capped_any',
  'd.is_off_date_any',
  'd.is_termination_any',
  'd.is_novation_any',
  'd.is_reset_optimization_any',
  'd.is_clearing_termination_any',
  'd.is_correction_any',
  'd.lifecycle_mix',
  'd.is_fomc_dated',
  'd.fomc_meeting_label',
  'd.cluster_id',
  'd.cluster_size',
  'd.tape_label',
  'd.package_metrics',
  'd.legs_json',
  'd.manual_package_id',
  'd.user_comment',
  'd.link_reason',
  'd.tags',
  'd.link_metrics',
  'd.link_created_by',
  'd.link_created_at',
]

export type TapeDisplayView = {
  view: string
  columns: string
}

let cached: TapeDisplayView | null = null
let cachedAt = 0
const CACHE_TTL_MS = 60_000

export async function resolveDisplayView(): Promise<TapeDisplayView> {
  const now = Date.now()
  if (cached && now - cachedAt < CACHE_TTL_MS) {
    return cached
  }
  const result = await query<{ rel: string | null }>(
    'SELECT to_regclass($1) AS rel',
    [DISPLAY_VIEW],
  )
  if (!result.rows[0]?.rel) {
    throw new Error(
      `tape display view ${DISPLAY_VIEW} not found — run ingest_usdswaps_tape`,
    )
  }
  cached = { view: DISPLAY_VIEW, columns: COLUMNS.join(', ') }
  cachedAt = now
  return cached
}

/** Reset the module-level cache; test-only hook. */
export function __resetCache() {
  cached = null
  cachedAt = 0
}
