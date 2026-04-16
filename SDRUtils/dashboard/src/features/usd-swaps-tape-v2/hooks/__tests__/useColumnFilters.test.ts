import { describe, expect, it } from '@jest/globals'
import { FilterMatchMode, FilterOperator } from 'primereact/api'
import {
  DEFAULT_SORT_FIELD,
  DEFAULT_SORT_ORDER,
  parseSortField,
  parseSortOrder,
  rehydrateFilters,
  serializeFilters,
} from '../useColumnFilters.helpers'

describe('useColumnFilters URL helpers', () => {
  it('rehydrate of empty / invalid input returns an empty object', () => {
    expect(rehydrateFilters(null)).toEqual({})
    expect(rehydrateFilters('')).toEqual({})
    expect(rehydrateFilters('{broken json')).toEqual({})
    expect(rehydrateFilters('null')).toEqual({})
  })

  it('serialize + rehydrate round-trips a menu-mode filter map', () => {
    const input = {
      tape_label: {
        operator: FilterOperator.AND,
        constraints: [{ value: '5Y', matchMode: FilterMatchMode.CONTAINS }],
      },
      total_risk: {
        operator: FilterOperator.OR,
        constraints: [
          { value: 1000, matchMode: FilterMatchMode.GREATER_THAN },
          { value: 10000, matchMode: FilterMatchMode.LESS_THAN },
        ],
      },
    } as any

    const url = serializeFilters(input)
    expect(url).toContain('tape_label')
    expect(url).toContain('total_risk')

    const out = rehydrateFilters(url)
    expect((out.tape_label as any).constraints[0].value).toBe('5Y')
    expect((out.total_risk as any).operator).toBe(FilterOperator.OR)
    expect((out.total_risk as any).constraints).toHaveLength(2)
  })

  it('strips constraints with empty values during serialize', () => {
    const input = {
      tape_label: {
        operator: FilterOperator.AND,
        constraints: [{ value: null, matchMode: FilterMatchMode.CONTAINS }],
      },
    } as any
    expect(serializeFilters(input)).toBe('')
  })

  it('rehydrate drops fields whose menu constraints are all empty', () => {
    const raw = JSON.stringify({
      tape_label: {
        operator: FilterOperator.AND,
        constraints: [{ value: null }],
      },
    })
    expect(rehydrateFilters(raw)).toEqual({})
  })

  it('rehydrate accepts the flat { value, matchMode } shape for back-compat', () => {
    const raw = JSON.stringify({
      tape_label: { value: '5Y', matchMode: FilterMatchMode.CONTAINS },
    })
    const out = rehydrateFilters(raw)
    expect((out.tape_label as any).constraints[0].value).toBe('5Y')
    expect((out.tape_label as any).constraints[0].matchMode).toBe(
      FilterMatchMode.CONTAINS,
    )
    expect((out.tape_label as any).operator).toBe(FilterOperator.AND)
  })

  it('defaults sort state to execution_start descending when URL params are absent', () => {
    expect(parseSortField(null)).toBe(DEFAULT_SORT_FIELD)
    expect(parseSortField('')).toBe(DEFAULT_SORT_FIELD)
    expect(parseSortOrder(null)).toBe(DEFAULT_SORT_ORDER)
    expect(parseSortOrder('0')).toBe(DEFAULT_SORT_ORDER)
  })

  it('preserves explicit sort params from the URL', () => {
    expect(parseSortField('weighted_fixed_rate')).toBe('weighted_fixed_rate')
    expect(parseSortOrder('1')).toBe(1)
    expect(parseSortOrder('-1')).toBe(DEFAULT_SORT_ORDER)
  })
})
