export type SofrSwapTapeLeg = {
  trade_id?: string
  package_id?: string | null
  leg_order?: number
  event_action?: string | null
  execution_timestamp?: string | null
  effective_date?: string | null
  expiration_date?: string | null
  product_type?: string | null
  trade_label?: string | null
  tenor_years?: number | null
  tenor_label?: string | null
  forward_start_years?: number | null
  forward_label?: string | null
  is_forward?: boolean | null
  notional?: number | null
  notional_currency?: string | null
  is_notional_capped?: boolean | number | string | null
  estimated_pv01?: number | null
  risk?: number | null
  fixed_rate?: number | null
  other_payment_amount?: number | null
  other_payment_currency?: string | null
  package_transaction_spread?: number | null
  package_transaction_price?: number | null
  package_transaction_price_currency?: string | null
  platform_identifier?: string | null
  cleared?: string | null
  package_type?: string | null
  matched_ust_maturity?: boolean | null
  ust_cusip?: string | null
  swap_maturity_date?: string | null
  matched_ust_maturity_trade_confidence?: string | null
  invoice_swap_ticker?: string | null
  is_mac?: boolean | null
  is_spreadover?: boolean | null
  is_asset_swap?: boolean | null
  leg_metrics?: Record<string, any> | null
  manual_link_id?: string | null
  is_manually_linked?: boolean | number | string | null
}

export type SofrSwapTapeRow = {
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
  as_of_date: string | null
  execution_start: string
  execution_end: string
  effective_date?: string | null
  expiration_date?: string | null
  tenor_years?: number | null
  tenor_label?: string | null
  forward_start_years?: number | null
  forward_label?: string | null
  is_forward?: boolean | null
  legs_count: number
  total_notional?: number | null
  gross_notional?: number | null
  total_risk?: number | null
  gross_risk?: number | null
  weighted_fixed_rate?: number | null
  min_fixed_rate?: number | null
  max_fixed_rate?: number | null
  package_indicator?: boolean | null
  package_transaction_spread?: number | null
  package_transaction_price?: number | null
  package_transaction_price_currency?: string | null
  package_metrics: Record<string, any> | null
  legs_json: SofrSwapTapeLeg[]
  platform_identifier?: string | null
  event_action?: string | null
}

export type SofrSwapTapeResponse = {
  rows: SofrSwapTapeRow[]
  nextCursor: string | null
  hasMore: boolean
  latestExecutionStart: string | null
}

export type FlowHistoryStats = {
  tradeCount: number
  grossNotional: number
  grossRisk: number
  avgFixedRate: number | null
  idbTradeCount: number
  custyTradeCount: number
}

export type FlowHistoryDay = {
  date: string
  quadrants: {
    frontShort: FlowHistoryStats
    frontLong: FlowHistoryStats
    forwardShort: FlowHistoryStats
    forwardLong: FlowHistoryStats
  }
  boundary: FlowHistoryStats
  unknown: FlowHistoryStats
  gridTotal: FlowHistoryStats
}

export type FlowHistoryResponse = {
  days: FlowHistoryDay[]
  meta: {
    start: string
    end: string
    forwardBoundary: number
    tenorBoundary: number
    tolerance: number
    platform: string
    tradingDaysCount: number
  }
}

export type TimeseriesMetricKey =
  | 'notional'
  | 'risk'
  | 'fixed_rate'
  | 'trade_count'

export type TimeseriesViewKey = 'INTRADAY' | 'DAILY_CLOSE' | 'DAILY_OHLC'
