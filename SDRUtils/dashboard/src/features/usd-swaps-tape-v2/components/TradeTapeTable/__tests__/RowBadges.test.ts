import { describe, expect, it } from '@jest/globals'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { flagBadgesFor, lifecyclePillsFor } from '../RowBadges.helpers'

const rowBadgesSource = readFileSync(
  resolve(
    process.cwd(),
    'src/features/usd-swaps-tape-v2/components/TradeTapeTable/RowBadges.tsx',
  ),
  'utf8',
)

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

describe('LifecyclePills rendering', () => {
  it('does not append the mix count to the pill label (visual only — "NEW 2" reads as "NEW")', () => {
    // Count stays on the pill object for aria-labels / telemetry, but the
    // visible label must not include the numeric suffix. We verify via source
    // because this component lives above a Jest DOM renderer in this repo.
    expect(rowBadgesSource).not.toContain('p.count > 1')
    expect(rowBadgesSource).not.toContain('` ${p.count}`')
  })
})

describe('LIFECYCLE_TONES palette (feedback round 1 saturated)', () => {
  it('UNWIND pill uses the saturated red-500 tone with ring outline', async () => {
    const { LIFECYCLE_TONES } = await import('../../../constants')
    expect(LIFECYCLE_TONES.UNWIND).toMatch(/bg-red-500\/30/)
    expect(LIFECYCLE_TONES.UNWIND).toMatch(/ring-red-400/)
  })

  it('NEW_RISK uses emerald-500; COMPRESSION uses sky-500; NOVATION uses violet-500', async () => {
    const { LIFECYCLE_TONES } = await import('../../../constants')
    expect(LIFECYCLE_TONES.NEW_RISK).toMatch(/bg-emerald-500/)
    expect(LIFECYCLE_TONES.COMPRESSION).toMatch(/bg-sky-500/)
    expect(LIFECYCLE_TONES.NOVATION).toMatch(/bg-violet-500/)
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
