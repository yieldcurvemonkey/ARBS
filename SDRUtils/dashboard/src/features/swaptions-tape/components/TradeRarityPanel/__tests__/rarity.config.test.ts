import { describe, expect, it } from '@jest/globals';
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
});
