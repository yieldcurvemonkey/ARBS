import { describe, expect, it } from '@jest/globals'
import type { UsdSwapTapeRow } from '../../types'
import { __internal } from '../useTradeTapeData'

const buildQuery = __internal.buildQuery
const dedupeDuplicatePackages = __internal.dedupeDuplicatePackages

describe('useTradeTapeData buildQuery', () => {
  it('always emits a page size so the server caps each fetch predictably', () => {
    const q = buildQuery({})
    // Default page size is intentionally larger than the swaption tape so
    // traders see a deep tape on first paint; VirtualScroller still chains
    // additional pages at the same size as the server scrolls further back.
    expect(q.get('limit')).toBe('200')
  })

  it('honours a caller-supplied limit override', () => {
    const q = buildQuery({ limit: 50 })
    expect(q.get('limit')).toBe('50')
  })

  it('does NOT emit any filter query params — filtering is client-only post feedback round 1', () => {
    const q = buildQuery({} as any)
    expect(q.has('filter')).toBe(false)
    expect(q.has('columnFilters')).toBe(false)
    expect(q.has('lifecycle')).toBe(false)
    expect(q.has('tradeTypes')).toBe(false)
    expect(q.has('venues')).toBe(false)
    expect(q.has('clean')).toBe(false)
  })

  it('attaches cursor / since when provided', () => {
    const q1 = buildQuery({}, { cursor: '2026-04-14T00:00:00Z' })
    expect(q1.get('cursor')).toBe('2026-04-14T00:00:00Z')
    const q2 = buildQuery({}, { since: '2026-04-14T20:00:00Z' })
    expect(q2.get('since')).toBe('2026-04-14T20:00:00Z')
  })

  it('emits columnFilters when the hook is configured with one', () => {
    const cf = JSON.stringify({
      tape_label: {
        operator: 'and',
        constraints: [{ value: '10Y', matchMode: 'contains' }],
      },
    })
    const q = buildQuery({ columnFilters: cf } as any)
    expect(q.get('columnFilters')).toBe(cf)
  })

  it('attaches columnFilters to cursor + since requests too', () => {
    const cf = JSON.stringify({
      tape_label: {
        operator: 'and',
        constraints: [{ value: '10Y', matchMode: 'contains' }],
      },
    })
    const q1 = buildQuery({ columnFilters: cf } as any, { cursor: 'abc' })
    expect(q1.get('cursor')).toBe('abc')
    expect(q1.get('columnFilters')).toBe(cf)
    const q2 = buildQuery({ columnFilters: cf } as any, { since: 'xyz' })
    expect(q2.get('since')).toBe('xyz')
    expect(q2.get('columnFilters')).toBe(cf)
  })

  it('omits columnFilters when not supplied', () => {
    const q = buildQuery({})
    expect(q.has('columnFilters')).toBe(false)
  })

  it('omits columnFilters when explicitly null (no active overlay)', () => {
    const q = buildQuery({ columnFilters: null } as any)
    expect(q.has('columnFilters')).toBe(false)
  })
})

describe('dedupeDuplicatePackages', () => {
  // Minimal factory: only the fields the dedupe signature / filter consult.
  // Default legs_json has 2 entries so the orphan-drop filter leaves the
  // row alone. Tests that want to exercise the zero-leg path override it.
  const makeRow = (overrides: Partial<UsdSwapTapeRow> = {}): UsdSwapTapeRow => ({
    package_id: 'CURVE_1',
    execution_start: '2026-04-10T16:55:46Z',
    execution_end: '2026-04-10T16:56:26Z',
    package_type: 'CURVE',
    package_tenors: '5Y/10Y',
    total_risk: 41500,
    weighted_fixed_rate: 0.03708,
    package_transaction_spread: -0.003175,
    platform_identifier: null,
    legs_json: [{ fixed_rate: 0.035 }, { fixed_rate: 0.037 }],
    ...overrides,
  } as unknown as UsdSwapTapeRow)

  it('returns the same rows when nothing collides', () => {
    const rows = [
      makeRow({ package_id: 'CURVE_1' }),
      makeRow({
        package_id: 'CURVE_2',
        execution_start: '2026-04-10T17:00:00Z',
        package_tenors: '2Y/5Y',
      }),
    ]
    expect(dedupeDuplicatePackages(rows)).toHaveLength(2)
  })

  it('collapses rows that share the dedupe signature into one', () => {
    const rows = [
      makeRow({ package_id: 'CURVE_1', platform_identifier: null }),
      makeRow({ package_id: 'CURVE_2', platform_identifier: 'RTXF' }),
    ]
    const out = dedupeDuplicatePackages(rows)
    expect(out).toHaveLength(1)
  })

  it('prefers the variant with a non-null platform_identifier', () => {
    const rows = [
      makeRow({ package_id: 'CURVE_1', platform_identifier: null }),
      makeRow({ package_id: 'CURVE_2', platform_identifier: 'RTXF' }),
    ]
    const out = dedupeDuplicatePackages(rows)
    expect(out[0]?.platform_identifier).toBe('RTXF')
  })

  it('keeps the first-seen row when both variants are equally complete', () => {
    const rows = [
      makeRow({ package_id: 'CURVE_A', platform_identifier: 'BBSF' }),
      makeRow({ package_id: 'CURVE_B', platform_identifier: 'RTXF' }),
    ]
    const out = dedupeDuplicatePackages(rows)
    expect(out).toHaveLength(1)
    expect(out[0]?.package_id).toBe('CURVE_A')
  })

  it('treats differences in package_tenors as distinct logical trades', () => {
    const rows = [
      makeRow({ package_id: 'CURVE_1', package_tenors: '5Y/10Y' }),
      makeRow({ package_id: 'CURVE_2', package_tenors: '2Y/5Y' }),
    ]
    expect(dedupeDuplicatePackages(rows)).toHaveLength(2)
  })

  it('treats differences in total_risk as distinct logical trades', () => {
    const rows = [
      makeRow({ package_id: 'CURVE_1', total_risk: 41500 }),
      makeRow({ package_id: 'CURVE_2', total_risk: 80000 }),
    ]
    expect(dedupeDuplicatePackages(rows)).toHaveLength(2)
  })

  it('drops orphan package rows whose legs_json is empty', () => {
    // Pre-fix collision bug left stale package rows in Postgres whose legs
    // got re-associated to a newer package_id. They render in the tape with
    // no legs_json entries and no way to expand — drop them.
    const rows = [
      makeRow({
        package_id: 'CURVE_orphan',
        package_type: 'CURVE',
        legs_json: [],
      }),
      makeRow({
        package_id: 'CURVE_healthy',
        package_type: 'CURVE',
        package_tenors: '2Y/5Y',
        legs_json: [{ fixed_rate: 0.035 }, { fixed_rate: 0.037 }] as any,
      }),
    ]
    const out = dedupeDuplicatePackages(rows)
    expect(out).toHaveLength(1)
    expect(out[0]?.package_id).toBe('CURVE_healthy')
  })

  it('when two rows share the signature, prefers the one with more legs', () => {
    // Exact scenario from the user screenshot: both rows carry the same
    // execution window, risk, rate, spread, and tenors. One is the stale
    // orphan (zero legs), the other is the live package (two legs). Keep
    // the live one.
    const rows = [
      makeRow({
        package_id: 'CURVE_orphan',
        legs_json: [],
      }),
      makeRow({
        package_id: 'CURVE_healthy',
        legs_json: [{ fixed_rate: 0.035 }, { fixed_rate: 0.037 }] as any,
      }),
    ]
    const out = dedupeDuplicatePackages(rows)
    expect(out).toHaveLength(1)
    expect(out[0]?.package_id).toBe('CURVE_healthy')
  })

  it('leaves outright / non-package rows alone (package_id signature is unique)', () => {
    const rows = [
      makeRow({
        package_id: 'OUTRIGHT-T1',
        package_type: 'OUTRIGHT',
        package_tenors: '10Y',
        total_risk: 10000,
        legs_json: [{ fixed_rate: 0.035 }] as any,
      }),
      makeRow({
        package_id: 'OUTRIGHT-T2',
        package_type: 'OUTRIGHT',
        package_tenors: '10Y',
        total_risk: 10000,
        execution_start: '2026-04-10T17:10:00Z',
        execution_end: '2026-04-10T17:10:00Z',
        legs_json: [{ fixed_rate: 0.035 }] as any,
      }),
    ]
    expect(dedupeDuplicatePackages(rows)).toHaveLength(2)
  })

  it('drops an orphan outright with zero legs too', () => {
    // Same orphan mechanism can affect single-leg OUTRIGHT rows if the
    // backing trade_id was re-classified under a different package_id.
    const rows = [
      makeRow({
        package_id: 'OUTRIGHT-T1',
        package_type: 'OUTRIGHT',
        package_tenors: '10Y',
        legs_json: [],
      }),
    ]
    expect(dedupeDuplicatePackages(rows)).toHaveLength(0)
  })
})
