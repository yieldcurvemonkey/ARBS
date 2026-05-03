import { describe, expect, it } from '@jest/globals'
import { sampleMatchesSimilarity } from '../route'

describe('rarity similarity matching', () => {
  it('ignores size tolerance when focused notional is unavailable', () => {
    expect(
      sampleMatchesSimilarity(
        { fixed_rate: 0.03875, notional: 1_000_000_000 },
        {
          focusedRateBps: 387.5,
          primaryTol: 0.1,
          focusedNotional: Number.NaN,
          sizeTolPct: 0.25,
        },
      ),
    ).toBe(true)
  })

  it('applies the configured size tolerance when focused notional is available', () => {
    const opts = {
      focusedRateBps: 387.5,
      primaryTol: 0.1,
      focusedNotional: 100_000_000,
      sizeTolPct: 0.25,
    }

    expect(sampleMatchesSimilarity({ fixed_rate: 0.03875, notional: 120_000_000 }, opts)).toBe(true)
    expect(sampleMatchesSimilarity({ fixed_rate: 0.03875, notional: 140_000_000 }, opts)).toBe(false)
  })
})
