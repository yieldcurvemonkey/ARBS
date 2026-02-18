export type ManualSwapLinkValidationStatus = 'ok' | 'warn' | 'error'

export type ManualSwapLinkValidationItem = {
  key: string
  label: string
  status: ManualSwapLinkValidationStatus
  message: string
}

export type ManualSwapLinkTrade = {
  trade_id: string
  package_id: string
  trade_label?: string | null
  product_type?: string | null
  notional?: number | null
  risk?: number | null
  fixed_rate?: number | null
  execution_timestamp?: string | null
  platform_identifier?: string | null
}

export type ManualSwapLinkHistoryItem = {
  history_id: number
  action: string
  changed_by: string
  changed_at: string
  change_details?: Record<string, any> | null
  previous_state?: Record<string, any> | null
}

export type ManualSwapLinkDetail = {
  link_id: string
  manual_package_id: string
  package_type: string | null
  linked_trade_ids: string[]
  created_by: string
  created_at: string
  updated_by?: string | null
  updated_at?: string | null
  user_comment?: string | null
  link_reason?: string | null
  tags?: string[] | null
  link_metrics?: Record<string, any> | null
  is_active: boolean
}
