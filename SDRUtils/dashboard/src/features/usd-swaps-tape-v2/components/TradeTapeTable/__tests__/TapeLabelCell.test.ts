import { describe, expect, it } from '@jest/globals'
import { indexTone, structureOf } from '../TapeLabelCell.helpers'

describe('TapeLabelCell helpers', () => {
  it('indexTone maps SOFR to emerald', () => {
    expect(indexTone('SOFR')).toContain('emerald')
  })

  it('indexTone maps FED_FUNDS to amber', () => {
    expect(indexTone('FED_FUNDS')).toContain('amber')
  })

  it('indexTone falls back to slate for unknowns', () => {
    expect(indexTone('OTHER')).toContain('slate')
    expect(indexTone(null)).toContain('slate')
  })

  it('structureOf prefers package_structure over package_type', () => {
    const row: any = { package_structure: '2Y/5Y Curve', package_type: 'CURVE' }
    expect(structureOf(row)).toBe('2Y/5Y Curve')
  })

  it('structureOf falls back to package_type', () => {
    const row: any = { package_structure: null, package_type: 'OUTRIGHT' }
    expect(structureOf(row)).toBe('OUTRIGHT')
  })
})
