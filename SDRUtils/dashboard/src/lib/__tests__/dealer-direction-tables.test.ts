// ABOUTME: The generation constant and the join, pinned.
//
// The names below are pinned as literals, exactly as tape-tables.test.ts pins
// the tape's. The failure this prevents: the Python writer moves to _v2 and
// the reader silently keeps serving _v1 rows, which look like data rather than
// like a stale generation.
import { describe, expect, it } from '@jest/globals'
import {
  DD_COVERAGE,
  DD_GENERATION,
  DD_IN_LADDER,
  DD_LADDER,
  DD_RUNS,
  DD_UNIT,
  DD_UNIT_BUCKET,
} from '../dealer-direction-tables'
import { __buildDirectionJoin } from '../dealer-direction-join'

describe('the generation is a constant, not an env var', () => {
  it('is v1 and the names derive from it', () => {
    expect(DD_GENERATION).toBe('v1')
    expect(DD_UNIT).toBe('arbs_dd_unit_v1')
    expect(DD_UNIT_BUCKET).toBe('arbs_dd_unit_bucket_v1')
    expect(DD_COVERAGE).toBe('arbs_dd_coverage_v1')
    expect(DD_LADDER).toBe('arbs_dd_ladder_v1')
    expect(DD_RUNS).toBe('arbs_dd_runs_v1')
  })

  it('agrees with provenance.IN_LADDER', () => {
    expect(DD_IN_LADDER).toBe('IN_LADDER')
  })
})

describe('the tape join', () => {
  const join = __buildDirectionJoin()

  it('joins on package_id, not unit_key', () => {
    // Measured over five days spanning the whole tape: package_id matches
    // 100.0000% both directions; unit_key matches 21.7-29.3%, because a
    // single-leg print carrying a package id is keyed by that id in the view
    // and by its raw trade_id in unit_key.
    expect(join.join).toContain('dd.package_id = d.package_id')
    expect(join.join).not.toContain('unit_key')
    expect(join.join).toMatch(/^LEFT JOIN/)
  })

  it('is a LEFT join, so a day the batch has not reached still renders', () => {
    expect(join.join).toContain('LEFT JOIN')
  })

  it('aliases every field with a dd_ prefix', () => {
    const aliases = [...join.columns.matchAll(/AS (\w+)/g)].map((m) => m[1]!)
    expect(aliases.length).toBeGreaterThan(15)
    for (const a of aliases) expect(a.startsWith('dd_')).toBe(true)
  })

  it('carries the fields the grid actually reads', () => {
    for (const a of [
      'dd_dealer_direction', 'dd_p', 'dd_signed_weight', 'dd_rule',
      'dd_exclusion_reason', 'dd_in_dead_zone', 'dd_visibility_lag_seconds',
      'dd_notional_imputed', 'dd_code_vintage', 'dd_tape_generation',
    ]) {
      expect(join.columns).toContain(`AS ${a}`)
    }
  })

  it('does NOT carry dealer_spread_est or opa_sign — they are not direction', () => {
    // opa_sign is direction-blind by symmetry: the solver scores a sign vector
    // and its global complement identically, so the orientation is a tie-break.
    // dealer_spread_est is literally the dollar residual, always non-negative,
    // with a mean flat across the sign of the net. Surfacing either beside a
    // real direction would be read as corroboration.
    expect(join.columns).not.toContain('dealer_spread')
    expect(join.columns).not.toContain('opa_sign')
  })

  it('starts with a comma so it appends to an existing SELECT list', () => {
    expect(join.columns.startsWith(', ')).toBe(true)
  })
})
