// ABOUTME: Shared types for the manual-links UI primitives. These are the
// minimal shapes both consumer features (swaptions-tape, usd-swaps-tape-v2)
// project onto rows / detail records / history items. Consumer-specific
// extensions live in each consumer's own type modules.

/**
 * Fields the row-level helpers (predicates, grouping, badge) need from any
 * tape row. Consumer feature types (TapeRow, UsdSwapTapeRow, ...) all
 * carry a superset of these fields - this is the structural intersection.
 */
export interface TapeRowLike {
  manual_link_id?: string | null;
  manual_package_id?: string | null;
  package_source?: string | null;
}

/**
 * Validation outcome for a single check (server-side computed and surfaced
 * back to the modal).
 */
export type ManualLinkValidationStatus = 'ok' | 'warn' | 'error';

export type ManualLinkValidationItem = {
  key: string;
  label: string;
  status: ManualLinkValidationStatus;
  message: string;
};

/**
 * One trade leg as returned by `GET /links/:id` - same shape used by both
 * swaptions and usd-swaps consumers (both map to the same SQL projection).
 */
export type ManualLinkTrade = {
  trade_id: string;
  package_id: string;
  trade_label?: string | null;
  product_type?: string | null;
  notional?: number | null;
  execution_timestamp?: string | null;
  platform_identifier?: string | null;
};

/**
 * History audit entry returned by `GET /links/:id`.
 */
export type ManualLinkHistoryItem = {
  history_id: number;
  action: string;
  changed_by: string;
  changed_at: string;
  change_details?: Record<string, unknown> | null;
  previous_state?: Record<string, unknown> | null;
};

/**
 * Detail record returned by `GET /links/:id`. Includes the link record and
 * its currently-linked trades; history is fetched alongside but exposed as
 * a separate property for clarity.
 */
export type ManualLinkDetail = {
  link_id: string;
  manual_package_id: string;
  package_type: string | null;
  linked_trade_ids: string[];
  created_by: string;
  created_at: string;
  updated_by?: string | null;
  updated_at?: string | null;
  user_comment?: string | null;
  link_reason?: string | null;
  tags?: string[] | null;
  link_metrics?: Record<string, unknown> | null;
  is_active: boolean;
};

/**
 * Composite detail bundle: link + linked trades + history, matching the
 * `GET /links/:id` response wire shape.
 */
export type ManualLinkDetailBundle = {
  link: ManualLinkDetail;
  trades: ManualLinkTrade[];
  history: ManualLinkHistoryItem[];
};
