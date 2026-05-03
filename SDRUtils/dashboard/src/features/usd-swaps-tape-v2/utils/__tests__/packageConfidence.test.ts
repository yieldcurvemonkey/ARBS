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
