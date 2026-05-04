// ABOUTME: Tests for the deterministic linkId -> HSL colour helper.
import { describe, expect, it } from '@jest/globals';
import { manualLinkColor } from '../color';

describe('manualLinkColor', () => {
  it('returns same colour for same input across runs', () => {
    expect(manualLinkColor('link-abc')).toBe(manualLinkColor('link-abc'));
  });

  it('returns different colours for different inputs', () => {
    expect(manualLinkColor('a')).not.toBe(manualLinkColor('b'));
  });

  it('returns valid HSL format for non-empty inputs', () => {
    expect(manualLinkColor('x')).toMatch(/^hsl\(\d+, \d+%, \d+%\)$/);
  });

  it('returns null for empty / falsy inputs (preserves swaptions behaviour)', () => {
    expect(manualLinkColor('')).toBeNull();
    expect(manualLinkColor(null)).toBeNull();
    expect(manualLinkColor(undefined)).toBeNull();
  });

  it('produces values across the hue space for a sample of 100 ids', () => {
    const hues = new Set<number>();
    for (let i = 0; i < 100; i += 1) {
      const colour = manualLinkColor(`link-${i}`);
      expect(colour).not.toBeNull();
      const match = (colour as string).match(/^hsl\((\d+), /);
      expect(match).not.toBeNull();
      hues.add(Number((match as RegExpMatchArray)[1]));
    }
    // We don't require uniformity (hash collisions are fine), just non-trivial spread.
    expect(hues.size).toBeGreaterThan(20);
  });

  it('uses the same hashing scheme as the prior swaptions implementation', () => {
    // Reproduce the original swaptions formula inline to pin behaviour.
    function legacy(linkId: string): string | null {
      if (!linkId) return null;
      let hash = 0;
      for (let i = 0; i < linkId.length; i += 1) {
        hash = (hash * 31 + linkId.charCodeAt(i)) % 360;
      }
      return `hsl(${hash}, 65%, 52%)`;
    }
    const samples = ['abc', 'xyz', 'PKG-2026-AAAA', 'long-link-id-123456'];
    for (const s of samples) {
      expect(manualLinkColor(s)).toBe(legacy(s));
    }
  });
});
