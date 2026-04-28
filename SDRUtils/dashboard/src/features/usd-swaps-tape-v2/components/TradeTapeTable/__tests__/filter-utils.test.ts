import { describe, expect, it } from '@jest/globals'
import { FilterMatchMode, FilterOperator } from 'primereact/api'
import {
  buildColumnFilterPayload,
  collectFilterCandidates,
  getFilterDisplayLabel,
  hasActiveConstraints,
  isEmptyFilterValue,
  matchFilterMeta,
  matchFilterMetaWithRow,
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

describe('collectFilterCandidates (leg-fallback resolver)', () => {
  it('returns [root] when the root field is populated', () => {
    const row = {
      package_id: 'P1',
      tape_label: 'USD-SOFR 5Y Outright',
      legs_json: [{ tape_label: 'leg-level' }],
    }
    expect(collectFilterCandidates(row, 'tape_label')).toEqual([
      'USD-SOFR 5Y Outright',
    ])
  })

  it('falls back to leg values when the root is null (Platform)', () => {
    const row = {
      package_id: 'P2',
      platform_identifier: null,
      legs_json: [
        { platform_identifier: 'TWSF' },
        { platform_identifier: 'BBSF' },
      ],
    }
    expect(collectFilterCandidates(row, 'platform_identifier')).toEqual([
      'TWSF',
      'BBSF',
    ])
  })

  it('falls back to leg values for lifecycle_type', () => {
    const row = {
      package_id: 'P3',
      lifecycle_type: undefined,
      legs_json: [
        { lifecycle_type: 'NEW_TRADE' },
        { lifecycle_type: 'TERMINATION' },
      ],
    }
    expect(collectFilterCandidates(row, 'lifecycle_type')).toEqual([
      'NEW_TRADE',
      'TERMINATION',
    ])
  })

  it('returns [root] (nullish) when neither root nor legs carry data', () => {
    const row = { package_id: 'P4', legs_json: [{}] }
    expect(collectFilterCandidates(row as any, 'platform_identifier')).toEqual([
      undefined,
    ])
  })
})

describe('matchFilterMetaWithRow', () => {
  it('passes a leg-only Platform contains-filter when any leg matches', () => {
    const row = {
      package_id: 'P5',
      platform_identifier: null,
      legs_json: [{ platform_identifier: 'TWSF' }, { platform_identifier: 'BBSF' }],
    }
    const meta = {
      operator: FilterOperator.AND,
      constraints: [
        { value: 'TWSF', matchMode: FilterMatchMode.EQUALS },
      ],
    }
    expect(matchFilterMetaWithRow(row as any, 'platform_identifier', meta)).toBe(
      true,
    )
  })

  it('rejects a leg-only Platform contains-filter when no leg matches', () => {
    const row = {
      package_id: 'P6',
      platform_identifier: null,
      legs_json: [{ platform_identifier: 'XXXX' }],
    }
    const meta = {
      operator: FilterOperator.AND,
      constraints: [
        { value: 'TWSF', matchMode: FilterMatchMode.EQUALS },
      ],
    }
    expect(matchFilterMetaWithRow(row as any, 'platform_identifier', meta)).toBe(
      false,
    )
  })

  it('returns true when filter is empty regardless of row state', () => {
    const row = { package_id: 'P7', legs_json: [] }
    expect(
      matchFilterMetaWithRow(row as any, 'platform_identifier', {
        constraints: [{ value: '', matchMode: FilterMatchMode.CONTAINS }],
      }),
    ).toBe(true)
  })

  it('honors OR operator across leg values', () => {
    const row = {
      package_id: 'P8',
      platform_identifier: null,
      legs_json: [{ platform_identifier: 'TWSF' }],
    }
    const meta = {
      operator: FilterOperator.OR,
      constraints: [
        { value: 'BBSF', matchMode: FilterMatchMode.EQUALS },
        { value: 'TWSF', matchMode: FilterMatchMode.EQUALS },
      ],
    }
    expect(matchFilterMetaWithRow(row as any, 'platform_identifier', meta)).toBe(
      true,
    )
  })
})

describe('timestamp column filtering', () => {
  // The Time column renders M/D/YYYY HH:MM:SS in the NYC desk timezone.
  // The filter should compare against THAT visible string, not the raw
  // ISO timestamp the SDR feed delivers.
  const row = {
    // 2026-04-23T21:22:23Z = 2026-04-23 17:22:23 ET — the value the
    // user reported couldn't be filtered with "04/23".
    execution_start: '2026-04-23T21:22:23.000Z',
  }

  it('returns the NYC-formatted display string for execution_start', () => {
    const candidates = collectFilterCandidates(row as any, 'execution_start')
    expect(candidates).toHaveLength(1)
    expect(candidates[0]).toMatch(/4\/23\/2026 17:22:23/)
  })

  it('matches "04/23" with leading zero (the user-reported case)', () => {
    const meta = {
      operator: FilterOperator.AND,
      constraints: [{ value: '04/23', matchMode: FilterMatchMode.CONTAINS }],
    }
    expect(matchFilterMetaWithRow(row as any, 'execution_start', meta)).toBe(true)
  })

  it('matches "4/23" without leading zero', () => {
    const meta = {
      operator: FilterOperator.AND,
      constraints: [{ value: '4/23', matchMode: FilterMatchMode.CONTAINS }],
    }
    expect(matchFilterMetaWithRow(row as any, 'execution_start', meta)).toBe(true)
  })

  it('matches "04/23/2026" (full date)', () => {
    const meta = {
      operator: FilterOperator.AND,
      constraints: [{ value: '04/23/2026', matchMode: FilterMatchMode.CONTAINS }],
    }
    expect(matchFilterMetaWithRow(row as any, 'execution_start', meta)).toBe(true)
  })

  it('matches a partial time like "17:22"', () => {
    const meta = {
      operator: FilterOperator.AND,
      constraints: [{ value: '17:22', matchMode: FilterMatchMode.CONTAINS }],
    }
    expect(matchFilterMetaWithRow(row as any, 'execution_start', meta)).toBe(true)
  })

  it('rejects a non-matching date', () => {
    const meta = {
      operator: FilterOperator.AND,
      constraints: [{ value: '04/22', matchMode: FilterMatchMode.CONTAINS }],
    }
    expect(matchFilterMetaWithRow(row as any, 'execution_start', meta)).toBe(false)
  })

  it('STARTS_WITH respects the formatted display string', () => {
    const meta = {
      operator: FilterOperator.AND,
      constraints: [{ value: '4/23', matchMode: FilterMatchMode.STARTS_WITH }],
    }
    expect(matchFilterMetaWithRow(row as any, 'execution_start', meta)).toBe(true)
  })

  it('handles JS Date row values (pg driver shape)', () => {
    const dateRow = {
      execution_start: new Date('2026-04-23T21:22:23.000Z'),
    }
    const meta = {
      operator: FilterOperator.AND,
      constraints: [{ value: '04/23', matchMode: FilterMatchMode.CONTAINS }],
    }
    expect(matchFilterMetaWithRow(dateRow as any, 'execution_start', meta)).toBe(true)
  })

  it('non-timestamp fields keep raw-string semantics (no leading-zero strip)', () => {
    // A platform field with a leading-zero token should NOT have the
    // leading-zero collapse applied — that would break category equality.
    const platRow = { platform_identifier: '0BLT' }
    const meta = {
      operator: FilterOperator.AND,
      constraints: [{ value: '0BLT', matchMode: FilterMatchMode.EQUALS }],
    }
    expect(matchFilterMetaWithRow(platRow as any, 'platform_identifier', meta)).toBe(
      true,
    )
  })
})
