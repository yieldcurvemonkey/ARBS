// ABOUTME: Tests for the groupLinkedRows clustering helper.
import { describe, expect, it } from '@jest/globals';
import { groupLinkedRows } from '../grouping';

type Row = {
  id: string;
  manual_package_id?: string | null;
  manual_link_id?: string | null;
};

describe('groupLinkedRows', () => {
  it('returns rows unchanged when there are no linked rows', () => {
    const rows: Row[] = [{ id: 'a' }, { id: 'b' }, { id: 'c' }];
    expect(groupLinkedRows(rows)).toEqual(rows);
  });

  it('clusters rows by manual_package_id while preserving the source order within a group', () => {
    const rows: Row[] = [
      { id: 'a', manual_package_id: 'P1' },
      { id: 'b' },
      { id: 'c', manual_package_id: 'P1' },
      { id: 'd' },
      { id: 'e', manual_package_id: 'P2' },
      { id: 'f', manual_package_id: 'P2' },
    ];
    const result = groupLinkedRows(rows);
    // First cluster (P1) emitted at the position of its first occurrence.
    expect(result.map((r) => r.id)).toEqual(['a', 'c', 'b', 'd', 'e', 'f']);
  });

  it('falls back to manual_link_id when manual_package_id is absent', () => {
    const rows: Row[] = [
      { id: 'a', manual_link_id: 'L1' },
      { id: 'b' },
      { id: 'c', manual_link_id: 'L1' },
    ];
    const result = groupLinkedRows(rows);
    expect(result.map((r) => r.id)).toEqual(['a', 'c', 'b']);
  });

  it('ungrouped rows pass through in original order around clusters', () => {
    const rows: Row[] = [
      { id: 'a' },
      { id: 'b', manual_package_id: 'P1' },
      { id: 'c' },
      { id: 'd', manual_package_id: 'P1' },
    ];
    const result = groupLinkedRows(rows);
    // Source-order traversal: 'a' (ungrouped) -> 'b' first hit of P1 emits
    // [b, d] -> 'c' (ungrouped) passes through -> 'd' already emitted skip.
    expect(result.map((r) => r.id)).toEqual(['a', 'b', 'd', 'c']);
  });

  it('handles multiple groups in interleaved order anchored by first occurrence', () => {
    const rows: Row[] = [
      { id: 'a', manual_package_id: 'P1' },
      { id: 'b', manual_package_id: 'P2' },
      { id: 'c', manual_package_id: 'P1' },
      { id: 'd', manual_package_id: 'P2' },
    ];
    expect(groupLinkedRows(rows).map((r) => r.id)).toEqual(['a', 'c', 'b', 'd']);
  });

  it('empty array returns empty array', () => {
    expect(groupLinkedRows([])).toEqual([]);
  });
});
