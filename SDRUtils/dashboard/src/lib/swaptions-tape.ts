// ABOUTME: Shared utilities for swaptions-tape API routes - resolves display view and column set
import { query } from './db'

export type TapeRow = {
  package_id: string
  package_type: string | null
  package_source?: string | null
  link_id?: string | null
  manual_package_id?: string | null
  user_comment?: string | null
  link_reason?: string | null
  tags?: string[] | null
  link_metrics?: Record<string, any> | null
  link_created_by?: string | null
  link_created_at?: string | null
  as_of_date: string | null
  execution_start: string
  execution_end: string
  expiration_date: string | null
  underlying_expiration_date: string | null
  tenor_label: string | null
  forward_label: string | null
  legs_count: number
  total_notional: number | null
  total_premium: number | null
  package_indicator: boolean | null
  package_transaction_price: number | null
  package_confidence: number | null
  package_reason: string | null
  vega_curve_id?: string | null
  vega_curve_type?: string | null
  package_metrics: Record<string, any> | null
  legs_json: any[]
  platform_identifier?: string | null
  event_action?: string | null
}

const V2_VIEW = 'arbs_swaption_display_items_v2'
const V1_VIEW = 'arbs_swaption_display_items_v1'

// Columns matching the V1 view definition exactly
const V1_COLUMNS = [
  'd.package_id',
  'd.package_type',
  'd.as_of_date',
  'd.execution_start',
  'd.execution_end',
  'd.expiration_date',
  'd.underlying_expiration_date',
  'd.tenor_label',
  'd.forward_label',
  'd.legs_count',
  'd.total_notional',
  'd.total_premium',
  'd.package_indicator',
  'd.package_transaction_price',
  'd.package_confidence',
  'd.package_reason',
  'd.vega_curve_id',
  'd.vega_curve_type',
  'd.package_metrics',
  'd.legs_json',
  'plat.platform_identifier',
  'plat.event_action',
]

// Additional columns in the V2 view (manual linking + package_source)
const V2_EXTRA_COLUMNS = [
  'd.package_source',
  'd.link_id',
  'd.manual_package_id',
  'd.user_comment',
  'd.link_reason',
  'd.tags',
  'd.link_metrics',
  'd.link_created_by',
  'd.link_created_at',
]

let cachedHasManualFields: boolean | null = null

async function checkHasManualFields(): Promise<boolean> {
  if (cachedHasManualFields !== null) return cachedHasManualFields
  try {
    await query(
      `SELECT link_id FROM ${V2_VIEW} LIMIT 0`
    )
    cachedHasManualFields = true
    return true
  } catch {
    cachedHasManualFields = false
    return false
  }
}

export async function resolveDisplayView(): Promise<{
  view: string
  columns: string
  hasManualFields: boolean
}> {
  const hasManualFields = await checkHasManualFields()
  const view = hasManualFields ? V2_VIEW : V1_VIEW
  const columnList = hasManualFields
    ? [...V1_COLUMNS, ...V2_EXTRA_COLUMNS]
    : V1_COLUMNS
  return {
    view,
    columns: columnList.join(', '),
    hasManualFields,
  }
}
