import { describe, expect, it } from '@jest/globals'
import {
  parseStructureGridParams,
  buildStructureGridSql,
  buildStructureSqlTimeOfDay,
  buildStructureSqlRolling,
  resolveStructureForwardSchema,
  shapeStructureGridResponse,
  computeWindowBounds,
} from '../route.logic'
import type { StructureDef } from '@/features/usd-swaps-tape-v2/types/structure-grid.types'

const SAMPLE_STRUCTURES: StructureDef[] = [
  { id: '2s10s', label: '2s10s', tenors: [2, 10], tolerance: 0.125 },
  { id: '5s30s', label: '5s30s', tenors: [5, 30], tolerance: 0.125 },
]

const structuresJson = JSON.stringify(SAMPLE_STRUCTURES)

// -----------------------------------------------------------------------
// parseStructureGridParams
// -----------------------------------------------------------------------

describe('parseStructureGridParams', () => {
  it('accepts valid params with required fields', () => {
    const out = parseStructureGridParams(
      new URLSearchParams(`structureType=curve&structures=${encodeURIComponent(structuresJson)}`),
    )
    expect(out).toEqual({
      ok: true,
      value: {
        structureType: 'curve',
        structures: SAMPLE_STRUCTURES,
        metric: 'dv01',
        period: 'today',
        lookbackDays: 90,
        forwardSchema: 'structure_default',
      },
    })
  })

  it('missing structureType returns error', () => {
    const out = parseStructureGridParams(
      new URLSearchParams(`structures=${encodeURIComponent(structuresJson)}`),
    )
    expect(out.ok).toBe(false)
    if (!out.ok) expect(out.error).toContain('structureType is required')
  })

  it('missing structures returns error', () => {
    const out = parseStructureGridParams(
      new URLSearchParams('structureType=curve'),
    )
    expect(out.ok).toBe(false)
    if (!out.ok) expect(out.error).toContain('structures is required')
  })

  it('invalid structureType returns error', () => {
    const out = parseStructureGridParams(
      new URLSearchParams(`structureType=spread&structures=${encodeURIComponent(structuresJson)}`),
    )
    expect(out.ok).toBe(false)
    if (!out.ok) expect(out.error).toContain('structureType must be')
  })

  it('invalid JSON structures returns error', () => {
    const out = parseStructureGridParams(
      new URLSearchParams('structureType=curve&structures=not-json'),
    )
    expect(out.ok).toBe(false)
    if (!out.ok) expect(out.error).toContain('structures must be valid JSON')
  })

  it('empty array structures returns error', () => {
    const out = parseStructureGridParams(
      new URLSearchParams(`structureType=curve&structures=${encodeURIComponent('[]')}`),
    )
    expect(out.ok).toBe(false)
    if (!out.ok) expect(out.error).toContain('non-empty')
  })

  it('default metric is dv01 (not notional)', () => {
    const out = parseStructureGridParams(
      new URLSearchParams(`structureType=fly&structures=${encodeURIComponent(structuresJson)}`),
    )
    expect(out.ok).toBe(true)
    if (out.ok) expect(out.value.metric).toBe('dv01')
  })

  it('default forwardSchema is structure_default', () => {
    const out = parseStructureGridParams(
      new URLSearchParams(`structureType=curve&structures=${encodeURIComponent(structuresJson)}`),
    )
    expect(out.ok).toBe(true)
    if (out.ok) expect(out.value.forwardSchema).toBe('structure_default')
  })

  it('accepts forwardSchema=default', () => {
    const out = parseStructureGridParams(
      new URLSearchParams(`structureType=curve&structures=${encodeURIComponent(structuresJson)}&forwardSchema=default`),
    )
    expect(out.ok).toBe(true)
    if (out.ok) expect(out.value.forwardSchema).toBe('default')
  })

  it('accepts metric=notional override', () => {
    const out = parseStructureGridParams(
      new URLSearchParams(`structureType=curve&structures=${encodeURIComponent(structuresJson)}&metric=notional`),
    )
    expect(out.ok).toBe(true)
    if (out.ok) expect(out.value.metric).toBe('notional')
  })

  it('rejects invalid metric', () => {
    const out = parseStructureGridParams(
      new URLSearchParams(`structureType=curve&structures=${encodeURIComponent(structuresJson)}&metric=pnl`),
    )
    expect(out.ok).toBe(false)
  })

  it('accepts textFilter', () => {
    const out = parseStructureGridParams(
      new URLSearchParams(`structureType=curve&structures=${encodeURIComponent(structuresJson)}&textFilter=Fed`),
    )
    expect(out.ok).toBe(true)
    if (out.ok) expect(out.value.textFilter).toBe('Fed')
  })

  it('omits textFilter when not provided', () => {
    const out = parseStructureGridParams(
      new URLSearchParams(`structureType=curve&structures=${encodeURIComponent(structuresJson)}`),
    )
    expect(out.ok).toBe(true)
    if (out.ok) expect(out.value.textFilter).toBeUndefined()
  })

  it('rejects invalid period', () => {
    const out = parseStructureGridParams(
      new URLSearchParams(`structureType=curve&structures=${encodeURIComponent(structuresJson)}&period=5d`),
    )
    expect(out.ok).toBe(false)
  })

  it('rejects lookbackDays above 730', () => {
    const out = parseStructureGridParams(
      new URLSearchParams(`structureType=curve&structures=${encodeURIComponent(structuresJson)}&lookbackDays=731`),
    )
    expect(out.ok).toBe(false)
  })

  it('rejects invalid forwardSchema', () => {
    const out = parseStructureGridParams(
      new URLSearchParams(`structureType=curve&structures=${encodeURIComponent(structuresJson)}&forwardSchema=bogus`),
    )
    expect(out.ok).toBe(false)
  })

  it('accepts fly structureType', () => {
    const flyStructures = JSON.stringify([
      { id: '2s5s10s', label: '2s5s10s', tenors: [2, 5, 10], tolerance: 0.125 },
    ])
    const out = parseStructureGridParams(
      new URLSearchParams(`structureType=fly&structures=${encodeURIComponent(flyStructures)}`),
    )
    expect(out.ok).toBe(true)
    if (out.ok) expect(out.value.structureType).toBe('fly')
  })
})

// -----------------------------------------------------------------------
// resolveStructureForwardSchema
// -----------------------------------------------------------------------

describe('resolveStructureForwardSchema', () => {
  it('resolves structure_default to curated buckets with spot + IMM + round-year', () => {
    const schema = resolveStructureForwardSchema('structure_default', new Date('2026-05-05T12:00:00Z'))
    expect(schema.id).toBe('structure_default')
    expect(schema.kind).toBe('years')
    const ids = schema.buckets.map((b) => b.id)
    expect(ids).toContain('spot')
    expect(ids).toContain('1y')
    expect(ids).toContain('2y')
    expect(ids).toContain('5y')
  })

  it('delegates to standard resolveForwardSchema for non-structure_default ids', () => {
    const schema = resolveStructureForwardSchema('default')
    expect(schema.id).toBe('default')
    expect(schema.buckets.length).toBeGreaterThan(0)
  })
})

// -----------------------------------------------------------------------
// buildStructureSqlTimeOfDay
// -----------------------------------------------------------------------

describe('buildStructureSqlTimeOfDay', () => {
  const fwd = resolveStructureForwardSchema('structure_default', new Date('2026-05-05T14:32:00Z'))
  const bounds = computeWindowBounds('today', 90, new Date('2026-05-05T14:32:00Z'))

  it('includes structure_defs CTE with VALUES from structures param', () => {
    const built = buildStructureSqlTimeOfDay({
      structureType: 'curve',
      structures: SAMPLE_STRUCTURES,
      metric: 'dv01',
      forwardSchema: fwd,
      bounds,
    })
    expect(built.sql).toContain('structure_defs')
    expect(built.sql).toContain("'2s10s'")
    expect(built.sql).toContain("'5s30s'")
    expect(built.sql).toContain('ARRAY[2::numeric, 10::numeric]')
  })

  it('filters curve package types', () => {
    const built = buildStructureSqlTimeOfDay({
      structureType: 'curve',
      structures: SAMPLE_STRUCTURES,
      metric: 'dv01',
      forwardSchema: fwd,
      bounds,
    })
    expect(built.params).toContain('CURVE')
    expect(built.params).toContain('SPREADOVER_CURVE')
    expect(built.params).toContain('MATCHED_MATURITY_CURVE')
  })

  it('filters fly package types for structureType=fly', () => {
    const built = buildStructureSqlTimeOfDay({
      structureType: 'fly',
      structures: SAMPLE_STRUCTURES,
      metric: 'dv01',
      forwardSchema: fwd,
      bounds,
    })
    expect(built.params).toContain('FLY')
    expect(built.params).toContain('SPREADOVER_FLY')
    expect(built.params).toContain('MATCHED_MATURITY_FLY')
  })

  it('uses leg_count for risk leg rank (curves = long leg)', () => {
    const built = buildStructureSqlTimeOfDay({
      structureType: 'curve',
      structures: SAMPLE_STRUCTURES,
      metric: 'dv01',
      forwardSchema: fwd,
      bounds,
    })
    expect(built.sql).toContain('leg_rank = leg_count')
  })

  it('uses rank 2 for risk leg rank (flies = belly leg)', () => {
    const built = buildStructureSqlTimeOfDay({
      structureType: 'fly',
      structures: SAMPLE_STRUCTURES,
      metric: 'dv01',
      forwardSchema: fwd,
      bounds,
    })
    expect(built.sql).toContain('leg_rank = 2')
  })

  it('uses risk_leg_value for metric=dv01', () => {
    const built = buildStructureSqlTimeOfDay({
      structureType: 'curve',
      structures: SAMPLE_STRUCTURES,
      metric: 'dv01',
      forwardSchema: fwd,
      bounds,
    })
    expect(built.sql).toContain('risk_leg_value')
  })

  it('uses notional_leg_value for metric=notional', () => {
    const built = buildStructureSqlTimeOfDay({
      structureType: 'curve',
      structures: SAMPLE_STRUCTURES,
      metric: 'notional',
      forwardSchema: fwd,
      bounds,
    })
    expect(built.sql).toContain('notional_leg_value')
  })

  it('emits platform CASE with unqualified column names', () => {
    const built = buildStructureSqlTimeOfDay({
      structureType: 'curve',
      structures: SAMPLE_STRUCTURES,
      metric: 'dv01',
      forwardSchema: fwd,
      bounds,
    })
    // Should NOT have `l.venue` or `l.platform_identifier` in the bucketed CTE
    expect(built.sql).toContain("COALESCE(venue, '')")
    expect(built.sql).toContain("COALESCE(platform_identifier, '')")
  })

  it('includes IDB/CUSTY platform filter aggregates', () => {
    const built = buildStructureSqlTimeOfDay({
      structureType: 'curve',
      structures: SAMPLE_STRUCTURES,
      metric: 'dv01',
      forwardSchema: fwd,
      bounds,
    })
    expect(built.sql).toContain("FILTER (WHERE platform = 'IDB')")
    expect(built.sql).toContain("FILTER (WHERE platform = 'CUSTY')")
  })

  it('includes ILIKE clause when textFilter present', () => {
    const built = buildStructureSqlTimeOfDay({
      structureType: 'curve',
      structures: SAMPLE_STRUCTURES,
      metric: 'dv01',
      forwardSchema: fwd,
      bounds,
      textFilter: 'Fed',
    })
    expect(built.sql).toContain('ILIKE')
    expect(built.params).toContain('Fed')
  })

  it('uses structure_id as tenor_bucket', () => {
    const built = buildStructureSqlTimeOfDay({
      structureType: 'curve',
      structures: SAMPLE_STRUCTURES,
      metric: 'dv01',
      forwardSchema: fwd,
      bounds,
    })
    expect(built.sql).toContain('structure_id AS tenor_bucket')
  })
})

// -----------------------------------------------------------------------
// buildStructureSqlRolling
// -----------------------------------------------------------------------

describe('buildStructureSqlRolling', () => {
  const fwd = resolveStructureForwardSchema('structure_default', new Date('2026-05-05T14:32:00Z'))
  const bounds = computeWindowBounds('1w', 90, new Date('2026-05-05T14:32:00Z'))

  it('includes windowed CTE with rolling window split', () => {
    const built = buildStructureSqlRolling({
      structureType: 'curve',
      structures: SAMPLE_STRUCTURES,
      metric: 'dv01',
      forwardSchema: fwd,
      bounds,
    })
    expect(built.sql).toContain('window_kind')
    expect(built.sql).toContain('baseline_window_id')
    expect(built.sql).toContain("date_trunc('week'")
  })

  it('includes structure_defs and CROSS JOIN in rolling mode', () => {
    const built = buildStructureSqlRolling({
      structureType: 'curve',
      structures: SAMPLE_STRUCTURES,
      metric: 'dv01',
      forwardSchema: fwd,
      bounds,
    })
    expect(built.sql).toContain('structure_defs')
    expect(built.sql).toContain('CROSS JOIN structure_defs s')
  })
})

// -----------------------------------------------------------------------
// buildStructureGridSql dispatch
// -----------------------------------------------------------------------

describe('buildStructureGridSql dispatch', () => {
  const fwd = resolveStructureForwardSchema('structure_default')

  it('dispatches to time_of_day for today', () => {
    const bounds = computeWindowBounds('today', 90, new Date())
    const built = buildStructureGridSql({
      structureType: 'curve',
      structures: SAMPLE_STRUCTURES,
      metric: 'dv01',
      forwardSchema: fwd,
      bounds,
    })
    expect(built.sql).toContain('day_et = $3')
  })

  it('dispatches to rolling for 1w', () => {
    const bounds = computeWindowBounds('1w', 90, new Date())
    const built = buildStructureGridSql({
      structureType: 'curve',
      structures: SAMPLE_STRUCTURES,
      metric: 'dv01',
      forwardSchema: fwd,
      bounds,
    })
    expect(built.sql).not.toContain('day_et = $3')
    expect(built.sql).toContain('window_kind')
  })
})

// -----------------------------------------------------------------------
// shapeStructureGridResponse
// -----------------------------------------------------------------------

describe('shapeStructureGridResponse', () => {
  it('maps rows to cells filtering by valid forward/structure ids', () => {
    const fwd = resolveStructureForwardSchema('structure_default', new Date('2026-05-05T12:00:00Z'))
    const params = {
      structureType: 'curve' as const,
      structures: SAMPLE_STRUCTURES,
      metric: 'dv01' as const,
      period: 'today' as const,
      lookbackDays: 90,
      forwardSchema: 'structure_default' as const,
    }
    const out = shapeStructureGridResponse(
      [
        {
          fwd: 'spot', tenor: '2s10s',
          current_value: 100, idb_current: 40, custy_current: 60,
          outright_current: 0, curve_current: 100, fly_current: 0, invoice_current: 0, other_current: 0,
          trade_count: 5, prior_array: [80, 90, 110],
          p25: 80, p50: 90, p75: 110, pmin: 80, pmax: 110, n: 3,
          as_of_ts: '2026-05-05T14:00:00Z',
        },
        // This row has an unknown structure id and should be filtered out
        {
          fwd: 'spot', tenor: 'unknown_structure',
          current_value: 50, idb_current: 0, custy_current: 50,
          outright_current: 0, curve_current: 0, fly_current: 0, invoice_current: 0, other_current: 0,
          trade_count: 1, prior_array: [],
          p25: 0, p50: 0, p75: 0, pmin: 0, pmax: 0, n: 0,
          as_of_ts: null,
        },
      ],
      params,
      fwd,
    )
    expect(out.cells.length).toBe(1)
    expect(out.cells[0].fwd).toBe('spot')
    expect(out.cells[0].tenor).toBe('2s10s')
    expect(out.cells[0].current).toBe(100)
    expect(out.cells[0].idbCurrent).toBe(40)
    expect(out.cells[0].custyCurrent).toBe(60)
    expect(out.cells[0].percentile).not.toBeNull()
    expect(out.structureType).toBe('curve')
    expect(out.metric).toBe('dv01')
    expect(out.axes.structure.buckets).toEqual([
      { id: '2s10s', label: '2s10s' },
      { id: '5s30s', label: '5s30s' },
    ])
  })

  it('computes totals correctly', () => {
    const fwd = resolveStructureForwardSchema('structure_default', new Date('2026-05-05T12:00:00Z'))
    const params = {
      structureType: 'curve' as const,
      structures: SAMPLE_STRUCTURES,
      metric: 'dv01' as const,
      period: 'today' as const,
      lookbackDays: 90,
      forwardSchema: 'structure_default' as const,
    }
    const out = shapeStructureGridResponse(
      [
        {
          fwd: 'spot', tenor: '2s10s',
          current_value: 100, idb_current: 40, custy_current: 60,
          outright_current: 0, curve_current: 100, fly_current: 0, invoice_current: 0, other_current: 0,
          trade_count: 5, prior_array: [], p25: 0, p50: 0, p75: 0, pmin: 0, pmax: 0, n: 0,
          as_of_ts: null,
        },
        {
          fwd: 'spot', tenor: '5s30s',
          current_value: 50, idb_current: 20, custy_current: 30,
          outright_current: 0, curve_current: 50, fly_current: 0, invoice_current: 0, other_current: 0,
          trade_count: 2, prior_array: [], p25: 0, p50: 0, p75: 0, pmin: 0, pmax: 0, n: 0,
          as_of_ts: null,
        },
      ],
      params,
      fwd,
    )
    expect(out.totals.grand.current).toBe(150)
    expect(out.totals.rowTotals['spot'].current).toBe(150)
    expect(out.totals.colTotals['2s10s'].current).toBe(100)
    expect(out.totals.colTotals['5s30s'].current).toBe(50)
  })
})
