import { describe, expect, it } from '@jest/globals'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import {
  economicClassBadgeFor,
  extendedLifecyclePillsFor,
  flagBadgesFor,
  lifecyclePillsFor,
  qualityBadgesFor,
} from '../RowBadges.helpers'

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


// ===========================================================================
// Phase 2-5 SDR remediation: matrix kind, quality flags, extended lifecycle
// ===========================================================================

describe('economicClassBadgeFor (Phase 3 matrix)', () => {
  it('returns null for a row with no class signal', () => {
    expect(economicClassBadgeFor(row())).toBeNull()
  })

  it('uses the package-level economic_class_primary when present', () => {
    const meta = economicClassBadgeFor(
      row({ economic_class_primary: 'ECONOMIC_FLOW' }),
    )
    expect(meta?.label).toBe('FLOW')
    expect(meta?.className).toMatch(/bg-emerald/)
  })

  it('falls back to ADMINISTRATIVE for compression-only rows', () => {
    const meta = economicClassBadgeFor(row({ is_compression_any: true }))
    expect(meta?.label).toBe('ADMIN')
  })

  it('falls back to ECONOMIC_UNWIND for unwind rows', () => {
    const meta = economicClassBadgeFor(row({ is_unwind: true }))
    expect(meta?.label).toBe('UNW')
  })

  it('matrix kind beats legacy heuristic when both are present', () => {
    const meta = economicClassBadgeFor(
      row({ economic_class_primary: 'ADMINISTRATIVE', is_new_risk: true }),
    )
    expect(meta?.label).toBe('ADMIN')
  })
})


describe('qualityBadgesFor (Phase 4-5 compliance flags)', () => {
  it('returns empty for a clean row', () => {
    expect(qualityBadgesFor(row())).toEqual([])
  })

  it('emits VIOL when any leg has state_machine_violation', () => {
    const badges = qualityBadgesFor(
      row({
        legs_json: [
          {
            state_machine_violation: true,
            violation_reason: 'MODI_ON_ERRORED_WITHOUT_REVI',
          },
        ],
      }),
    )
    expect(badges.map((b) => b.key)).toContain('VIOL')
    expect(badges[0].title).toContain('MODI_ON_ERRORED_WITHOUT_REVI')
  })

  it('emits CAP-BAND from any leg with cap_band_violation', () => {
    const badges = qualityBadgesFor(
      row({ legs_json: [{ cap_band_violation: true }] }),
    )
    expect(badges.map((b) => b.key)).toContain('CAP-BAND')
  })

  it('emits FREQ for frequency_anomaly legs', () => {
    const badges = qualityBadgesFor(
      row({ legs_json: [{ frequency_anomaly: true }] }),
    )
    expect(badges.map((b) => b.key)).toContain('FREQ')
  })

  it('emits TRUNC when at least one leg has schedule_truncated=true', () => {
    const badges = qualityBadgesFor(
      row({ legs_json: [{ schedule_truncated: true, schedule_row_count: 25 }] }),
    )
    expect(badges.map((b) => b.key)).toContain('TRUNC')
  })

  it('emits D2 for d2_missing legs', () => {
    const badges = qualityBadgesFor(
      row({ legs_json: [{ d2_missing: true }] }),
    )
    expect(badges.map((b) => b.key)).toContain('D2')
  })

  it('emits CLR when clearing_accepted_start lags original_execution by ≥ 60s', () => {
    const badges = qualityBadgesFor(
      row({
        original_execution_start: '2026-04-09T16:45:00Z',
        clearing_accepted_start: '2026-04-09T16:46:30Z',
      }),
    )
    expect(badges.map((b) => b.key)).toContain('CLR')
  })

  it('does NOT emit CLR for sub-second clearing acceptance (P2-02 noise fix)', () => {
    const badges = qualityBadgesFor(
      row({
        original_execution_start: '2026-04-09T16:45:00Z',
        clearing_accepted_start: '2026-04-09T16:45:00.250Z',
      }),
    )
    expect(badges.map((b) => b.key)).not.toContain('CLR')
  })

  it('emits P45 when on_p43_any is False', () => {
    const badges = qualityBadgesFor(row({ on_p43_any: false }))
    expect(badges.map((b) => b.key)).toContain('P43-OFF')
  })
})


describe('extendedLifecyclePillsFor (Phase 2 MODI sub-states)', () => {
  it('adds AMENDMENT pill when any leg has lc_was_amended', () => {
    const pills = extendedLifecyclePillsFor(
      row({ legs_json: [{ lc_was_amended: true }] }),
    )
    expect(pills.map((p) => p.type)).toContain('AMENDMENT')
  })

  it('adds NULL_FILL pill when any leg has lc_was_null_filled', () => {
    const pills = extendedLifecyclePillsFor(
      row({ legs_json: [{ lc_was_null_filled: true }] }),
    )
    expect(pills.map((p) => p.type)).toContain('NULL_FILL')
  })

  it('adds SCHED_AMORT pill when any leg has lc_was_scheduled_amortization', () => {
    const pills = extendedLifecyclePillsFor(
      row({ legs_json: [{ lc_was_scheduled_amortization: true }] }),
    )
    expect(pills.map((p) => p.type)).toContain('SCHED_AMORT')
  })

  it('adds ERROR pill when any leg has state_machine_violation', () => {
    const pills = extendedLifecyclePillsFor(
      row({ legs_json: [{ state_machine_violation: true }] }),
    )
    expect(pills.map((p) => p.type)).toContain('ERROR')
  })

  it('does not duplicate pills already present in the lifecycle_mix', () => {
    const pills = extendedLifecyclePillsFor(
      row({
        lifecycle_mix: { TERMINATION: 1 },
        legs_json: [{ lc_was_amended: true }],
      }),
    )
    const types = pills.map((p) => p.type)
    expect(types).toContain('TERMINATION')
    expect(types).toContain('AMENDMENT')
    // No duplicates
    expect(new Set(types).size).toBe(types.length)
  })
})
