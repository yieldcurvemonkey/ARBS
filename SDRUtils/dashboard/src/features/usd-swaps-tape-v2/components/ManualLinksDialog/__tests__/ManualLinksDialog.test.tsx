// ABOUTME: Source-level pin that the v2 ManualLinksDialog mounts the
// shared useManualLinkForm + ManualLinkValidationList +
// ManualLinkMetricsTable. The actual validate/create network flow is
// exercised by the api wrapper / form-hook tests.
import { describe, expect, it } from '@jest/globals';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const source = readFileSync(
  resolve(
    process.cwd(),
    'src/features/usd-swaps-tape-v2/components/ManualLinksDialog/ManualLinksDialog.tsx',
  ),
  'utf8',
);

describe('v2 ManualLinksDialog — shared module wiring', () => {
  it('imports useManualLinkForm from the shared module', () => {
    expect(source).toMatch(
      /import\s+\{[^}]*useManualLinkForm[^}]*\}\s+from\s+['"]@\/lib\/manual-links-ui[^'"]*['"]/,
    );
  });

  it('imports ManualLinkValidationList from the shared module', () => {
    expect(source).toMatch(
      /import\s+\{[^}]*ManualLinkValidationList[^}]*\}\s+from\s+['"]@\/lib\/manual-links-ui[^'"]*['"]/,
    );
  });

  it('imports ManualLinkMetricsTable from the shared module', () => {
    expect(source).toMatch(
      /import\s+\{[^}]*ManualLinkMetricsTable[^}]*\}\s+from\s+['"]@\/lib\/manual-links-ui[^'"]*['"]/,
    );
  });

  it('passes the v2 base path into the shared form hook', () => {
    expect(source).toMatch(/basePath:\s*V2_LINKS_BASE/);
  });

  it('renders the validation list when form.validation has entries', () => {
    expect(source).toMatch(/<ManualLinkValidationList\b/);
  });

  it('renders the metrics table when form.metrics is set', () => {
    expect(source).toMatch(/<ManualLinkMetricsTable\b/);
  });

  it('uses form.handleCreate inside the submit handler', () => {
    expect(source).toMatch(/form\.handleCreate\(/);
  });

  it('exposes a Re-validate button wired to form.validateLink()', () => {
    expect(source).toMatch(/form\.validateLink\(\)/);
  });

  it('disables the submit when validation has errors', () => {
    expect(source).toMatch(/hasValidationErrors/);
    expect(source).toMatch(/v\.status === 'error'/);
  });
});
