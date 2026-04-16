import { describe, expect, it } from '@jest/globals'
import { FilterMatchMode, FilterOperator } from 'primereact/api'
import { rehydrateFilters, serializeFilters } from '../useColumnFilters.helpers'

describe('useColumnFilters URL helpers', () => {
  it('rehydrate of empty / invalid input returns an empty object', () => {
    expect(rehydrateFilters(null)).toEqual({})
    expect(rehydrateFilters('')).toEqual({})
    expect(rehydrateFilters('{broken json')).toEqual({})
    expect(rehydrateFilters('null')).toEqual({})
  })

  it('serialize + rehydrate round-trips a full DataTableFilterMeta', () => {
    const input = {
      tape_label: {
        operator: FilterOperator.AND,
        constraints: [
          { value: '5Y', matchMode: FilterMatchMode.CONTAINS },
        ],
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
    expect(out.tape_label).toBeTruthy()
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

  it('rehydrate drops fields whose constraints are all empty', () => {
    const raw = JSON.stringify({
      tape_label: {
        operator: FilterOperator.AND,
        constraints: [{ value: null }],
      },
    })
    expect(rehydrateFilters(raw)).toEqual({})
  })
})
