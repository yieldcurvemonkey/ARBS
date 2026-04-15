import { describe, expect, it } from '@jest/globals'
import { FilterMatchMode, FilterOperator } from 'primereact/api'
import { applyColumnFilters, applyFuzzy, applySort } from '../filter-pipeline'

const mkRow = (overrides: Record<string, any> = {}): any => ({
  package_id: 'P',
  tape_label: 'USD-SOFR 5Y Outright',
  platform_identifier: 'Tradeweb',
  total_risk: 12_345,
  total_notional: 1_000_000,
  weighted_fixed_rate: 0.0425,
  execution_start: '2026-04-15T14:30:00Z',
  execution_end: '2026-04-15T14:30:00Z',
  trade_type: 'OUTRIGHT',
  lifecycle_mix: { NEW_RISK: 1 },
  legs_json: [{ tape_label: 'USD-SOFR 5Y' }],
  ...overrides,
})

describe('applyFuzzy', () => {
  it('returns all rows for empty query', () => {
    const rows = [mkRow(), mkRow({ package_id: 'Q' })]
    expect(applyFuzzy(rows, '')).toHaveLength(2)
  })

  it('matches on displayed tape label', () => {
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

  it('matches on fallback platform when the package-level platform is null', () => {
    const row = mkRow({
      package_id: 'A',
      platform_identifier: null,
      legs_json: [{ platform_identifier: 'Bloomberg', tape_label: 'USD-SOFR 5Y' }],
    })
    expect(applyFuzzy([row], 'bloom')).toEqual([row])
  })

  it('matches on lifecycle/action text', () => {
    const row = mkRow({
      package_id: 'A',
      lifecycle_mix: { UNWIND: 1 },
      is_unwind: true,
    })
    expect(applyFuzzy([row], 'unw')).toEqual([row])
  })
})

describe('applyColumnFilters', () => {
  it('applies CONTAINS filter on displayed tape label', () => {
    const a = mkRow({ package_id: 'A', tape_label: 'USD-SOFR 5Y Outright' })
    const b = mkRow({ package_id: 'B', tape_label: 'USD-FEDFUNDS 2Y' })
    const filtered = applyColumnFilters([a, b], {
      tape_label: { value: 'sofr', matchMode: FilterMatchMode.CONTAINS },
    })
    expect(filtered.map((r) => r.package_id)).toEqual(['A'])
  })

  it('uses the rendered action text for filtering', () => {
    const a = mkRow({
      package_id: 'A',
      lifecycle_mix: { NEW_RISK: 1 },
      is_new_risk: true,
    })
    const b = mkRow({
      package_id: 'B',
      lifecycle_mix: { UNWIND: 1 },
      is_unwind: true,
    })
    const filtered = applyColumnFilters([a, b], {
      action_label: { value: 'unw', matchMode: FilterMatchMode.CONTAINS },
    })
    expect(filtered.map((r) => r.package_id)).toEqual(['B'])
  })

  it('uses the fallback platform for filtering', () => {
    const a = mkRow({
      package_id: 'A',
      platform_identifier: null,
      legs_json: [{ platform_identifier: 'Bloomberg', tape_label: 'USD-SOFR 5Y' }],
    })
    const b = mkRow({ package_id: 'B', platform_identifier: 'Tradeweb' })
    const filtered = applyColumnFilters([a, b], {
      platform_identifier: { value: 'bloom', matchMode: FilterMatchMode.CONTAINS },
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

  it('honors per-column OR constraints', () => {
    const a = mkRow({ package_id: 'A', tape_label: 'USD-SOFR 5Y' })
    const b = mkRow({ package_id: 'B', tape_label: 'USD-FEDFUNDS 2Y' })
    const c = mkRow({ package_id: 'C', tape_label: 'EUR-ESTR 5Y' })
    const filtered = applyColumnFilters([a, b, c], {
      tape_label: {
        operator: FilterOperator.OR,
        constraints: [
          { value: 'sofr', matchMode: FilterMatchMode.CONTAINS },
          { value: 'fedfunds', matchMode: FilterMatchMode.CONTAINS },
        ],
      },
    })
    expect(filtered.map((r) => r.package_id)).toEqual(['A', 'B'])
  })

  it('AND combinator requires every field to match', () => {
    const a = mkRow({ package_id: 'A', tape_label: 'USD-SOFR 5Y', total_risk: 100 })
    const b = mkRow({ package_id: 'B', tape_label: 'USD-SOFR 2Y', total_risk: 300 })
    const filtered = applyColumnFilters(
      [a, b],
      {
        tape_label: { value: 'sofr', matchMode: FilterMatchMode.CONTAINS },
        total_risk: { value: 200, matchMode: FilterMatchMode.GREATER_THAN },
      },
      'and',
    )
    expect(filtered.map((r) => r.package_id)).toEqual(['B'])
  })

  it('OR combinator includes rows matching any single field', () => {
    const a = mkRow({ package_id: 'A', tape_label: 'USD-SOFR 5Y', total_risk: 100 })
    const b = mkRow({ package_id: 'B', tape_label: 'USD-FEDFUNDS 2Y', total_risk: 300 })
    const c = mkRow({ package_id: 'C', tape_label: 'EUR-ESTR 5Y', total_risk: 50 })
    const filtered = applyColumnFilters(
      [a, b, c],
      {
        tape_label: { value: 'sofr', matchMode: FilterMatchMode.CONTAINS },
        total_risk: { value: 200, matchMode: FilterMatchMode.GREATER_THAN },
      },
      'or',
    )
    expect(filtered.map((r) => r.package_id)).toEqual(['A', 'B'])
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

  it('sorts string columns using displayed fallback values', () => {
    const a = mkRow({
      package_id: 'A',
      platform_identifier: null,
      legs_json: [{ platform_identifier: 'Zulu', tape_label: 'USD-SOFR 5Y' }],
    })
    const b = mkRow({ package_id: 'B', platform_identifier: 'Alpha' })
    expect(
      applySort([a, b], 'platform_identifier', 1).map((r) => r.package_id),
    ).toEqual(['B', 'A'])
  })

  it('null values sort last regardless of order', () => {
    const a = mkRow({ package_id: 'A', total_risk: null })
    const b = mkRow({ package_id: 'B', total_risk: 100 })
    expect(applySort([a, b], 'total_risk', 1).map((r) => r.package_id)).toEqual(['B', 'A'])
    expect(applySort([a, b], 'total_risk', -1).map((r) => r.package_id)).toEqual(['B', 'A'])
  })
})
