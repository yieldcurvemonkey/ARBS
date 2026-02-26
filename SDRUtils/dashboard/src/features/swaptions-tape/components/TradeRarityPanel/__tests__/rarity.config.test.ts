import { describe, expect, it } from '@jest/globals';
import fs from 'fs';
import path from 'path';
import { KNOWN_PACKAGE_TYPES, STRUCTURE_ANALYTICS_CONFIG } from '../rarity.config';

describe('rarity.config', () => {
  it('has configs for all known package types', () => {
    KNOWN_PACKAGE_TYPES.forEach((packageType) => {
      expect(STRUCTURE_ANALYTICS_CONFIG[packageType]).toBeDefined();
    });
  });

  it('primary metrics are marked as primary', () => {
    Object.values(STRUCTURE_ANALYTICS_CONFIG).forEach((config) => {
      expect(config.primaryMetric.primary).toBe(true);
      expect(config.primaryMetric.key.length).toBeGreaterThan(0);
    });
  });

  it('registers DELTA_HEDGE with primary diagnostics', () => {
    expect(KNOWN_PACKAGE_TYPES).toContain('DELTA_HEDGE');
    const config = STRUCTURE_ANALYTICS_CONFIG.DELTA_HEDGE;
    expect(config).toBeDefined();
    expect(config.primaryMetric.key).toBe('delta_hedge_implied_delta');
    const secondaryKeys = config.secondaryMetrics.map((metric) => metric.key);
    expect(secondaryKeys).toContain('delta_hedge_dv01_ratio');
  });

  it('renders DELTA_HEDGE package badge marker in tape component', () => {
    const tapePath = path.resolve(
      process.cwd(),
      'src/features/swaptions-tape/components/SwaptionTradeTape.tsx',
    );
    const source = fs.readFileSync(tapePath, 'utf8');
    expect(source).toContain('DELTA_HEDGE');
    expect(source).toContain('?');
  });

  it('includes synthetic hedge fallback row copy in tape component', () => {
    const tapePath = path.resolve(
      process.cwd(),
      'src/features/swaptions-tape/components/SwaptionTradeTape.tsx',
    );
    const source = fs.readFileSync(tapePath, 'utf8');
    expect(source).toContain('hedge details unavailable');
    expect(source).toContain('Hedge Swap');
  });
});
