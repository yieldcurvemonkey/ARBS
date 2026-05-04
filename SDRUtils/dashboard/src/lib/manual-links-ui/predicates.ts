// ABOUTME: Predicate for "is this row part of a manual / hybrid link?".
// Used by row-level rendering (badge, grouping, click handler) so the
// presence of a manual_link_id, manual_package_id, or MANUAL/HYBRID
// package_source all flag the row as manual-linked.

import type { TapeRowLike } from './types';

/**
 * True when the row participates in a manual or hybrid package link.
 *
 * Three-way disjunction matches the original swaptions logic:
 * 1. `manual_link_id` - the row was directly linked.
 * 2. `manual_package_id` - the row's package has a manual link applied.
 * 3. `package_source` is MANUAL or HYBRID - inferred-via-source signal.
 */
export function isManualPackage(row: TapeRowLike | null | undefined): boolean {
  if (!row) return false;
  if (row.manual_link_id) return true;
  if (row.manual_package_id) return true;
  const source = row.package_source?.toUpperCase?.();
  return source === 'MANUAL' || source === 'HYBRID';
}
