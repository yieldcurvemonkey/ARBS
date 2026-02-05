// Manual link utilities for swaption trade linking.
// Provides validation, metrics computation, and CRUD helpers.

import { query } from './db';
import crypto from 'crypto';

// Table names (centralized to avoid typos across API routes)
export const MANUAL_LINKS_TABLE = 'arbs_manual_links';
export const MANUAL_LINK_HISTORY_TABLE = 'arbs_manual_link_history';

// --- Types ---

type ManualLinkLeg = {
  trade_id: string;
  package_id: string;
  trade_label?: string | null;
  product_type?: string | null;
  notional?: number | null;
  premium?: number | null;
  execution_timestamp?: string | null;
  platform_identifier?: string | null;
  strike?: number | null;
};

type ManualLinkConflict = {
  link_id: string;
  manual_package_id: string;
  conflicting_trade_ids: string[];
};

type ValidationItem = {
  key: string;
  label: string;
  status: 'ok' | 'warn' | 'error';
  message: string;
};

type TableAvailability = {
  linksTable: boolean;
  historyTable: boolean;
  missingTables: string[];
};

// --- Public API ---

/**
 * Normalize a raw trade_ids input (string, array, etc.) into a
 * deduplicated array of non-empty strings.
 */
export function normalizeIdList(value: unknown): string[] {
  if (!value) return [];
  let items: string[];
  if (Array.isArray(value)) {
    items = value.map((entry) => String(entry).trim()).filter(Boolean);
  } else if (typeof value === 'string') {
    items = value
      .split(/[,\s]+/)
      .map((entry) => entry.trim())
      .filter(Boolean);
  } else {
    items = [String(value).trim()].filter(Boolean);
  }
  return Array.from(new Set(items));
}

/**
 * Check whether the manual link tables exist in the database.
 */
export async function checkManualLinkTables(): Promise<TableAvailability> {
  const result = await query(
    `SELECT table_name
     FROM information_schema.tables
     WHERE table_name IN ($1, $2)`,
    [MANUAL_LINKS_TABLE, MANUAL_LINK_HISTORY_TABLE],
  );

  const existing = new Set(result.rows.map((r: any) => r.table_name));
  const linksTable = existing.has(MANUAL_LINKS_TABLE);
  const historyTable = existing.has(MANUAL_LINK_HISTORY_TABLE);

  const missingTables: string[] = [];
  if (!linksTable) missingTables.push(MANUAL_LINKS_TABLE);
  if (!historyTable) missingTables.push(MANUAL_LINK_HISTORY_TABLE);

  return { linksTable, historyTable, missingTables };
}

/**
 * Resolve input trade/package IDs into their constituent legs from
 * the swaption legs table.
 */
export async function resolveLinkLegs(
  inputIds: string[],
): Promise<ManualLinkLeg[]> {
  if (!inputIds.length) return [];

  const result = await query(
    `SELECT trade_id,
            package_id,
            trade_label,
            product_type,
            notional,
            premium,
            execution_timestamp,
            platform_identifier,
            strike
     FROM arbs_swaption_legs_v1
     WHERE trade_id = ANY($1)
        OR package_id = ANY($1)
     ORDER BY execution_timestamp DESC`,
    [inputIds],
  );

  return result.rows as ManualLinkLeg[];
}

/**
 * Compute aggregate metrics for a set of linked legs.
 */
export function computeLinkMetrics(
  legs: ManualLinkLeg[],
): Record<string, any> {
  const metrics: Record<string, any> = {};
  if (!legs.length) return metrics;

  const notionals = legs
    .map((l) => l.notional)
    .filter((n): n is number => n != null);

  metrics.leg_count = legs.length;
  metrics.trade_count = new Set(legs.map((l) => l.trade_id)).size;
  metrics.total_notional = notionals.reduce((s, n) => s + n, 0);
  metrics.package_ids = Array.from(new Set(legs.map((l) => l.package_id)));

  return metrics;
}

/**
 * Find existing active manual links that already contain any of the
 * given trade IDs (i.e. potential conflicts).
 */
export async function findManualLinkConflicts(
  tradeIds: string[],
  excludeLinkId?: string,
): Promise<ManualLinkConflict[]> {
  if (!tradeIds.length) return [];

  const params: unknown[] = [tradeIds];
  let excludeClause = '';
  if (excludeLinkId) {
    params.push(excludeLinkId);
    excludeClause = `AND link_id <> $${params.length}`;
  }

  const result = await query(
    `SELECT link_id, manual_package_id, linked_trade_ids
     FROM ${MANUAL_LINKS_TABLE}
     WHERE is_active = TRUE
       AND linked_trade_ids && $1
       ${excludeClause}`,
    params,
  );

  return result.rows.map((row: any) => {
    const existingIds: string[] = Array.isArray(row.linked_trade_ids)
      ? row.linked_trade_ids
      : [];
    const overlap = tradeIds.filter((id) => existingIds.includes(id));
    return {
      link_id: row.link_id,
      manual_package_id: row.manual_package_id,
      conflicting_trade_ids: overlap,
    };
  });
}

/**
 * Build validation result items from legs, metrics, and conflicts.
 */
export function buildValidationItems(
  legs: ManualLinkLeg[],
  metrics: Record<string, any>,
  conflicts: ManualLinkConflict[],
): { items: ValidationItem[]; hasErrors: boolean } {
  const items: ValidationItem[] = [];

  // Minimum trade count
  const uniqueTradeIds = new Set(legs.map((l) => l.trade_id));
  if (uniqueTradeIds.size < 2) {
    items.push({
      key: 'min_trades',
      label: 'Minimum Trades',
      status: 'error',
      message: `At least 2 trades required, found ${uniqueTradeIds.size}.`,
    });
  } else {
    items.push({
      key: 'min_trades',
      label: 'Minimum Trades',
      status: 'ok',
      message: `${uniqueTradeIds.size} trades selected.`,
    });
  }

  // Conflict check
  if (conflicts.length > 0) {
    const conflictIds = conflicts.map((c) => c.manual_package_id).join(', ');
    items.push({
      key: 'conflicts',
      label: 'Existing Links',
      status: 'warn',
      message: `Overlap with existing link(s): ${conflictIds}.`,
    });
  } else {
    items.push({
      key: 'conflicts',
      label: 'Existing Links',
      status: 'ok',
      message: 'No conflicting links found.',
    });
  }

  const hasErrors = items.some((item) => item.status === 'error');
  return { items, hasErrors };
}

/**
 * Generate a unique manual package ID (prefixed with "ML-").
 */
export async function generateManualPackageId(): Promise<string> {
  const hex = crypto.randomBytes(8).toString('hex');
  return `ML-${hex}`;
}
