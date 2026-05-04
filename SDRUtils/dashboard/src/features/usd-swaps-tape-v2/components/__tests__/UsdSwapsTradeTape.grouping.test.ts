// ABOUTME: Source-level pin that UsdSwapsTradeTape applies the shared
// groupLinkedRows transform to its row pipeline before passing rows to
// the TradeTapeTable. The actual ordering semantics are unit-tested in
// lib/manual-links-ui/__tests__/grouping.test.ts; here we just confirm
// the import and the applied call.
import { describe, expect, it } from '@jest/globals';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const source = readFileSync(
  resolve(
    process.cwd(),
    'src/features/usd-swaps-tape-v2/components/UsdSwapsTradeTape.tsx',
  ),
  'utf8',
);

describe('UsdSwapsTradeTape — manual-link grouping', () => {
  it('imports groupLinkedRows from the shared module', () => {
    expect(source).toMatch(
      /import\s+\{[^}]*groupLinkedRows[^}]*\}\s+from\s+['"]@\/lib\/manual-links-ui[^'"]*['"]/,
    );
  });

  it('applies groupLinkedRows to the row stream feeding TradeTapeTable', () => {
    expect(source).toMatch(/groupLinkedRows\([^)]+\)/);
  });

  it('passes the grouped rows (not raw tape.rows) into TradeTapeTable', () => {
    // The component renders `<TradeTapeTable rows={...} ...>`. Match
    // the rows= JSX prop and ensure it isn't bare `tape.rows` (which
    // would mean grouping wasn't applied to the rendered stream).
    expect(source).toMatch(/<TradeTapeTable\b[\s\S]{0,200}rows=\{(?!tape\.rows\s*\})/);
  });
});
