import { describe, expect, it } from '@jest/globals'
import { __test_helpers } from '../TapeLabelCell'

describe('TapeLabelCell helpers', () => {
  it('indexTone maps SOFR to emerald', () => {
    expect(__test_helpers.indexTone('SOFR')).toContain('emerald')
  })

  it('indexTone maps FED_FUNDS to amber', () => {
    expect(__test_helpers.indexTone('FED_FUNDS')).toContain('amber')
  })

  it('indexTone falls back to slate for unknowns', () => {
    expect(__test_helpers.indexTone('OTHER')).toContain('slate')
    expect(__test_helpers.indexTone(null)).toContain('slate')
  })

  it('structureOf prefers package_structure over package_type', () => {
    const row: any = { package_structure: '2Y/5Y Curve', package_type: 'CURVE' }
    expect(__test_helpers.structureOf(row)).toBe('2Y/5Y Curve')
  })

  it('structureOf falls back to package_type', () => {
    const row: any = { package_structure: null, package_type: 'OUTRIGHT' }
    expect(__test_helpers.structureOf(row)).toBe('OUTRIGHT')
  })
})
