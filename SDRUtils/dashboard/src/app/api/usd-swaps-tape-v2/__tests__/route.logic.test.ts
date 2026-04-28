import { describe, expect, it } from '@jest/globals'
import {
  buildCleanTapeClause,
  buildColumnFilterClause,
  buildLifecycleClause,
  buildTapeQuery,
  parseDatePattern,
  parseParams,
} from '../route.logic'

const VIEW = 'arbs_usd_swap_tape_display_v2'
const COLUMNS = 'd.*'

function paramsOf(qs: string) {
  const result = parseParams(new URLSearchParams(qs))
  if (!result.ok) throw new Error(result.error)
  return result.value
}

describe('parseParams', () => {
  it('defaults to clean=false', () => {
    expect(paramsOf('').clean).toBe(false)
  })

  it('respects clean=true', () => {
    expect(paramsOf('clean=true').clean).toBe(true)
  })

  it('rejects cursor + since simultaneously', () => {
    const result = parseParams(new URLSearchParams('cursor=a&since=b'))
    expect(result.ok).toBe(false)
  })

  it('caps limit at MAX_LIMIT', () => {
    expect(paramsOf('limit=10000').limit).toBe(500)
  })

  it('parses lifecycle CSV and normalizes to lowercase', () => {
    expect(paramsOf('lifecycle=new_risk,UNWIND').lifecycle).toEqual([
      'new_risk',
      'unwind',
    ])
  })

  it('rejects unknown lifecycle values', () => {
    const result = parseParams(new URLSearchParams('lifecycle=banana'))
    expect(result.ok).toBe(false)
  })

  it('rejects unknown venue value', () => {
    const result = parseParams(new URLSearchParams('venues=DESK'))
    expect(result.ok).toBe(false)
  })
})

describe('buildCleanTapeClause', () => {
  it('lists every noise flag', () => {
    const clause = buildCleanTapeClause()
    expect(clause).toContain('NOT d.is_unwind')
    expect(clause).toContain('NOT d.is_compression_any')
    expect(clause).toContain('NOT d.is_ufro_any')
    expect(clause).toContain('NOT d.is_reset_optimization_any')
    expect(clause).toContain('NOT d.is_clearing_termination_any')
  })

  it('drops matrix-administrative rows (Phase 3)', () => {
    const clause = buildCleanTapeClause()
    expect(clause).toContain('contributes_to_flow_any')
    expect(clause).toContain('TRUE')
  })

  it('drops state-machine-violating rows', () => {
    const clause = buildCleanTapeClause()
    expect(clause).toContain('state_machine_violation_any')
  })
})

describe('buildLifecycleClause', () => {
  it('returns null for empty selection', () => {
    expect(buildLifecycleClause([])).toBeNull()
  })

  it('ORs each selected lifecycle to its flag', () => {
    const clause = buildLifecycleClause(['new_risk', 'unwind'])
    expect(clause).toContain('d.is_new_risk')
    expect(clause).toContain('d.is_unwind')
    expect(clause).toContain(' OR ')
  })
})

describe('buildTapeQuery', () => {
  it('produces a WHERE-free query when no filters are set', () => {
    const { sql } = buildTapeQuery(paramsOf(''), VIEW, COLUMNS)
    expect(sql).not.toMatch(/WHERE/)
    expect(sql).toMatch(/ORDER BY d\.execution_start DESC/)
  })

  it('adds the clean-tape WHERE fragment when clean=true', () => {
    const { sql } = buildTapeQuery(paramsOf('clean=true'), VIEW, COLUMNS)
    expect(sql).toMatch(/NOT d\.is_unwind/)
    expect(sql).toMatch(/NOT d\.is_compression_any/)
    expect(sql).toMatch(/NOT d\.is_ufro_any/)
  })

  it('adds lifecycle OR predicate when lifecycle CSV is set', () => {
    const { sql } = buildTapeQuery(
      paramsOf('lifecycle=new_risk,unwind'),
      VIEW,
      COLUMNS,
    )
    expect(sql).toMatch(/d\.is_new_risk/)
    expect(sql).toMatch(/d\.is_unwind/)
  })

  it('pushes category params in order', () => {
    const { sql, params } = buildTapeQuery(
      paramsOf('venues=D2D&ccps=LCH'),
      VIEW,
      COLUMNS,
    )
    expect(sql).toMatch(/d\.venue IN/)
    expect(sql).toMatch(/d\.ccp IN/)
    // params: D2D, LCH, limit+1
    expect(params[0]).toBe('D2D')
    expect(params[1]).toBe('LCH')
    expect(params[params.length - 1]).toBe(201)
  })

  it('adds a fomc_meeting_label equality predicate', () => {
    const { sql, params } = buildTapeQuery(
      paramsOf('fomcMeeting=APR26'),
      VIEW,
      COLUMNS,
    )
    expect(sql).toMatch(/d\.fomc_meeting_label = \$1/)
    expect(params[0]).toBe('APR26')
  })

  it('treats global filter as ILIKE across label/structure/tenors/package_id', () => {
    const { sql, params } = buildTapeQuery(
      paramsOf('filter=SOFR'),
      VIEW,
      COLUMNS,
    )
    expect(sql).toMatch(/d\.tape_label ILIKE/)
    expect(sql).toMatch(/d\.package_structure ILIKE/)
    expect(params[0]).toBe('%SOFR%')
  })

  it('passes cursor as execution_start upper bound', () => {
    const { sql, params } = buildTapeQuery(
      paramsOf('cursor=2026-04-14T00:00:00Z'),
      VIEW,
      COLUMNS,
    )
    expect(sql).toMatch(/d\.execution_start < \$1/)
    expect(params[0]).toBe('2026-04-14T00:00:00Z')
  })

  it('emits column-filter WHERE clause for tape_label CONTAINS', () => {
    const url = new URLSearchParams()
    url.set(
      'columnFilters',
      JSON.stringify({
        tape_label: {
          operator: 'and',
          constraints: [{ value: '10Y', matchMode: 'contains' }],
        },
      }),
    )
    const parsed = parseParams(url)
    if (!parsed.ok) throw new Error(parsed.error)
    const { sql, params } = buildTapeQuery(parsed.value, VIEW, COLUMNS)
    expect(sql).toMatch(/d\.tape_label ILIKE \$1/)
    expect(params[0]).toBe('%10Y%')
  })

  it('column-filter clause composes with existing WHERE fragments', () => {
    const url = new URLSearchParams()
    url.set('clean', 'true')
    url.set(
      'columnFilters',
      JSON.stringify({
        tape_label: {
          operator: 'and',
          constraints: [{ value: '10Y', matchMode: 'contains' }],
        },
      }),
    )
    const parsed = parseParams(url)
    if (!parsed.ok) throw new Error(parsed.error)
    const { sql } = buildTapeQuery(parsed.value, VIEW, COLUMNS)
    expect(sql).toMatch(/NOT d\.is_unwind/)
    expect(sql).toMatch(/d\.tape_label ILIKE/)
  })

  it('omits the column-filter clause when columnFilters is empty', () => {
    const { sql } = buildTapeQuery(paramsOf(''), VIEW, COLUMNS)
    expect(sql).not.toMatch(/d\.tape_label ILIKE/)
  })
})

describe('buildColumnFilterClause', () => {
  it('returns null for empty filters object', () => {
    const params: unknown[] = []
    expect(buildColumnFilterClause({}, params)).toBeNull()
    expect(params).toEqual([])
  })

  it('ignores fields not in the allowlist', () => {
    const params: unknown[] = []
    const clause = buildColumnFilterClause(
      {
        not_a_column: {
          operator: 'and',
          constraints: [{ value: 'x', matchMode: 'contains' }],
        },
      },
      params,
    )
    expect(clause).toBeNull()
    expect(params).toEqual([])
  })

  it('CONTAINS on tape_label: ILIKE %x% with escaped value', () => {
    const params: unknown[] = []
    const clause = buildColumnFilterClause(
      {
        tape_label: {
          operator: 'and',
          constraints: [{ value: '10Y', matchMode: 'contains' }],
        },
      },
      params,
    )
    expect(clause).toMatch(/d\.tape_label ILIKE \$1/)
    expect(params).toEqual(['%10Y%'])
  })

  it('escapes %, _, \\ in CONTAINS values so they are literal', () => {
    const params: unknown[] = []
    buildColumnFilterClause(
      {
        tape_label: {
          operator: 'and',
          constraints: [{ value: '5%_x', matchMode: 'contains' }],
        },
      },
      params,
    )
    expect(params).toEqual(['%5\\%\\_x%'])
  })

  it('STARTS_WITH on tape_label uses prefix pattern', () => {
    const params: unknown[] = []
    const clause = buildColumnFilterClause(
      {
        tape_label: {
          operator: 'and',
          constraints: [{ value: '10Y', matchMode: 'startsWith' }],
        },
      },
      params,
    )
    expect(clause).toMatch(/d\.tape_label ILIKE \$1/)
    expect(params).toEqual(['10Y%'])
  })

  it('ENDS_WITH on tape_label uses suffix pattern', () => {
    const params: unknown[] = []
    buildColumnFilterClause(
      {
        tape_label: {
          operator: 'and',
          constraints: [{ value: 'OIS', matchMode: 'endsWith' }],
        },
      },
      params,
    )
    expect(params).toEqual(['%OIS'])
  })

  it('NOT_CONTAINS uses NOT ILIKE', () => {
    const params: unknown[] = []
    const clause = buildColumnFilterClause(
      {
        tape_label: {
          operator: 'and',
          constraints: [{ value: '10Y', matchMode: 'notContains' }],
        },
      },
      params,
    )
    expect(clause).toMatch(/d\.tape_label NOT ILIKE/)
  })

  it('EQUALS on text column compares LOWER(col)', () => {
    const params: unknown[] = []
    const clause = buildColumnFilterClause(
      {
        package_type: {
          operator: 'and',
          constraints: [{ value: 'CURVE', matchMode: 'equals' }],
        },
      },
      params,
    )
    expect(clause).toMatch(/LOWER\(d\.package_type\) = \$1/)
    expect(params).toEqual(['curve'])
  })

  it('NOT_EQUALS on text column uses LOWER(col) <>', () => {
    const params: unknown[] = []
    const clause = buildColumnFilterClause(
      {
        package_type: {
          operator: 'and',
          constraints: [{ value: 'CURVE', matchMode: 'notEquals' }],
        },
      },
      params,
    )
    expect(clause).toMatch(/LOWER\(d\.package_type\) <> \$1/)
    expect(params).toEqual(['curve'])
  })

  it('IN on text column ORs each lowercased value', () => {
    const params: unknown[] = []
    const clause = buildColumnFilterClause(
      {
        package_type: {
          operator: 'and',
          constraints: [{ value: ['CURVE', 'FLY'], matchMode: 'in' }],
        },
      },
      params,
    )
    expect(clause).toMatch(
      /LOWER\(d\.package_type\) = \$1.*OR.*LOWER\(d\.package_type\) = \$2/,
    )
    expect(params).toEqual(['curve', 'fly'])
  })

  it('GREATER_THAN on numeric column casts numeric', () => {
    const params: unknown[] = []
    const clause = buildColumnFilterClause(
      {
        total_risk: {
          operator: 'and',
          constraints: [{ value: '50000', matchMode: 'gt' }],
        },
      },
      params,
    )
    expect(clause).toMatch(/d\.total_risk > \$1/)
    expect(params).toEqual([50000])
  })

  it('LESS_THAN_OR_EQUAL_TO on numeric column', () => {
    const params: unknown[] = []
    const clause = buildColumnFilterClause(
      {
        weighted_fixed_rate: {
          operator: 'and',
          constraints: [{ value: 0.04, matchMode: 'lte' }],
        },
      },
      params,
    )
    expect(clause).toMatch(/d\.weighted_fixed_rate <= \$1/)
    expect(params).toEqual([0.04])
  })

  it('skips non-numeric values for numeric fields', () => {
    const params: unknown[] = []
    const clause = buildColumnFilterClause(
      {
        total_risk: {
          operator: 'and',
          constraints: [{ value: 'abc', matchMode: 'gt' }],
        },
      },
      params,
    )
    expect(clause).toBeNull()
    expect(params).toEqual([])
  })

  it('LEG fields use EXISTS (jsonb_array_elements) — platform_identifier CONTAINS', () => {
    const params: unknown[] = []
    const clause = buildColumnFilterClause(
      {
        platform_identifier: {
          operator: 'and',
          constraints: [{ value: 'TWSF', matchMode: 'contains' }],
        },
      },
      params,
    )
    expect(clause).toMatch(
      /EXISTS \(SELECT 1 FROM jsonb_array_elements\(d\.legs_json\) l WHERE l->>'platform_identifier' ILIKE \$1\)/,
    )
    expect(params).toEqual(['%TWSF%'])
  })

  it('LEG field EQUALS — lifecycle_type', () => {
    const params: unknown[] = []
    const clause = buildColumnFilterClause(
      {
        lifecycle_type: {
          operator: 'and',
          constraints: [{ value: 'NEW_RISK', matchMode: 'equals' }],
        },
      },
      params,
    )
    expect(clause).toMatch(
      /EXISTS \(SELECT 1 FROM jsonb_array_elements\(d\.legs_json\) l WHERE LOWER\(l->>'lifecycle_type'\) = \$1\)/,
    )
    expect(params).toEqual(['new_risk'])
  })

  it('multiple fields are joined by AND', () => {
    const params: unknown[] = []
    const clause = buildColumnFilterClause(
      {
        tape_label: {
          operator: 'and',
          constraints: [{ value: '10Y', matchMode: 'contains' }],
        },
        package_type: {
          operator: 'and',
          constraints: [{ value: 'CURVE', matchMode: 'equals' }],
        },
      },
      params,
    )
    expect(clause).toMatch(
      /\(d\.tape_label ILIKE \$1\) AND \(LOWER\(d\.package_type\) = \$2\)/,
    )
    expect(params).toEqual(['%10Y%', 'curve'])
  })

  it('per-field OR joins constraints inside one field with OR', () => {
    const params: unknown[] = []
    const clause = buildColumnFilterClause(
      {
        tape_label: {
          operator: 'or',
          constraints: [
            { value: '10Y', matchMode: 'contains' },
            { value: '5Y', matchMode: 'contains' },
          ],
        },
      },
      params,
    )
    expect(clause).toMatch(
      /\(d\.tape_label ILIKE \$1 OR d\.tape_label ILIKE \$2\)/,
    )
    expect(params).toEqual(['%10Y%', '%5Y%'])
  })

  it('execution_start filter is NOT pushed (deferred)', () => {
    const params: unknown[] = []
    const clause = buildColumnFilterClause(
      {
        execution_start: {
          operator: 'and',
          constraints: [{ value: '04/23', matchMode: 'contains' }],
        },
      },
      params,
    )
    expect(clause).toBeNull()
    expect(params).toEqual([])
  })

  it('null / undefined / empty-string values produce no clause', () => {
    const params: unknown[] = []
    const clause = buildColumnFilterClause(
      {
        tape_label: {
          operator: 'and',
          constraints: [
            { value: null, matchMode: 'contains' },
            { value: '', matchMode: 'contains' },
            { value: undefined, matchMode: 'contains' },
          ],
        },
      },
      params,
    )
    expect(clause).toBeNull()
    expect(params).toEqual([])
  })
})

describe('parseDatePattern', () => {
  // Anchor today to a deterministic value so "current year" defaulting is
  // testable without time-mocking the runner.
  const TODAY = new Date('2026-04-28T15:00:00Z')

  it('parses M/D in current NYC year', () => {
    expect(parseDatePattern('4/21', TODAY)).toBe('2026-04-21')
  })

  it('parses MM/DD with leading zeros', () => {
    expect(parseDatePattern('04/21', TODAY)).toBe('2026-04-21')
  })

  it('parses M/D/YYYY', () => {
    expect(parseDatePattern('4/21/2026', TODAY)).toBe('2026-04-21')
  })

  it('parses MM/DD/YYYY', () => {
    expect(parseDatePattern('04/21/2026', TODAY)).toBe('2026-04-21')
  })

  it('parses M/D/YY (two-digit year, current century)', () => {
    expect(parseDatePattern('4/21/26', TODAY)).toBe('2026-04-21')
  })

  it('parses YYYY-MM-DD ISO', () => {
    expect(parseDatePattern('2026-04-21', TODAY)).toBe('2026-04-21')
  })

  it('parses YYYY-M-D ISO without leading zeros', () => {
    expect(parseDatePattern('2026-4-21', TODAY)).toBe('2026-04-21')
  })

  it('returns null for unparseable input', () => {
    expect(parseDatePattern('NEWFLOW', TODAY)).toBeNull()
    expect(parseDatePattern('5Y', TODAY)).toBeNull()
    expect(parseDatePattern('', TODAY)).toBeNull()
    expect(parseDatePattern('04/21 - 04/23', TODAY)).toBeNull()
    expect(parseDatePattern('>=2026-04-15', TODAY)).toBeNull()
  })

  it('returns null for impossible dates', () => {
    expect(parseDatePattern('13/40', TODAY)).toBeNull()
    expect(parseDatePattern('2026-02-30', TODAY)).toBeNull()
  })

  it('steps back a year if M/D defaults to a future date', () => {
    // anchor TODAY = 2027-01-05; trader types 12/30 — they meant
    // 2026-12-30 (recent past), not 2027-12-30 (future).
    const earlyJan = new Date('2027-01-05T15:00:00Z')
    expect(parseDatePattern('12/30', earlyJan)).toBe('2026-12-30')
  })

  it('does NOT step back when explicit year is supplied (even if future)', () => {
    const earlyJan = new Date('2027-01-05T15:00:00Z')
    // 12/30/2027 is explicit — keep it.
    expect(parseDatePattern('12/30/2027', earlyJan)).toBe('2027-12-30')
  })

  it('trims whitespace before parsing', () => {
    expect(parseDatePattern('  04/21  ', TODAY)).toBe('2026-04-21')
  })

  it('returns null for non-string input', () => {
    expect(parseDatePattern(null as any, TODAY)).toBeNull()
    expect(parseDatePattern(undefined as any, TODAY)).toBeNull()
    expect(parseDatePattern(0 as any, TODAY)).toBeNull()
  })
})
