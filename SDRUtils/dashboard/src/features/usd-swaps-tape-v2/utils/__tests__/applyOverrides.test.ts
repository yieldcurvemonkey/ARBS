import { describe, expect, it } from '@jest/globals'
import { applyOverrides } from '../applyOverrides'
import type { UsdSwapTapeRow } from '../../types'

const leg = (trade_id: string, tenor = 5) =>
  ({ trade_id, tenor_years: tenor } as any)

const row = (
  package_id: string,
  legs: Array<{ trade_id: string }>,
  extras: Partial<UsdSwapTapeRow> = {},
): UsdSwapTapeRow =>
  ({
    package_id,
    package_type: 'CURVE',
    legs_json: legs,
    ...extras,
  } as any)

describe('applyOverrides', () => {
  it('passes normal rows through in order, tagging kind + key', () => {
    const rows = [row('P1', [leg('T1')]), row('P2', [leg('T2')])]
    const out = applyOverrides(rows)
    expect(out.map((r) => r.package_id)).toEqual(['P1', 'P2'])
    expect(out.map((r) => r.__rowKind)).toEqual(['normal', 'normal'])
    expect(out.map((r) => r.__syntheticKey)).toEqual(['P1', 'P2'])
    // legs untouched
    expect(out[0].legs_json).toHaveLength(1)
  })

  it('clusters GROUP rows sharing manual_package_id contiguously (anchored at first)', () => {
    const rows = [
      row('P1', [leg('T1')], { manual_package_id: 'SMO-1', override_type: 'GROUP', override_map: { T1: 'o1' } }),
      row('P2', [leg('T2')]),
      row('P3', [leg('T3')], { manual_package_id: 'SMO-1', override_type: 'GROUP', override_map: { T3: 'o1' } }),
    ]
    const out = applyOverrides(rows)
    expect(out.map((r) => r.package_id)).toEqual(['P1', 'P3', 'P2'])
    expect(out.every((r) => r.__rowKind === 'normal')).toBe(true)
  })

  it('explodes a SPLIT package into one row per leg with synthetic keys', () => {
    const rows = [
      row('P1', [leg('T1'), leg('T2'), leg('T3')], {
        override_type: 'SPLIT',
        override_map: { T1: 'o9', T2: 'o9', T3: 'o9' },
      }),
    ]
    const out = applyOverrides(rows)
    expect(out).toHaveLength(3)
    expect(out.map((r) => r.__syntheticKey)).toEqual([
      'P1::split::T1',
      'P1::split::T2',
      'P1::split::T3',
    ])
    expect(out.every((r) => r.__rowKind === 'split-leg')).toBe(true)
    expect(out.every((r) => r.legs_json.length === 1)).toBe(true)
    expect(out[1].legs_json[0].trade_id).toBe('T2')
    // override metadata preserved so the SPLIT badge renders on each row
    expect(out[0].override_type).toBe('SPLIT')
  })

  it('DETACH keeps a remnant package row + standalone detached legs', () => {
    const rows = [
      row('P1', [leg('T1'), leg('T2'), leg('T3')], {
        override_type: 'DETACH',
        override_map: { T2: 'o5' },
      }),
    ]
    const out = applyOverrides(rows)
    expect(out).toHaveLength(2)
    // remnant first, keyed by package_id, kind normal, only non-detached legs
    expect(out[0].__syntheticKey).toBe('P1')
    expect(out[0].__rowKind).toBe('normal')
    expect(out[0].legs_json.map((l) => l.trade_id)).toEqual(['T1', 'T3'])
    // detached leg standalone
    expect(out[1].__syntheticKey).toBe('P1::detach::T2')
    expect(out[1].__rowKind).toBe('detached')
    expect(out[1].legs_json.map((l) => l.trade_id)).toEqual(['T2'])
  })

  it('DETACH of every leg emits only detached rows (no empty remnant)', () => {
    const rows = [
      row('P1', [leg('T1')], { override_type: 'DETACH', override_map: { T1: 'o5' } }),
    ]
    const out = applyOverrides(rows)
    expect(out).toHaveLength(1)
    expect(out[0].__rowKind).toBe('detached')
    expect(out[0].__syntheticKey).toBe('P1::detach::T1')
  })

  it('SPLIT with a leg missing trade_id falls back to an index key', () => {
    const rows = [
      row('P1', [{ trade_id: undefined } as any, leg('T2')], {
        override_type: 'SPLIT',
        override_map: { T2: 'o9' },
      }),
    ]
    const out = applyOverrides(rows)
    expect(out[0].__syntheticKey).toBe('P1::split::idx0')
    expect(out[1].__syntheticKey).toBe('P1::split::T2')
  })

  it('returns [] for empty input', () => {
    expect(applyOverrides([])).toEqual([])
  })
})
