// ABOUTME: Swaption tape helpers for resolving display views and types.
import { query } from './db'

export type TapeRow = {
  package_id: string
  package_type: string | null
  package_source?: string | null
  manual_link_id?: string | null
  manual_package_id?: string | null
  user_comment?: string | null
  link_reason?: string | null
  tags?: string[] | null
  link_metrics?: Record<string, any> | null
  link_created_by?: string | null
  link_created_at?: string | null
  detection_strat?: string | null
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
  is_notional_capped?: boolean | number | string | null
  vega_curve_id?: string | null
  vega_curve_type?: string | null
  package_metrics: Record<string, any> | null
  legs_json: any[]
  platform_identifier?: string | null
  event_action?: string | null
}

const V2_COLUMNS = `d.package_id, d.package_type, d.package_source, d.detection_strat,
  d.as_of_date, d.execution_start, d.execution_end,
  d.expiration_date, d.underlying_expiration_date,
  d.tenor_label, d.forward_label,
  d.legs_count, d.total_notional, d.total_premium,
  d.package_indicator, d.package_transaction_price,
  d.package_confidence, d.package_reason,
  d.is_notional_capped,
  d.vega_curve_id, d.vega_curve_type,
  d.package_metrics, d.legs_json,
  d.manual_link_id, d.manual_package_id,
  d.user_comment, d.link_reason, d.tags,
  d.link_metrics, d.link_created_by, d.link_created_at`

const V1_COLUMNS = `d.package_id, d.package_type, d.package_source, d.detection_strat,
  d.as_of_date, d.execution_start, d.execution_end,
  d.expiration_date, d.underlying_expiration_date,
  d.tenor_label, d.forward_label,
  d.legs_count, d.total_notional, d.total_premium,
  d.package_indicator, d.package_transaction_price,
  d.package_confidence, d.package_reason,
  d.is_notional_capped,
  d.vega_curve_id, d.vega_curve_type,
  d.package_metrics, d.legs_json`

export async function resolveDisplayView(): Promise<{
  view: string
  columns: string
  hasManualFields: boolean
}> {
  try {
    await query(`SELECT 1 FROM arbs_swaption_display_items_v2 LIMIT 0`)
    return {
      view: 'arbs_swaption_display_items_v2',
      columns: V2_COLUMNS,
      hasManualFields: true,
    }
  } catch {
    return {
      view: 'arbs_swaption_display_items_v1',
      columns: V1_COLUMNS,
      hasManualFields: false,
    }
  }
}
