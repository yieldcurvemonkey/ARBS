// Swaptions tape display view resolution.
// Dynamically selects the database view based on schema availability.

import { query } from './db';

// Re-export TapeRow so API routes can import from a single location.
export type { TapeRow } from '@/features/swaptions-tape/types/trade.types';

type DisplayViewResult = {
  view: string;
  columns: string;
  hasManualFields: boolean;
};

const V2_VIEW = 'arbs_swaption_display_items_v2';
const V1_VIEW = 'arbs_swaption_master_tape_v2';

const V2_COLUMNS = [
  'package_id',
  'package_type',
  'package_source',
  'manual_link_id',
  'manual_package_id',
  'user_comment',
  'link_reason',
  'tags',
  'link_metrics',
  'link_created_by',
  'link_created_at',
  'detection_strat',
  'as_of_date',
  'execution_start',
  'execution_end',
  'expiration_date',
  'underlying_expiration_date',
  'tenor_label',
  'forward_label',
  'legs_count',
  'total_notional',
  'total_premium',
  'package_indicator',
  'package_transaction_price',
  'package_confidence',
  'package_reason',
  'is_notional_capped',
  'vega_curve_id',
  'vega_curve_type',
  'package_metrics',
  'legs_json',
].map((col) => `d.${col}`).join(', ');

const V1_COLUMNS = [
  'package_id',
  'package_type',
  'as_of_date',
  'execution_start',
  'execution_end',
  'expiration_date',
  'underlying_expiration_date',
  'tenor_label',
  'forward_label',
  'legs_count',
  'total_notional',
  'total_premium',
  'package_indicator',
  'package_transaction_price',
  'package_confidence',
  'package_reason',
  'is_notional_capped',
  'vega_curve_id',
  'vega_curve_type',
  'package_metrics',
  'legs_json',
].map((col) => `d.${col}`).join(', ');

let cachedResult: DisplayViewResult | null = null;

async function viewExists(viewName: string): Promise<boolean> {
  const result = await query(
    `SELECT 1 FROM information_schema.tables WHERE table_name = $1 LIMIT 1`,
    [viewName],
  );
  return result.rows.length > 0;
}

/**
 * Resolve which display view to query from.
 * Prefers v2 (with manual link fields) when available, falls back to v1.
 * Result is cached for the lifetime of the server process.
 */
export async function resolveDisplayView(): Promise<DisplayViewResult> {
  if (cachedResult) return cachedResult;

  const hasV2 = await viewExists(V2_VIEW);
  if (hasV2) {
    cachedResult = {
      view: V2_VIEW,
      columns: V2_COLUMNS,
      hasManualFields: true,
    };
  } else {
    cachedResult = {
      view: V1_VIEW,
      columns: V1_COLUMNS,
      hasManualFields: false,
    };
  }

  return cachedResult;
}
