import { describe, expect, it } from '@jest/globals'
import { FilterMatchMode, FilterOperator } from 'primereact/api'
import {
  buildColumnFilterPayload,
  getFilterDisplayLabel,
  hasActiveConstraints,
  isEmptyFilterValue,
  matchFilterMeta,
  matchFilterValue,
  parseFilterNumber,
} from '../filter-utils'

describe('isEmptyFilterValue', () => {
  it('treats null / undefined / empty string / empty array as empty', () => {
    expect(isEmptyFilterValue(null)).toBe(true)
    expect(isEmptyFilterValue(undefined)).toBe(true)
    expect(isEmptyFilterValue('')).toBe(true)
    expect(isEmptyFilterValue('   ')).toBe(true)
    expect(isEmptyFilterValue([])).toBe(true)
  })
  it('treats zero / non-empty string / populated array as non-empty', () => {
    expect(isEmptyFilterValue(0)).toBe(false)
    expect(isEmptyFilterValue('x')).toBe(false)
    expect(isEmptyFilterValue([1])).toBe(false)
  })
})

describe('parseFilterNumber', () => {
  it('returns the number for numeric input', () => {
    expect(parseFilterNumber(3.14)).toBe(3.14)
  })
  it('coerces numeric strings', () => {
    expect(parseFilterNumber('42')).toBe(42)
  })
  it('returns null for non-numeric', () => {
    expect(parseFilterNumber('abc')).toBeNull()
    expect(parseFilterNumber(null)).toBeNull()
    expect(parseFilterNumber('')).toBeNull()
  })
})

describe('matchFilterValue', () => {
  it('returns true when the filter value is empty (permissive)', () => {
    expect(matchFilterValue('any', '', FilterMatchMode.CONTAINS)).toBe(true)
  })
  it('CONTAINS matches substring case-insensitive', () => {
    expect(matchFilterValue('Hello World', 'hello', FilterMatchMode.CONTAINS)).toBe(true)
    expect(matchFilterValue('Hello', 'bye', FilterMatchMode.CONTAINS)).toBe(false)
  })
  it('GREATER_THAN_OR_EQUAL_TO on numbers', () => {
    expect(matchFilterValue(10, 5, FilterMatchMode.GREATER_THAN_OR_EQUAL_TO)).toBe(true)
    expect(matchFilterValue(4, 5, FilterMatchMode.GREATER_THAN_OR_EQUAL_TO)).toBe(false)
  })
  it('IN matches any member of the array', () => {
    expect(matchFilterValue('UNWIND', ['NEW_RISK', 'UNWIND'], FilterMatchMode.IN)).toBe(true)
    expect(matchFilterValue('CORR', ['NEW_RISK'], FilterMatchMode.IN)).toBe(false)
  })
})

describe('matchFilterMeta', () => {
  it('AND operator requires all constraints to pass', () => {
    const meta = {
      operator: FilterOperator.AND,
      constraints: [
        { value: 'SOFR', matchMode: FilterMatchMode.CONTAINS },
        { value: 'SWAP', matchMode: FilterMatchMode.CONTAINS },
      ],
    }
    expect(matchFilterMeta('SOFR SWAP', meta)).toBe(true)
    expect(matchFilterMeta('SOFR BOND', meta)).toBe(false)
  })
  it('OR operator matches if any constraint passes', () => {
    const meta = {
      operator: FilterOperator.OR,
      constraints: [
        { value: 'BOND', matchMode: FilterMatchMode.CONTAINS },
        { value: 'SWAP', matchMode: FilterMatchMode.CONTAINS },
      ],
    }
    expect(matchFilterMeta('SOFR SWAP', meta)).toBe(true)
    expect(matchFilterMeta('something else', meta)).toBe(false)
  })
  it('empty constraint list accepts any value', () => {
    expect(matchFilterMeta('x', { constraints: [{ value: null }] })).toBe(true)
  })
})

describe('buildColumnFilterPayload', () => {
  it('returns an empty payload when all menu constraints are empty', () => {
    const payload = buildColumnFilterPayload({
      tape_label: {
        operator: FilterOperator.AND,
        constraints: [{ value: null, matchMode: FilterMatchMode.CONTAINS }],
      },
    } as any)
    expect(payload).toEqual({})
  })
  it('serializes a menu-mode filter preserving operator + constraints', () => {
    const payload = buildColumnFilterPayload({
      tape_label: {
        operator: FilterOperator.OR,
        constraints: [
          { value: '5Y', matchMode: FilterMatchMode.CONTAINS },
          { value: '10Y', matchMode: FilterMatchMode.CONTAINS },
        ],
      },
      total_risk: {
        operator: FilterOperator.AND,
        constraints: [{ value: null, matchMode: FilterMatchMode.GREATER_THAN }],
      },
    } as any)
    expect((payload.tape_label as any).operator).toBe(FilterOperator.OR)
    expect((payload.tape_label as any).constraints).toHaveLength(2)
    expect(payload.total_risk).toBeUndefined()
  })
  it('also accepts a flat { value, matchMode } shape and wraps it', () => {
    const payload = buildColumnFilterPayload({
      tape_label: { value: 'Fed', matchMode: FilterMatchMode.CONTAINS },
    } as any)
    expect((payload.tape_label as any).operator).toBe(FilterOperator.AND)
    expect((payload.tape_label as any).constraints).toEqual([
      { value: 'Fed', matchMode: FilterMatchMode.CONTAINS },
    ])
  })
})

describe('hasActiveConstraints', () => {
  it('is true when any constraint has a non-empty value', () => {
    expect(
      hasActiveConstraints({
        constraints: [
          { value: null },
          { value: 'x', matchMode: FilterMatchMode.CONTAINS },
        ],
      }),
    ).toBe(true)
  })
  it('is false when every constraint is empty', () => {
    expect(
      hasActiveConstraints({ constraints: [{ value: null }, { value: '' }] }),
    ).toBe(false)
  })
})

describe('getFilterDisplayLabel', () => {
  it('renders mode + value per active constraint', () => {
    const label = getFilterDisplayLabel({
      operator: FilterOperator.AND,
      constraints: [{ value: '5Y', matchMode: FilterMatchMode.CONTAINS }],
    })
    expect(label).toBe('contains "5Y"')
  })
  it('returns empty string when no active constraints', () => {
    expect(getFilterDisplayLabel({ constraints: [{ value: null }] })).toBe('')
  })
})
