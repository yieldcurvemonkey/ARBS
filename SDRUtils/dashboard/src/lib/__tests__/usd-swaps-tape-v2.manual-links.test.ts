// ABOUTME: Pin that the v2 tape display projection includes the
// manual-link metadata columns. The columns flow from the upstream
// view (arbs_usd_swap_tape_display_v2), which is materialised by
// ingest_usdswaps_tape. The SELECT list in usd-swaps-tape-v2.ts
// intersects with information_schema.columns at runtime so deploys
// tolerate lagging ingests, but the *intended* projection must always
// list every manual-link field so badges + the detail modal can
// hydrate as soon as the view exposes them.
import { describe, expect, it } from '@jest/globals';
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
    'd.manual_link_id',
    'd.manual_package_id',
    'd.link_created_by',
    'd.link_created_at',
    'd.user_comment',
    'd.link_reason',
    'd.tags',
    'd.link_metrics',
  ];

  for (const col of REQUIRED_COLUMNS) {
    it(`projects ${col} into the tape SELECT list`, () => {
      // Each column appears in the COLUMNS array as a quoted string.
      const escaped = col.replace(/[.]/g, '\\.');
      expect(source).toMatch(new RegExp(`['"]${escaped}['"]`));
    });
  }

  it('uses the v2 display view (TAPE_DISPLAY_VIEW) as the FROM source', () => {
    // The display view is sourced from the route.logic.ts constant so a
    // rollback flips one place; we verify the import path here.
    expect(source).toMatch(/TAPE_DISPLAY_VIEW/);
    expect(source).toMatch(/from\s+['"]@\/app\/api\/usd-swaps-tape-v2\/route\.logic['"]/);
  });
});
