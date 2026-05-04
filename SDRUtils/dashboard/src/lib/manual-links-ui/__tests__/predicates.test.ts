// ABOUTME: Tests for the isManualPackage predicate.
import { describe, expect, it } from '@jest/globals';
import { isManualPackage } from '../predicates';

describe('isManualPackage', () => {
  it.each([
    [{ manual_link_id: 'x' }, true],
    [{ manual_link_id: null }, false],
    [{ manual_package_id: 'p' }, true],
    [{ manual_package_id: null }, false],
    [{ package_source: 'MANUAL' }, true],
    [{ package_source: 'manual' }, true], // case-insensitive
    [{ package_source: 'HYBRID' }, true],
    [{ package_source: 'hybrid' }, true],
    [{ package_source: 'INFERRED' }, false],
    [{ package_source: 'AUTO' }, false],
    [{}, false],
    [{ manual_link_id: '' }, false],
    [{ manual_package_id: '' }, false],
  ])('returns %p for %p', (row, expected) => {
    expect(isManualPackage(row as any)).toBe(expected);
  });

  it('treats manual_link_id as authoritative even with non-manual source', () => {
    expect(isManualPackage({ manual_link_id: 'x', package_source: 'INFERRED' } as any)).toBe(true);
  });

  it('treats manual_package_id as authoritative even with no source', () => {
    expect(isManualPackage({ manual_package_id: 'p' } as any)).toBe(true);
  });
});
