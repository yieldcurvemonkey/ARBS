// ABOUTME: Source-level pin that UsdSwapsTradeTape resolves view-time
// structural overrides (applyOverrides — which itself clusters via the shared
// groupLinkedRows transform) before passing rows to the TradeTapeTable. The
// override + grouping semantics are unit-tested in
// utils/__tests__/applyOverrides.test.ts and
// lib/manual-links-ui/__tests__/grouping.test.ts; here we just confirm the
// import and the applied call.
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

describe('UsdSwapsTradeTape — override / grouping row pipeline', () => {
  it('imports applyOverrides from the feature utils module', () => {
    expect(source).toMatch(
      /import\s+\{[^}]*applyOverrides[^}]*\}\s+from\s+['"]\.\.\/utils\/applyOverrides['"]/,
    );
  });

  it('applies applyOverrides to the row stream feeding TradeTapeTable', () => {
    expect(source).toMatch(/applyOverrides\(tape\.rows\)/);
  });

  it('passes the resolved display rows (not raw tape.rows) into TradeTapeTable', () => {
    // The component renders `<TradeTapeTable rows={...} ...>`. Match
    // the rows= JSX prop and ensure it isn't bare `tape.rows` (which
    // would mean the override/grouping transform wasn't applied to the
    // rendered stream).
    expect(source).toMatch(/<TradeTapeTable\b[\s\S]{0,200}rows=\{(?!tape\.rows\s*\})/);
  });
});

describe('UsdSwapsTradeTape — manual-link detail modal wiring', () => {
  it('imports ManualLinkDetailModal from the shared module', () => {
    expect(source).toMatch(
      /import\s+\{[^}]*ManualLinkDetailModal[^}]*\}\s+from\s+['"]@\/lib\/manual-links-ui[^'"]*['"]/,
    );
  });

  it('mounts <ManualLinkDetailModal> with the v2 base path', () => {
    expect(source).toMatch(/<ManualLinkDetailModal\b/);
    expect(source).toMatch(/apiBasePath=\{V2_LINKS_BASE\}/);
  });

  it('threads onOpenManualLink down through TradeTapeTable into the columns', () => {
    expect(source).toMatch(/onOpenManualLink=\{handleOpenManualLink\}/);
  });

  it('opens the modal by setting detailLinkId and closes by nulling it', () => {
    expect(source).toMatch(/setDetailLinkId\(linkId\)/);
    expect(source).toMatch(/setDetailLinkId\(null\)/);
  });

  it('passes onUpdated and onDeactivated callbacks that refetch the tape', () => {
    expect(source).toMatch(/onUpdated=\{[\s\S]{0,200}tape\.refetch\(\)/);
    expect(source).toMatch(/onDeactivated=\{[\s\S]{0,200}tape\.refetch\(\)/);
  });

  it('binds adminPassword + savedUser inputs through the modal props', () => {
    expect(source).toMatch(/adminPassword=\{adminPassword\}/);
    expect(source).toMatch(/onAdminPasswordChange=\{setAdminPassword\}/);
    expect(source).toMatch(/currentUser=\{savedUser\}/);
    expect(source).toMatch(/onUserChange=\{setSavedUser\}/);
  });
});
