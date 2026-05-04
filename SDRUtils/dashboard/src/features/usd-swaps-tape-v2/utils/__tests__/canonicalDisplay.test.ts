import { describe, expect, it } from '@jest/globals'
import {
  canonicalDisplayLabel,
  canonicalSourceVariants,
  CANONICAL_BUCKETS,
} from '../canonicalDisplay'

describe('canonicalDisplayLabel', () => {
  it.each([
    ['USD/SOFR-OIS/COMPOUND', 'SOFR OIS'],
    ['USD/SOFR-TERM', 'Term SOFR'],
    ['USD/FED-FUNDS-OIS/COMPOUND', 'Fed Funds OIS'],
    ['USD/OBFR-OIS/COMPOUND', 'OBFR OIS'],
    ['USD/BSBY/IBOR', 'BSBY'],
    ['USD/LIBOR/IBOR', 'USD LIBOR'],
    ['USD/ISDA-CMS', 'CMS'],
    ['USD/SIFMA-MUNI', 'SIFMA Muni'],
    ['UNKNOWN', '—'],
  ])('maps %s → %s', (key, label) => {
    expect(canonicalDisplayLabel(key)).toBe(label)
  })

  it('falls back to the raw key for unrecognised inputs', () => {
    expect(canonicalDisplayLabel('USD/UNRECOGNISED-INDEX')).toBe(
      'USD/UNRECOGNISED-INDEX',
    )
  })

  it('handles basis canonical keys', () => {
    expect(canonicalDisplayLabel('USD/BASIS/SOFR-OIS+FED-FUNDS-OIS')).toBe(
      'SOFR vs Fed Funds (basis)',
    )
  })
})

describe('canonicalSourceVariants', () => {
  it('returns example SDR strings for SOFR OIS', () => {
    const variants = canonicalSourceVariants('USD/SOFR-OIS/COMPOUND')
    expect(variants).toContain('USD-SOFR-OIS Compound 1D')
    expect(variants).toContain('USD-SOFR-COMPOUND 1D Constant')
    expect(variants).toContain('USD-SOFR')
  })

  it('returns example SDR strings for Fed Funds OIS', () => {
    const variants = canonicalSourceVariants('USD/FED-FUNDS-OIS/COMPOUND')
    expect(variants).toContain('USD-Federal Funds-OIS Compound 1D')
    expect(variants).toContain('USD-Federal Funds-H.15-OIS-COMPOUND 1D')
    expect(variants).toContain('USD-FED-FUNDS-OIS')
  })

  it('returns empty list for unrecognised buckets', () => {
    expect(canonicalSourceVariants('USD/UNRECOGNISED')).toEqual([])
  })
})

describe('CANONICAL_BUCKETS', () => {
  it('exposes a stable display order for the AnalyticsPanel selector', () => {
    expect(CANONICAL_BUCKETS.map((b) => b.key)).toEqual([
      'USD/SOFR-OIS/COMPOUND',
      'USD/SOFR-TERM',
      'USD/FED-FUNDS-OIS/COMPOUND',
      'USD/OBFR-OIS/COMPOUND',
      'USD/BSBY/IBOR',
      'USD/LIBOR/IBOR',
      'USD/ISDA-CMS',
      'USD/SIFMA-MUNI',
    ])
  })
})
