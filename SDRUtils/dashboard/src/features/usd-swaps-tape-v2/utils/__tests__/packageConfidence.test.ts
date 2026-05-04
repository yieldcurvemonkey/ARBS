import { describe, expect, it } from '@jest/globals'
import type { UsdSwapTapeLeg, UsdSwapTapeRow } from '../../types'
import { computePackageConfidence } from '../packageConfidence'

const baseRow = (overrides: Partial<UsdSwapTapeRow> = {}): UsdSwapTapeRow =>
  ({
    package_id: 'P1',
    package_type: 'OUTRIGHT',
    package_indicator: null,
    n_package_legs: 1,
    legs_count: 1,
    legs_json: [],
    package_metrics: {},
    ...overrides,
  }) as UsdSwapTapeRow

describe('computePackageConfidence — OUTRIGHT', () => {
  it('returns 2/2 for a vanilla outright with no package indicator', () => {
    const result = computePackageConfidence(baseRow())
    expect(result.score).toBe(2)
    expect(result.total).toBe(2)
    expect(result.tone).toBe('info')
    expect(result.signals.map((s) => s.name)).toEqual([
      'package_indicator_off',
      'leg_count',
    ])
    expect(result.signals.every((s) => s.passed)).toBe(true)
  })
})

const curveLeg = (overrides: Partial<UsdSwapTapeLeg>): UsdSwapTapeLeg =>
  ({
    trade_id: 'T',
    tenor_years: 5,
    risk: 0,
    fixed_rate: 0,
    notional: 100_000_000,
    ...overrides,
  }) as UsdSwapTapeLeg

describe('computePackageConfidence — CURVE', () => {
  const curveRow = (overrides: Partial<UsdSwapTapeRow> = {}): UsdSwapTapeRow =>
    baseRow({
      package_type: 'CURVE',
      package_indicator: true,
      n_package_legs: 2,
      package_transaction_spread: 50,
      legs_json: [
        curveLeg({ tenor_years: 5, risk: -5_000, fixed_rate: 3.5 }),
        curveLeg({ tenor_years: 10, risk: 5_000, fixed_rate: 4.0 }),
      ],
      ...overrides,
    })

  it('returns 5/5 for a textbook 5s10s with PTS=50', () => {
    const result = computePackageConfidence(curveRow())
    expect(result.score).toBe(5)
    expect(result.total).toBe(5)
    expect(result.tone).toBe('high')
  })

  it('fails risk balance when belly-leg DV01 imbalanced > 10%', () => {
    const result = computePackageConfidence(
      curveRow({
        legs_json: [
          curveLeg({ tenor_years: 5, risk: -2_000, fixed_rate: 3.5 }),
          curveLeg({ tenor_years: 10, risk: 5_000, fixed_rate: 4.0 }),
        ],
      }),
    )
    expect(result.score).toBe(4)
    expect(
      result.signals.find((s) => s.name === 'risk_balance')?.passed,
    ).toBe(false)
  })

  it('fails PTS match when derived spread is more than 0.5 bp off', () => {
    const result = computePackageConfidence(
      curveRow({
        package_transaction_spread: 50,
        legs_json: [
          curveLeg({ tenor_years: 5, risk: -5_000, fixed_rate: 3.5 }),
          // 4.01 - 3.5 = 0.51% = 51 bp — 1 bp off reported 50.
          curveLeg({ tenor_years: 10, risk: 5_000, fixed_rate: 4.01 }),
        ],
      }),
    )
    expect(result.score).toBe(4)
    expect(result.signals.find((s) => s.name === 'pts_match')?.passed).toBe(false)
  })

  it('fails leg count when 3 legs are stamped CURVE', () => {
    const result = computePackageConfidence(
      curveRow({
        n_package_legs: 3,
        legs_json: [
          curveLeg({ tenor_years: 2, risk: -2_500, fixed_rate: 3.0 }),
          curveLeg({ tenor_years: 5, risk: -2_500, fixed_rate: 3.5 }),
          curveLeg({ tenor_years: 10, risk: 5_000, fixed_rate: 4.0 }),
        ],
      }),
    )
    expect(result.signals.find((s) => s.name === 'leg_count')?.passed).toBe(false)
  })

  it('fails tenor monotonicity when legs are not ascending', () => {
    const result = computePackageConfidence(
      curveRow({
        legs_json: [
          curveLeg({ tenor_years: 10, risk: -5_000, fixed_rate: 4.0 }),
          curveLeg({ tenor_years: 5, risk: 5_000, fixed_rate: 3.5 }),
        ],
      }),
    )
    expect(
      result.signals.find((s) => s.name === 'tenor_monotonic')?.passed,
    ).toBe(false)
  })
})

describe('computePackageConfidence — FLY', () => {
  const flyRow = (overrides: Partial<UsdSwapTapeRow> = {}): UsdSwapTapeRow =>
    baseRow({
      package_type: 'FLY',
      package_indicator: true,
      n_package_legs: 3,
      // 2*3.85 - 3.50 - 4.00 = 0.20% = 20 bp.
      package_transaction_spread: 20,
      legs_json: [
        curveLeg({ tenor_years: 5, risk: -2_500, fixed_rate: 3.5 }),
        curveLeg({ tenor_years: 10, risk: 5_000, fixed_rate: 3.85 }),
        curveLeg({ tenor_years: 30, risk: -2_500, fixed_rate: 4.0 }),
      ],
      ...overrides,
    })

  it('returns 5/5 for a textbook 5/10/30 fly', () => {
    const result = computePackageConfidence(flyRow())
    expect(result.score).toBe(5)
    expect(result.total).toBe(5)
    expect(result.tone).toBe('high')
  })

  it('passes fly risk balance when belly risk is 2x either equal wing by magnitude', () => {
    const result = computePackageConfidence(
      flyRow({
        package_transaction_spread: -0.0758,
        legs_json: [
          curveLeg({ tenor_years: 2, risk: 50_000, fixed_rate: 3.642 }),
          curveLeg({ tenor_years: 5, risk: 100_000, fixed_rate: 3.660 }),
          curveLeg({ tenor_years: 7, risk: 50_000, fixed_rate: 3.753 }),
        ],
      }),
    )
    expect(result.score).toBe(5)
    expect(result.total).toBe(5)
    expect(result.signals.find((s) => s.name === 'risk_balance')?.passed).toBe(true)
  })

  it('fails belly = -2*wings when belly DV01 is off by 25%', () => {
    const result = computePackageConfidence(
      flyRow({
        legs_json: [
          curveLeg({ tenor_years: 5, risk: -2_500, fixed_rate: 3.5 }),
          // belly under-weighted: should be 5000, given 3750
          curveLeg({ tenor_years: 10, risk: 3_750, fixed_rate: 3.85 }),
          curveLeg({ tenor_years: 30, risk: -2_500, fixed_rate: 4.0 }),
        ],
      }),
    )
    expect(result.score).toBe(4)
    expect(
      result.signals.find((s) => s.name === 'risk_balance')?.passed,
    ).toBe(false)
  })

  it('fails PTS match when derived bfly is 0.8 bp off reported PTS', () => {
    const result = computePackageConfidence(
      flyRow({
        package_transaction_spread: 20,
        legs_json: [
          curveLeg({ tenor_years: 5, risk: -2_500, fixed_rate: 3.5 }),
          // 2*3.854 - 3.5 - 4.0 = 0.208% = 20.8 bp; off by 0.8 bp.
          curveLeg({ tenor_years: 10, risk: 5_000, fixed_rate: 3.854 }),
          curveLeg({ tenor_years: 30, risk: -2_500, fixed_rate: 4.0 }),
        ],
      }),
    )
    expect(result.signals.find((s) => s.name === 'pts_match')?.passed).toBe(false)
  })

  it('fails leg count when only 2 legs are stamped FLY', () => {
    const result = computePackageConfidence(
      flyRow({
        n_package_legs: 2,
        legs_json: [
          curveLeg({ tenor_years: 5, risk: -5_000, fixed_rate: 3.5 }),
          curveLeg({ tenor_years: 10, risk: 5_000, fixed_rate: 3.85 }),
        ],
      }),
    )
    expect(result.signals.find((s) => s.name === 'leg_count')?.passed).toBe(false)
  })
})

describe('computePackageConfidence — SPREADOVER', () => {
  it('returns 3/3 when indicator on, has_spread true, PTS non-zero', () => {
    const result = computePackageConfidence(
      baseRow({
        package_type: 'SPREADOVER',
        package_indicator: true,
        has_spread: true,
        package_transaction_spread: 12,
        n_package_legs: 1,
        legs_json: [curveLeg({ tenor_years: 5 })],
      }),
    )
    expect(result.score).toBe(3)
    expect(result.total).toBe(3)
  })

  it('fails PTS-non-zero signal when PTS is missing', () => {
    const result = computePackageConfidence(
      baseRow({
        package_type: 'SPREADOVER',
        package_indicator: true,
        has_spread: true,
        package_transaction_spread: null,
        n_package_legs: 1,
        legs_json: [curveLeg({ tenor_years: 5 })],
      }),
    )
    expect(result.signals.find((s) => s.name === 'pts_present')?.passed).toBe(false)
  })
})

describe('computePackageConfidence — MATCHED_MATURITY', () => {
  it('returns 3/3 when legs share maturity and rate indices differ', () => {
    const result = computePackageConfidence(
      baseRow({
        package_type: 'MATCHED_MATURITY',
        package_indicator: true,
        n_package_legs: 2,
        legs_json: [
          curveLeg({
            tenor_years: 10,
            swap_maturity_date: '2036-05-01',
            rate_index_clean: 'USD-SOFR',
          }),
          curveLeg({
            tenor_years: 10,
            swap_maturity_date: '2036-05-01',
            rate_index_clean: 'USD-LIBOR',
          }),
        ],
      }),
    )
    expect(result.score).toBe(3)
    expect(result.total).toBe(3)
  })

  it('fails same-maturity when leg maturities differ', () => {
    const result = computePackageConfidence(
      baseRow({
        package_type: 'MATCHED_MATURITY',
        package_indicator: true,
        n_package_legs: 2,
        legs_json: [
          curveLeg({
            tenor_years: 10,
            swap_maturity_date: '2036-05-01',
            rate_index_clean: 'USD-SOFR',
          }),
          curveLeg({
            tenor_years: 10,
            swap_maturity_date: '2037-05-01',
            rate_index_clean: 'USD-LIBOR',
          }),
        ],
      }),
    )
    expect(result.signals.find((s) => s.name === 'same_maturity')?.passed).toBe(false)
  })
})

describe('computePackageConfidence — composite types', () => {
  it('SPREADOVER_FLY uses FLY signals + per-leg PTP/PTS presence', () => {
    const result = computePackageConfidence(
      baseRow({
        package_type: 'SPREADOVER_FLY',
        package_indicator: true,
        n_package_legs: 3,
        package_transaction_spread: 20,
        legs_json: [
          {
            ...curveLeg({ tenor_years: 5, risk: -2_500, fixed_rate: 3.5 }),
            package_transaction_spread: 12,
          } as any,
          {
            ...curveLeg({ tenor_years: 10, risk: 5_000, fixed_rate: 3.85 }),
            package_transaction_spread: 14,
          } as any,
          {
            ...curveLeg({ tenor_years: 30, risk: -2_500, fixed_rate: 4.0 }),
            package_transaction_spread: 16,
          } as any,
        ],
      }),
    )
    expect(result.total).toBe(6)
    expect(result.score).toBe(6)
    expect(result.signals.find((s) => s.name === 'per_leg_pts_present')?.passed).toBe(true)
  })

  it('MATCHED_MATURITY_CURVE uses CURVE signals + same-maturity-per-leg', () => {
    const result = computePackageConfidence(
      baseRow({
        package_type: 'MATCHED_MATURITY_CURVE',
        package_indicator: true,
        n_package_legs: 2,
        package_transaction_spread: 50,
        legs_json: [
          {
            ...curveLeg({ tenor_years: 5, risk: -5_000, fixed_rate: 3.5 }),
            swap_maturity_date: '2031-05-01',
          } as any,
          {
            ...curveLeg({ tenor_years: 10, risk: 5_000, fixed_rate: 4.0 }),
            swap_maturity_date: '2036-05-01',
          } as any,
        ],
      }),
    )
    // Base CURVE has 5 signals; composite adds 1 (per-leg matched-maturity check
    // — passes here because each leg's maturity matches its own tenor).
    expect(result.total).toBe(6)
  })
})

describe('computePackageConfidence — maturity-convention types', () => {
  it.each(['MAC', 'IMM', 'FOMC'])(
    'treats %s as OUTRIGHT (informational, 2/2)',
    (kind) => {
      const result = computePackageConfidence(
        baseRow({
          package_type: kind as any,
          package_indicator: false,
          n_package_legs: 1,
          legs_json: [curveLeg({ tenor_years: 5 })],
        }),
      )
      expect(result.tone).toBe('info')
      expect(result.score).toBe(2)
      expect(result.total).toBe(2)
    },
  )
})

describe('computePackageConfidence — tolerance override', () => {
  it('passes a 0.8 bp PTS miss when ptsMatchBp tolerance is loosened to 1', () => {
    const row = baseRow({
      package_type: 'CURVE',
      package_indicator: true,
      n_package_legs: 2,
      package_transaction_spread: 50,
      legs_json: [
        curveLeg({ tenor_years: 5, risk: -5_000, fixed_rate: 3.5 }),
        curveLeg({ tenor_years: 10, risk: 5_000, fixed_rate: 4.008 }),
      ],
    })
    const tight = computePackageConfidence(row)
    expect(tight.signals.find((s) => s.name === 'pts_match')?.passed).toBe(false)
    const loose = computePackageConfidence(row, { ptsMatchBp: 1.0 })
    expect(loose.signals.find((s) => s.name === 'pts_match')?.passed).toBe(true)
  })
})

describe('computePackageConfidence — sub-bp PTS detail rendering', () => {
  it('renders sub-bp PTS values without collapsing them to 0.00', () => {
    const row = baseRow({
      package_type: 'CURVE',
      package_indicator: true,
      n_package_legs: 2,
      package_transaction_spread: 0.0000125,
      legs_json: [
        curveLeg({ tenor_years: 5, risk: -5_000, fixed_rate: 0.035 }),
        curveLeg({ tenor_years: 10, risk: 5_000, fixed_rate: 0.0350001 }),
      ],
    })
    const result = computePackageConfidence(row)
    const ptsSig = result.signals.find((s) => s.name === 'pts_match')
    expect(ptsSig).toBeDefined()
    // No "0.00" collapse — must contain a non-zero precision marker.
    expect(ptsSig!.detail).not.toMatch(/derived 0\.00bp/)
    // Reported PTS rendered with at least 4 sig figs OR scientific.
    expect(ptsSig!.detail).toMatch(/0\.0000125|1\.250e-5/)
  })
})

describe('computePackageConfidence — inferredType override (SPREADOVER → base)', () => {
  const flyLeg = (overrides: Partial<UsdSwapTapeLeg>): UsdSwapTapeLeg =>
    curveLeg({ ...overrides })

  it('SPREADOVER_FLY collapses to FLY when every per-leg PTS = package PTS', () => {
    const result = computePackageConfidence(
      baseRow({
        package_type: 'SPREADOVER_FLY',
        package_indicator: true,
        n_package_legs: 3,
        package_transaction_spread: 0.0000125,
        legs_json: [
          {
            ...flyLeg({ tenor_years: 8, risk: -1_500, fixed_rate: 0.03795 }),
            package_transaction_spread: 0.0000125,
          } as any,
          {
            ...flyLeg({ tenor_years: 9, risk: 3_000, fixed_rate: 0.03841 }),
            package_transaction_spread: 0.0000125,
          } as any,
          {
            ...flyLeg({ tenor_years: 10, risk: -1_500, fixed_rate: 0.03886 }),
            package_transaction_spread: 0.0000125,
          } as any,
        ],
      }),
    )
    expect(result.inferredType).toBe('FLY')
    expect(result.inferredTypeReason).toContain('per-leg PTS')
    expect(
      result.signals.find((s) => s.name === 'inferred_base_type')?.passed,
    ).toBe(true)
  })

  it('SPREADOVER_CURVE collapses to CURVE when every per-leg PTS = package PTS', () => {
    const result = computePackageConfidence(
      baseRow({
        package_type: 'SPREADOVER_CURVE',
        package_indicator: true,
        n_package_legs: 2,
        package_transaction_spread: 0.5,
        legs_json: [
          {
            ...flyLeg({ tenor_years: 5, risk: -5_000, fixed_rate: 3.5 }),
            package_transaction_spread: 0.5,
          } as any,
          {
            ...flyLeg({ tenor_years: 10, risk: 5_000, fixed_rate: 4.0 }),
            package_transaction_spread: 0.5,
          } as any,
        ],
      }),
    )
    expect(result.inferredType).toBe('CURVE')
  })

  it('does NOT trigger when per-leg PTS values diverge from package PTS', () => {
    const result = computePackageConfidence(
      baseRow({
        package_type: 'SPREADOVER_CURVE',
        package_indicator: true,
        n_package_legs: 2,
        package_transaction_spread: 0.5,
        legs_json: [
          {
            ...flyLeg({ tenor_years: 5, risk: -5_000, fixed_rate: 3.5 }),
            package_transaction_spread: 0.5,
          } as any,
          {
            ...flyLeg({ tenor_years: 10, risk: 5_000, fixed_rate: 4.0 }),
            // UST hedge leg PTS differs — genuine spreadover.
            package_transaction_spread: 12.4,
          } as any,
        ],
      }),
    )
    expect(result.inferredType).toBeNull()
    expect(result.inferredTypeReason).toBeNull()
  })

  it('does NOT trigger for plain FLY / CURVE / SPREADOVER (only SPREADOVER_FLY/CURVE)', () => {
    for (const t of ['FLY', 'CURVE', 'SPREADOVER', 'OUTRIGHT']) {
      const result = computePackageConfidence(
        baseRow({
          package_type: t as any,
          package_indicator: t === 'OUTRIGHT' ? false : true,
          n_package_legs: t === 'FLY' ? 3 : t === 'OUTRIGHT' ? 1 : 2,
          package_transaction_spread: 0.5,
          legs_json: [],
        }),
      )
      expect(result.inferredType).toBeNull()
    }
  })

  it('does NOT trigger when a per-leg PTS is missing', () => {
    const result = computePackageConfidence(
      baseRow({
        package_type: 'SPREADOVER_FLY',
        package_indicator: true,
        n_package_legs: 3,
        package_transaction_spread: 0.0000125,
        legs_json: [
          {
            ...flyLeg({ tenor_years: 8 }),
            package_transaction_spread: 0.0000125,
          } as any,
          {
            ...flyLeg({ tenor_years: 9 }),
            // Missing per-leg PTS.
          } as any,
          {
            ...flyLeg({ tenor_years: 10 }),
            package_transaction_spread: 0.0000125,
          } as any,
        ],
      }),
    )
    expect(result.inferredType).toBeNull()
  })

  it('triggers when every per-leg PTS matches package PTS at a clean 100× scale (decimal/percent unit mismatch)', () => {
    // Package PTS recorded in one unit (e.g. bps form, 0.00125),
    // per-leg PTS recorded in another (e.g. decimal, 0.0000125) —
    // they're the same underlying value, just unit-misencoded.
    const result = computePackageConfidence(
      baseRow({
        package_type: 'SPREADOVER_FLY',
        package_indicator: true,
        n_package_legs: 3,
        package_transaction_spread: 0.00125,
        legs_json: [
          {
            ...flyLeg({ tenor_years: 8 }),
            package_transaction_spread: 0.0000125,
          } as any,
          {
            ...flyLeg({ tenor_years: 9 }),
            package_transaction_spread: 0.0000125,
          } as any,
          {
            ...flyLeg({ tenor_years: 10 }),
            package_transaction_spread: 0.0000125,
          } as any,
        ],
      }),
    )
    expect(result.inferredType).toBe('FLY')
    expect(result.inferredTypeReason).toMatch(/0\.01× scale/)
    expect(result.inferredTypeReason).toMatch(/unit mismatch/)
  })

  it('triggers SPREADOVER_CURVE → CURVE at a 10000× scale (decimal ↔ bps)', () => {
    const result = computePackageConfidence(
      baseRow({
        package_type: 'SPREADOVER_CURVE',
        package_indicator: true,
        n_package_legs: 2,
        package_transaction_spread: 50,
        legs_json: [
          {
            ...flyLeg({ tenor_years: 5, risk: -5_000, fixed_rate: 3.5 }),
            // 0.005 decimal vs 50 bps (10000× scale)
            package_transaction_spread: 0.005,
          } as any,
          {
            ...flyLeg({ tenor_years: 10, risk: 5_000, fixed_rate: 4.0 }),
            package_transaction_spread: 0.005,
          } as any,
        ],
      }),
    )
    expect(result.inferredType).toBe('CURVE')
    expect(result.inferredTypeReason).toMatch(/× scale/)
  })

  it('does NOT trigger when per-leg PTS scale factors are inconsistent across legs', () => {
    // One leg matches at 100×, the other at 1× — that's not a unit
    // confusion, it's heterogeneous noise. Should NOT collapse.
    const result = computePackageConfidence(
      baseRow({
        package_type: 'SPREADOVER_CURVE',
        package_indicator: true,
        n_package_legs: 2,
        package_transaction_spread: 0.5,
        legs_json: [
          {
            ...flyLeg({ tenor_years: 5 }),
            package_transaction_spread: 0.5,
          } as any,
          {
            ...flyLeg({ tenor_years: 10 }),
            package_transaction_spread: 0.005,
          } as any,
        ],
      }),
    )
    expect(result.inferredType).toBeNull()
  })

  it('does NOT trigger when no clean order-of-magnitude scale fits', () => {
    // 7× isn't in the allowed scale list — that's just divergence.
    const result = computePackageConfidence(
      baseRow({
        package_type: 'SPREADOVER_FLY',
        package_indicator: true,
        n_package_legs: 3,
        package_transaction_spread: 0.7,
        legs_json: [
          {
            ...flyLeg({ tenor_years: 8 }),
            package_transaction_spread: 0.1,
          } as any,
          {
            ...flyLeg({ tenor_years: 9 }),
            package_transaction_spread: 0.1,
          } as any,
          {
            ...flyLeg({ tenor_years: 10 }),
            package_transaction_spread: 0.1,
          } as any,
        ],
      }),
    )
    expect(result.inferredType).toBeNull()
  })
})

describe('computePackageConfidence — pts_match scale-aware', () => {
  const flyRow = (overrides: Partial<UsdSwapTapeRow> = {}): UsdSwapTapeRow =>
    baseRow({
      package_type: 'FLY',
      package_indicator: true,
      n_package_legs: 3,
      legs_json: [
        curveLeg({ tenor_years: 5, risk: -2_500, fixed_rate: 3.5 }),
        curveLeg({ tenor_years: 10, risk: 5_000, fixed_rate: 3.85 }),
        curveLeg({ tenor_years: 30, risk: -2_500, fixed_rate: 4.0 }),
      ],
      ...overrides,
    })

  it('passes pts_match when derived bps and reported PTS differ by exactly 100× (scale-aware)', () => {
    // derived bfly = (2*3.85 - 3.5 - 4.0) * 100 = 20 bps.
    // reported PTS in decimal-form = 0.2 — 100× scale.
    const result = computePackageConfidence(
      flyRow({ package_transaction_spread: 0.2 }),
    )
    const sig = result.signals.find((s) => s.name === 'pts_match')
    expect(sig).toBeDefined()
    expect(sig!.passed).toBe(true)
    expect(sig!.detail).toMatch(/× scale/)
    expect(sig!.detail).toMatch(/unit mismatch/)
  })

  it('still passes pts_match when derived and reported are in the same unit (no scale annotation)', () => {
    const result = computePackageConfidence(
      flyRow({ package_transaction_spread: 20 }),
    )
    const sig = result.signals.find((s) => s.name === 'pts_match')
    expect(sig!.passed).toBe(true)
    expect(sig!.detail).not.toMatch(/× scale/)
    expect(sig!.detail).not.toMatch(/unit mismatch/)
  })

  it('passes pts_match across a one-order PTS scale mismatch', () => {
    const result = computePackageConfidence(
      flyRow({ package_transaction_spread: 2 }),
    )
    const sig = result.signals.find((s) => s.name === 'pts_match')
    expect(sig!.passed).toBe(true)
    expect(sig!.detail).toMatch(/10.*scale/)
  })

  it('derives bp correctly when fixed_rate legs arrive as decimal rates', () => {
    const result = computePackageConfidence(
      baseRow({
        package_type: 'FLY',
        package_indicator: true,
        n_package_legs: 3,
        package_transaction_spread: 0.0000125,
        legs_json: [
          curveLeg({ tenor_years: 8, risk: -1_500, fixed_rate: 0.03795 }),
          curveLeg({ tenor_years: 9, risk: 3_000, fixed_rate: 0.0384125 }),
          curveLeg({ tenor_years: 10, risk: -1_500, fixed_rate: 0.0388625 }),
        ],
      }),
    )
    const sig = result.signals.find((s) => s.name === 'pts_match')
    expect(sig!.passed).toBe(true)
    expect(sig!.detail).toMatch(/derived 0\.125bp/)
    expect(sig!.detail).toMatch(/10000.*scale/)
  })

  it('still fails pts_match when derived and reported diverge by a non-power-of-10 ratio', () => {
    // derived = 20 bps, reported = 7 — ratio 20/7 ≈ 2.86, no scale fits.
    const result = computePackageConfidence(
      flyRow({ package_transaction_spread: 7 }),
    )
    const sig = result.signals.find((s) => s.name === 'pts_match')
    expect(sig!.passed).toBe(false)
  })
})
