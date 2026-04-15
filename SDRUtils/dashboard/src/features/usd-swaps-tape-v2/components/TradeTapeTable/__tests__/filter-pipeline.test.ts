import { describe, expect, it } from '@jest/globals'
import { FilterMatchMode } from 'primereact/api'
import { applyColumnFilters, applyFuzzy, applySort } from '../filter-pipeline'

const mkRow = (overrides: Record<string, any> = {}): any => ({
  package_id: 'P',
  tape_label: 'USD-SOFR 5Y Outright',
  platform_identifier: 'Tradeweb',
  total_risk: 12345,
  total_notional: 1_000_000,
  weighted_fixed_rate: 0.0425,
  execution_start: '2026-04-15T14:30:00Z',
  execution_end: '2026-04-15T14:30:00Z',
  trade_type: 'OUTRIGHT',
  legs_json: [{ tape_label: 'USD-SOFR 5Y' }],
  ...overrides,
})

describe('applyFuzzy', () => {
  it('returns all rows for empty query', () => {
    const rows = [mkRow(), mkRow({ package_id: 'Q' })]
    expect(applyFuzzy(rows, '')).toHaveLength(2)
  })

  it('matches on tape_label', () => {
    const a = mkRow({
      package_id: 'A',
      tape_label: 'USD-SOFR 5Y Outright',
      legs_json: [{ tape_label: 'USD-SOFR 5Y' }],
    })
    const b = mkRow({
      package_id: 'B',
      tape_label: 'USD-FEDFUNDS 2Y',
      legs_json: [{ tape_label: 'USD-FEDFUNDS 2Y' }],
    })
    expect(applyFuzzy([a, b], 'sofr')).toEqual([a])
  })

  it('matches on platform', () => {
    const a = mkRow({
      package_id: 'A',
      platform_identifier: 'Bloomberg',
      legs_json: [],
    })
    const b = mkRow({
      package_id: 'B',
      platform_identifier: 'Tradeweb',
      legs_json: [],
    })
    expect(applyFuzzy([a, b], 'bloom').map((r) => r.package_id)).toEqual(['A'])
  })

  it('matches fuzzy subsequence (bbg within Bloomberg-ish)', () => {
    const a = mkRow({ package_id: 'A', tape_label: 'Bloomberg 5Y' })
    expect(applyFuzzy([a], 'bbg').length).toBe(1)
  })
})

describe('applyColumnFilters', () => {
  it('applies CONTAINS filter on tape_label', () => {
    const a = mkRow({ package_id: 'A', tape_label: 'USD-SOFR 5Y Outright' })
    const b = mkRow({ package_id: 'B', tape_label: 'USD-FEDFUNDS 2Y' })
    const filtered = applyColumnFilters([a, b], {
      tape_label: { value: 'sofr', matchMode: FilterMatchMode.CONTAINS },
    })
    expect(filtered.map((r) => r.package_id)).toEqual(['A'])
  })

  it('applies numeric GT filter on total_risk', () => {
    const a = mkRow({ package_id: 'A', total_risk: 100 })
    const b = mkRow({ package_id: 'B', total_risk: 200 })
    const filtered = applyColumnFilters([a, b], {
      total_risk: { value: 150, matchMode: FilterMatchMode.GREATER_THAN },
    })
    expect(filtered.map((r) => r.package_id)).toEqual(['B'])
  })

  it('returns all rows when no active filters', () => {
    const rows = [mkRow(), mkRow()]
    expect(applyColumnFilters(rows, {})).toHaveLength(2)
    expect(
      applyColumnFilters(rows, {
        tape_label: { value: null, matchMode: FilterMatchMode.CONTAINS },
      }),
    ).toHaveLength(2)
  })
})

describe('applySort', () => {
  it('returns input order when no sort field', () => {
    const a = mkRow({ package_id: 'A', total_risk: 100 })
    const b = mkRow({ package_id: 'B', total_risk: 200 })
    expect(applySort([a, b], null, 0).map((r) => r.package_id)).toEqual(['A', 'B'])
  })

  it('sorts numeric ascending', () => {
    const a = mkRow({ package_id: 'A', total_risk: 200 })
    const b = mkRow({ package_id: 'B', total_risk: 100 })
    expect(applySort([a, b], 'total_risk', 1).map((r) => r.package_id)).toEqual(['B', 'A'])
  })

  it('sorts numeric descending', () => {
    const a = mkRow({ package_id: 'A', total_risk: 100 })
    const b = mkRow({ package_id: 'B', total_risk: 200 })
    expect(applySort([a, b], 'total_risk', -1).map((r) => r.package_id)).toEqual(['B', 'A'])
  })

  it('sorts strings case-insensitive', () => {
    const a = mkRow({ package_id: 'A', platform_identifier: 'Zulu' })
    const b = mkRow({ package_id: 'B', platform_identifier: 'alpha' })
    expect(applySort([a, b], 'platform_identifier', 1).map((r) => r.package_id)).toEqual(['B', 'A'])
  })

  it('null values sort last regardless of order', () => {
    const a = mkRow({ package_id: 'A', total_risk: null })
    const b = mkRow({ package_id: 'B', total_risk: 100 })
    expect(applySort([a, b], 'total_risk', 1).map((r) => r.package_id)).toEqual(['B', 'A'])
    expect(applySort([a, b], 'total_risk', -1).map((r) => r.package_id)).toEqual(['B', 'A'])
  })
})
