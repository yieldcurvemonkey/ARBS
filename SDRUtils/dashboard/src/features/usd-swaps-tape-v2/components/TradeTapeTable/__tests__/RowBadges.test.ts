import { describe, expect, it } from '@jest/globals'
import { flagBadgesFor, lifecyclePillsFor } from '../RowBadges.helpers'

const row = (overrides: Record<string, any> = {}): any => ({
  package_id: 'P1',
  package_type: 'OUTRIGHT',
  legs_count: 1,
  execution_start: '2026-04-14T14:30:00Z',
  execution_end: '2026-04-14T14:30:00Z',
  package_metrics: {},
  legs_json: [],
  lifecycle_mix: {},
  ...overrides,
})

describe('lifecyclePillsFor', () => {
  it('returns empty array for a row with no mix data', () => {
    expect(lifecyclePillsFor(row())).toEqual([])
  })

  it('emits one pill per non-zero lifecycle count', () => {
    const pills = lifecyclePillsFor(
      row({ lifecycle_mix: { UNWIND: 3, TERMINATION: 1, COMPRESSION: 0 } }),
    )
    expect(pills.map((p) => p.type)).toEqual(['UNWIND', 'TERMINATION'])
    expect(pills[0].count).toBe(3)
    expect(pills[1].count).toBe(1)
  })

  it('labels match LIFECYCLE_LABELS', () => {
    const pills = lifecyclePillsFor(row({ lifecycle_mix: { TERMINATION: 1 } }))
    expect(pills[0].label).toBe('TERM')
  })
})

describe('lifecyclePillsFor — NEW hygiene', () => {
  it('drops NEW pill when mix also contains a non-NEW lifecycle', () => {
    const pills = lifecyclePillsFor(
      row({ lifecycle_mix: { NEW_RISK: 1, UNWIND: 2 } }),
    )
    expect(pills.map((p) => p.type)).toEqual(['UNWIND'])
  })

  it('keeps NEW pill when mix is pure NEW_RISK', () => {
    const pills = lifecyclePillsFor(row({ lifecycle_mix: { NEW_RISK: 4 } }))
    expect(pills.map((p) => p.type)).toEqual(['NEW_RISK'])
    expect(pills[0].count).toBe(4)
  })

  it('drops NEW when termination is the other flag', () => {
    const pills = lifecyclePillsFor(
      row({ lifecycle_mix: { NEW_RISK: 1, TERMINATION: 1 } }),
    )
    expect(pills.map((p) => p.type)).toEqual(['TERMINATION'])
  })
})

describe('flagBadgesFor', () => {
  it('emits block + UFRO + cap + off-date in order when all set', () => {
    const badges = flagBadgesFor(
      row({
        is_block_any: true,
        is_ufro_any: true,
        is_capped_any: true,
        is_off_date_any: true,
      }),
    )
    expect(badges.map((b) => b.key)).toEqual(['BLK', 'UFRO', 'CAP', 'ODT'])
  })

  it('carries aria-labels describing each flag', () => {
    const badges = flagBadgesFor(row({ is_block_any: true, is_ufro_any: true }))
    expect(badges.map((b) => b.ariaLabel)).toEqual([
      'block trade',
      'off-market rate',
    ])
  })
})
