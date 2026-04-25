import { describe, expect, it } from '@jest/globals'
import {
  buildCleanTapeClause,
  buildLifecycleClause,
  buildTapeQuery,
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
})
