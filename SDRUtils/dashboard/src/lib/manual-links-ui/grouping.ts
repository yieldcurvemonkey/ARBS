// ABOUTME: Cluster manual-linked rows by manual_package_id (preferred) or
// manual_link_id so visually-related rows render contiguously in the tape.
// Ungrouped rows pass through in source order. This is a pure transform -
// it does not mutate the input.

import type { TapeRowLike } from './types';

/**
 * Reorder rows so all rows sharing a manual link / package id render as a
 * contiguous cluster. The cluster's anchor position in the output is the
 * source position of the first row in that cluster - this preserves the
 * tape's chronological intent: the cluster appears where it first showed
 * up. Ungrouped rows pass through in source order.
 *
 * Returns the original array reference unchanged when no clusters are
 * present (cheap reference-stability guarantee for downstream memos).
 */
export function groupLinkedRows<R extends TapeRowLike>(rows: readonly R[]): R[] {
  const groups = new Map<string, R[]>();
  rows.forEach((row) => {
    const linkId = row.manual_package_id || row.manual_link_id;
    if (!linkId) return;
    if (!groups.has(linkId)) {
      groups.set(linkId, []);
    }
    groups.get(linkId)?.push(row);
  });

  if (!groups.size) return rows as R[];

  const emitted = new Set<string>();
  const result: R[] = [];

  rows.forEach((row) => {
    const linkId = row.manual_package_id || row.manual_link_id;
    if (!linkId) {
      result.push(row);
      return;
    }
    if (emitted.has(linkId)) return;
    emitted.add(linkId);
    const groupRows = groups.get(linkId);
    if (groupRows) {
      result.push(...groupRows);
    }
  });

  return result;
}
