// Trade and package types for swaptions tape

export type TapeLeg = {
  trade_id?: string;
  leg_order?: number;
  product_type?: string | null;
  trade_label?: string | null;
  strike?: number | null;
  notional?: number | null;
  notional_currency?: string | null;
  premium?: number | null;
  is_notional_capped?: boolean | number | string | null;
  is_manually_linked?: boolean | number | string | null;
  manual_link_id?: string | null;
  exercise_style?: string | null;
  package_type?: string | null;
  execution_timestamp?: string | null;
  execution_start?: string | null;
  execution_end?: string | null;
  execution_time?: string | null;
  event_timestamp?: string | null;
  leg_metrics?: Record<string, any>;
  event_action?: string | null;
};

export type TapeRow = {
  package_id: string;
  package_type: string | null;
  reported_package_type?: string | null;
  assumed_incomplete_straddle?: boolean;
  assumed_straddle_reason?: string | null;
  package_source?: string | null;
  manual_link_id?: string | null;
  manual_package_id?: string | null;
  user_comment?: string | null;
  link_reason?: string | null;
  tags?: string[] | null;
  link_metrics?: Record<string, any> | null;
  link_created_by?: string | null;
  link_created_at?: string | null;
  detection_strat?: string | null;
  as_of_date: string | null;
  execution_start: string;
  execution_end: string;
  expiration_date: string | null;
  underlying_expiration_date: string | null;
  tenor_label: string | null;
  forward_label: string | null;
  legs_count: number;
  total_notional: number | null;
  total_premium: number | null;
  package_indicator: boolean | null;
  package_transaction_price: number | null;
  package_confidence: number | null;
  package_reason: string | null;
  is_notional_capped?: boolean | number | string | null;
  vega_curve_id?: string | null;
  vega_curve_type?: string | null;
  package_metrics: Record<string, any> | null;
  legs_json: TapeLeg[];
  platform_identifier?: string | null;
  event_action?: string | null;
};

export type TapeResponse = {
  rows: TapeRow[];
  nextCursor: string | null;
  hasMore: boolean;
  latestExecutionStart: string | null;
};

export type LegMetricValues = {
  bpvol: number | null;
  dv01: number | null;
  vega01: number | null;
  gamma01: number | null;
  theta01: number | null;
};
