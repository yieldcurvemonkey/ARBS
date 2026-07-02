// ABOUTME: Pin that the v2 tape display projection includes the
// manual-link metadata columns. With the exclusion-list architecture
// (audit C1 prevention), a column is projected if it is NOT in
// EXCLUDED_VIEW_COLUMNS — so we verify each required column is absent
// from the exclusion set rather than checking source-file literals.
import { describe, expect, it } from '@jest/globals';
import { EXCLUDED_VIEW_COLUMNS } from '../usd-swaps-tape-v2';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const source = readFileSync(
  resolve(process.cwd(), 'src/lib/usd-swaps-tape-v2.ts'),
  'utf8',
);

describe('v2 tape projection — manual-link metadata', () => {
  // Per design §1.5: every tape row should hydrate manual_link_id,
  // manual_package_id, link_created_by, link_created_at, user_comment,
  // link_reason, tags - so row-level badges + cluster grouping render
  // without a separate fetch round-trip.
  const REQUIRED_COLUMNS = [
    'manual_link_id',
    'manual_package_id',
    'link_created_by',
    'link_created_at',
    'user_comment',
    'link_reason',
    'tags',
    'link_metrics',
  ];

  for (const col of REQUIRED_COLUMNS) {
    it(`projects d.${col} into the tape SELECT list`, () => {
      // With exclusion-list projection, a column is included by default.
      // Verify the column is NOT in the exclusion set.
      expect(EXCLUDED_VIEW_COLUMNS.has(col)).toBe(false);
    });
  }

  it('uses the v2 display view (TAPE_DISPLAY_VIEW) as the FROM source', () => {
    // The display view is sourced from the route.logic.ts constant so a
    // rollback flips one place; we verify the import path here.
    expect(source).toMatch(/TAPE_DISPLAY_VIEW/);
    expect(source).toMatch(/from\s+['"]@\/app\/api\/usd-swaps-tape-v2\/route\.logic['"]/);
  });
});
