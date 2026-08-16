// ABOUTME: The exact inputs Chrome showed reaching the panel, pinned.
import { describe, expect, it } from '@jest/globals'
import { structureOf } from '../IntradayPrintsPanel.helpers'

describe('structureOf on the live inputs', () => {
  it('detects the 10Y/15Y/30Y Fly the dock actually passed', () => {
    const r = structureOf({
      package_structure: '10Y/15Y/30Y Fly',
      legs_json: [
        { tenor_display: '10Y' }, { tenor_display: '15Y' }, { tenor_display: '30Y' },
      ],
    })
    expect(r).not.toBeNull()
    expect(r!.kind).toBe('FLY')
    expect(r!.tenors).toEqual(['10Y', '15Y', '30Y'])
  })

  it('detects a 10Y/30Y Curve', () => {
    const r = structureOf({
      package_structure: '10Y/30Y Curve',
      legs_json: [{ tenor_display: '10Y' }, { tenor_display: '30Y' }],
    })
    expect(r?.kind).toBe('CURVE')
  })

  it('refuses an outright and a multi-leg package', () => {
    expect(structureOf({ package_structure: '5Y Outright', legs_json: [{ tenor_display: '5Y' }] })).toBeNull()
    expect(structureOf({ package_structure: '30Y Spreadover', legs_json: [{ tenor_display: '30Y' }] })).toBeNull()
  })
})
