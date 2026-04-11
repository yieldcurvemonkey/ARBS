import { query } from '@/lib/db'
import type { SofrSwapTapeRow } from '@/features/sofr-swaps-tape/types'

const DISPLAY_VIEW_CANDIDATES = [
  { view: 'arbs_usd_swap_display_items_v4', hasManualFields: true },
  { view: 'arbs_usd_swap_display_items_v3', hasManualFields: false }
] as const

type DisplayView = {
  view: string
  columns: string
  hasManualFields: boolean
}

const COLUMNS_V1 = [
  'd.package_id',
  'd.package_type',
  'd.as_of_date',
  'd.execution_start',
  'd.execution_end',
  'd.effective_date',
  'd.expiration_date',
  'd.tenor_years',
  'd.tenor_label',
  'd.forward_start_years',
  'd.forward_label',
  'd.is_forward',
  'd.legs_count',
  'd.total_notional',
  'd.gross_notional',
  'd.total_risk',
  'd.gross_risk',
  'd.weighted_fixed_rate',
  'd.min_fixed_rate',
  'd.max_fixed_rate',
  'd.package_indicator',
  'd.package_transaction_spread',
  'd.package_metrics',
  'd.legs_json',
  'plat.platform_identifier',
  'plat.event_action'
]

const COLUMNS_V2 = [
  'd.package_id',
  'd.package_type',
  'd.package_source',
  'd.link_id AS manual_link_id',
  'd.manual_package_id',
  'd.user_comment',
  'd.link_reason',
  'd.tags',
  'd.link_created_by',
  'd.link_created_at',
  'd.link_metrics',
  'd.as_of_date',
  'd.execution_start',
  'd.execution_end',
  'd.effective_date',
  'd.expiration_date',
  'd.tenor_years',
  'd.tenor_label',
  'd.forward_start_years',
  'd.forward_label',
  'd.is_forward',
  'd.legs_count',
  'd.total_notional',
  'd.gross_notional',
  'd.total_risk',
  'd.gross_risk',
  'd.weighted_fixed_rate',
  'd.min_fixed_rate',
  'd.max_fixed_rate',
  'd.package_indicator',
  'd.package_transaction_spread',
  'd.package_metrics',
  'd.legs_json',
  'plat.platform_identifier',
  'plat.event_action'
]

let cachedView: DisplayView | null = null
let cachedAt = 0
const CACHE_TTL_MS = 60_000

async function relationExists(name: string) {
  try {
    const result = await query<{ rel: string | null }>(
      'SELECT to_regclass($1) AS rel',
      [name]
    )
    return Boolean(result.rows[0]?.rel)
  } catch (error) {
    console.warn('usd-swaps-tape display view check failed', error)
    return false
  }
}

export async function resolveDisplayView(): Promise<DisplayView> {
  const now = Date.now()
  if (cachedView && now - cachedAt < CACHE_TTL_MS) {
    return cachedView
  }

  let selected: typeof DISPLAY_VIEW_CANDIDATES[number] | null = null
  for (const candidate of DISPLAY_VIEW_CANDIDATES) {
    if (await relationExists(candidate.view)) {
      selected = candidate
      break
    }
  }

  const fallback = DISPLAY_VIEW_CANDIDATES[DISPLAY_VIEW_CANDIDATES.length - 1]
  const chosen = selected ?? fallback
  const columns = (chosen.hasManualFields ? COLUMNS_V2 : COLUMNS_V1).join(', ')

  cachedView = {
    view: chosen.view,
    columns,
    hasManualFields: chosen.hasManualFields
  }
  cachedAt = now
  return cachedView
}

export type { SofrSwapTapeRow }
