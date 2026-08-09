import { describe, expect, it } from '@jest/globals'
import { TAPE_PACKAGES } from '@/lib/tape-tables'
import {
  parseVolumeGridCellParams,
  buildIntradaySeasonalitySql,
  buildTimeseriesSql,
  buildRecentTradesSql,
  buildStructureTimeseriesSql,
  buildStructureIntradaySeasonalitySql,
  buildStructureRecentTradesSql,
  easternDateKey,
  rangeToStartDate,
  shapeIntradaySeasonalityResponse,
} from '../route.logic'

describe('parseVolumeGridCellParams', () => {
  it('rejects missing fwd', () => {
    expect(parseVolumeGridCellParams(new URLSearchParams('tenor=5y')).ok).toBe(false)
  })
  it('rejects missing tenor', () => {
    expect(parseVolumeGridCellParams(new URLSearchParams('fwd=spot')).ok).toBe(false)
  })
  it('applies defaults — outright + default schemas', () => {
    const out = parseVolumeGridCellParams(new URLSearchParams('fwd=spot&tenor=5y'))
    expect(out.ok).toBe(true)
    if (out.ok) {
      expect(out.value).toMatchObject({
        metric: 'notional', range: '3M', recentLimit: 50,
        forwardSchema: 'default', tenorSchema: 'default', packageType: 'outright',
      })
    }
  })
  it('rejects bucket ids absent from the requested schema', () => {
    // 5_10y is a legacy tenor id, not in default schema
    expect(parseVolumeGridCellParams(new URLSearchParams('fwd=spot&tenor=5_10y')).ok).toBe(false)
    // works under legacy schema
    expect(parseVolumeGridCellParams(new URLSearchParams('fwd=spot&tenor=5_10y&tenorSchema=legacy')).ok).toBe(true)
  })
  it('rejects bogus packageType', () => {
    expect(parseVolumeGridCellParams(new URLSearchParams('fwd=spot&tenor=5y&packageType=bogus')).ok).toBe(false)
  })
  it('rejects unknown forwardSchema', () => {
    expect(parseVolumeGridCellParams(new URLSearchParams('fwd=spot&tenor=5y&forwardSchema=foo')).ok).toBe(false)
  })
  it('accepts FOMC schema with a meeting label fwd id', () => {
    const out = parseVolumeGridCellParams(
      new URLSearchParams('fwd=APR26&tenor=5y&forwardSchema=fomc&packageType=fomc'),
    )
    expect(out.ok).toBe(true)
  })
  it('rejects malformed FOMC label under fomc schema', () => {
    expect(
      parseVolumeGridCellParams(
        new URLSearchParams('fwd=garbage&tenor=5y&forwardSchema=fomc'),
      ).ok,
    ).toBe(false)
  })
  it('accepts venue MIC code as tenor under venue schema', () => {
    const out = parseVolumeGridCellParams(
      new URLSearchParams('fwd=spot&tenor=BBSF&tenorSchema=venue'),
    )
    expect(out.ok).toBe(true)
  })
  it('rejects malformed MIC under venue schema', () => {
    expect(
      parseVolumeGridCellParams(
        new URLSearchParams('fwd=spot&tenor=oops!&tenorSchema=venue'),
      ).ok,
    ).toBe(false)
  })
})

describe('rangeToStartDate', () => {
  it('1M subtracts ~30 days', () => {
    const now = new Date('2026-05-05T00:00:00Z')
    const out = rangeToStartDate('1M', now)
    const days = (now.getTime() - out.getTime()) / 86_400_000
    expect(days).toBeGreaterThanOrEqual(28)
    expect(days).toBeLessThanOrEqual(32)
  })
})

describe('buildTimeseriesSql', () => {
  it('joins packages and applies bucket + package filters', () => {
    const sql = buildTimeseriesSql({
      bucketPredicateSql: 'l.forward_start_years < 1',
      packageFilterSql: 'p.package_type IN ($2)',
    })
    expect(sql).toContain(`JOIN ${TAPE_PACKAGES} p ON p.package_id = l.package_id`)
    expect(sql).toContain('AND l.forward_start_years < 1')
    expect(sql).toContain('AND p.package_type IN ($2)')
    expect(sql).toContain('GROUP BY day')
  })
})

describe('buildIntradaySeasonalitySql', () => {
  it('builds a current-vs-baseline cumulative intraday profile query', () => {
    const sql = buildIntradaySeasonalitySql({
      metric: 'dv01',
      bucketPredicateSql: 'l.forward_start_years < $4',
      packageFilterSql: 'p.package_type IN ($5)',
    })
    expect(sql).toContain('generate_series')
    expect(sql).toContain(`JOIN ${TAPE_PACKAGES} p ON p.package_id = l.package_id`)
    expect(sql).toContain('baseline_cumulative')
    expect(sql).toContain('current_cumulative')
    expect(sql).toContain('SUM(dv01)')
  })
})

describe('shapeIntradaySeasonalityResponse', () => {
  it('nulls current points after the current as-of bucket and keeps the average line', () => {
    const out = shapeIntradaySeasonalityResponse([
      {
        bucket_index: 0,
        minute_of_day: 30,
        current_value: 10,
        average_value: 8,
        observed_days: 5,
        as_of_ts: '2026-05-05T13:05:00Z',
      },
      {
        bucket_index: 30,
        minute_of_day: 930,
        current_value: 20,
        average_value: 18,
        observed_days: 5,
        as_of_ts: '2026-05-05T13:05:00Z',
      },
    ])
    expect(out.bucketMinutes).toBe(1)
    expect(out.observedDays).toBe(5)
    expect(out.asOf).toBe('2026-05-05T13:05:00.000Z')
    expect(out.points[0]).toMatchObject({ minuteOfDay: 30, current: 10, average: 8 })
    expect(out.points[1]).toMatchObject({ minuteOfDay: 930, current: null, average: 18 })
  })
})

describe('easternDateKey', () => {
  it('formats dates in America/New_York', () => {
    expect(easternDateKey(new Date('2026-05-05T03:30:00Z'))).toBe('2026-05-04')
  })
})

describe('buildRecentTradesSql', () => {
  it('orders by execution_start DESC and uses the supplied limit param', () => {
    const sql = buildRecentTradesSql({
      bucketPredicateSql: 'TRUE',
      packageFilterSql: 'p.package_type IN ($2)',
      limitParam: '$3',
    })
    expect(sql).toContain('ORDER BY p.execution_start DESC')
    expect(sql).toContain('LIMIT $3')
  })
})

describe('buildRecentTradesSql with legs', () => {
  it('includes a json_agg legs subquery when inCellPredicateSql is provided', () => {
    const sql = buildRecentTradesSql({
      bucketPredicateSql: 'l.tenor_years >= $2 AND l.tenor_years < $3',
      packageFilterSql: 'TRUE',
      limitParam: '$4',
      inCellPredicateSql: 'l2.tenor_years >= $2 AND l2.tenor_years < $3',
    })
    expect(sql).toContain('json_agg')
    expect(sql).toContain('json_build_object')
    expect(sql).toContain('l2.tenor_years')
    expect(sql).toContain('l2.forward_start_years')
    expect(sql).toContain('in_cell')
    expect(sql).toContain('l2.package_id = p.package_id')
  })

  it('omits legs subquery when inCellPredicateSql is not provided', () => {
    const sql = buildRecentTradesSql({
      bucketPredicateSql: 'l.tenor_years >= $2',
      packageFilterSql: 'TRUE',
      limitParam: '$3',
    })
    expect(sql).not.toContain('json_agg')
    expect(sql).not.toContain('l2.')
  })
})

describe('parseVolumeGridCellParams — optional tenor', () => {
  it('allows missing tenor when forwardSchema=fomc', () => {
    const out = parseVolumeGridCellParams(
      new URLSearchParams('fwd=JUN26&forwardSchema=fomc&metric=dv01'),
    )
    expect(out.ok).toBe(true)
    if (out.ok) expect(out.value.tenor).toBeUndefined()
  })

  it('requires tenor when forwardSchema is not fomc', () => {
    const out = parseVolumeGridCellParams(
      new URLSearchParams('fwd=spot&forwardSchema=default&metric=dv01'),
    )
    expect(out.ok).toBe(false)
    if (!out.ok) expect(out.error).toContain('tenor')
  })

  it('passes textFilter through', () => {
    const out = parseVolumeGridCellParams(
      new URLSearchParams('fwd=JUN26&tenor=2y&forwardSchema=fomc&metric=dv01&textFilter=OIS'),
    )
    expect(out.ok).toBe(true)
    if (out.ok) expect(out.value.textFilter).toBe('OIS')
  })
})

describe('buildTimeseriesSql with textFilterSql', () => {
  it('appends textFilterSql to the WHERE clause when provided', () => {
    const sql = buildTimeseriesSql({
      bucketPredicateSql: 'TRUE',
      packageFilterSql: 'TRUE',
      textFilterSql: "(l.tape_label ILIKE '%' || $4::text || '%' OR p.tape_label ILIKE '%' || $4::text || '%')",
    })
    expect(sql).toContain('tape_label ILIKE')
  })

  it('omits textFilter clause when not provided', () => {
    const sql = buildTimeseriesSql({
      bucketPredicateSql: 'TRUE',
      packageFilterSql: 'TRUE',
    })
    expect(sql).not.toContain('tape_label ILIKE')
  })
})

describe('buildRecentTradesSql with textFilterSql', () => {
  it('appends textFilterSql to the WHERE clause when provided', () => {
    const sql = buildRecentTradesSql({
      bucketPredicateSql: 'TRUE',
      packageFilterSql: 'TRUE',
      textFilterSql: "(l.tape_label ILIKE '%' || $3::text || '%' OR p.tape_label ILIKE '%' || $3::text || '%')",
      limitParam: '$4',
    })
    expect(sql).toContain('tape_label ILIKE')
  })
})

describe('buildIntradaySeasonalitySql with textFilterSql', () => {
  it('appends textFilterSql to the WHERE clause when provided', () => {
    const sql = buildIntradaySeasonalitySql({
      metric: 'dv01',
      bucketPredicateSql: 'TRUE',
      packageFilterSql: 'TRUE',
      textFilterSql: "(l.tape_label ILIKE '%' || $5::text || '%' OR p.tape_label ILIKE '%' || $5::text || '%')",
    })
    expect(sql).toContain('tape_label ILIKE')
  })
})

// ---------------------------------------------------------------------------
// Structure mode parsing
// ---------------------------------------------------------------------------

describe('parseVolumeGridCellParams — structure mode', () => {
  it('parses valid structure params for a curve', () => {
    const out = parseVolumeGridCellParams(
      new URLSearchParams('fwd=spot&structureType=curve&structureTenors=[2,10]&metric=dv01'),
    )
    expect(out.ok).toBe(true)
    if (out.ok) {
      expect(out.value.structureType).toBe('curve')
      expect(out.value.structureTenors).toEqual([2, 10])
      expect(out.value.structureTolerance).toBe(0.125)
      // tenor is optional when structureType is set
      expect(out.value.tenor).toBeUndefined()
    }
  })

  it('parses valid structure params for a fly', () => {
    const out = parseVolumeGridCellParams(
      new URLSearchParams('fwd=spot&structureType=fly&structureTenors=[2,5,10]&structureTolerance=0.25'),
    )
    expect(out.ok).toBe(true)
    if (out.ok) {
      expect(out.value.structureType).toBe('fly')
      expect(out.value.structureTenors).toEqual([2, 5, 10])
      expect(out.value.structureTolerance).toBe(0.25)
    }
  })

  it('rejects missing structureTenors when structureType is set', () => {
    const out = parseVolumeGridCellParams(
      new URLSearchParams('fwd=spot&structureType=curve'),
    )
    expect(out.ok).toBe(false)
    if (!out.ok) expect(out.error).toContain('structureTenors')
  })

  it('rejects invalid structureType', () => {
    const out = parseVolumeGridCellParams(
      new URLSearchParams('fwd=spot&structureType=spread&structureTenors=[2,10]'),
    )
    expect(out.ok).toBe(false)
    if (!out.ok) expect(out.error).toContain('structureType')
  })

  it('rejects non-array structureTenors', () => {
    const out = parseVolumeGridCellParams(
      new URLSearchParams('fwd=spot&structureType=curve&structureTenors=notjson'),
    )
    expect(out.ok).toBe(false)
    if (!out.ok) expect(out.error).toContain('structureTenors')
  })

  it('rejects empty structureTenors array', () => {
    const out = parseVolumeGridCellParams(
      new URLSearchParams('fwd=spot&structureType=curve&structureTenors=[]'),
    )
    expect(out.ok).toBe(false)
    if (!out.ok) expect(out.error).toContain('structureTenors')
  })

  it('makes tenor optional when structureType is present', () => {
    const out = parseVolumeGridCellParams(
      new URLSearchParams('fwd=spot&structureType=curve&structureTenors=[2,10]'),
    )
    expect(out.ok).toBe(true)
    if (out.ok) expect(out.value.tenor).toBeUndefined()
  })

  it('still accepts tenor alongside structureType', () => {
    const out = parseVolumeGridCellParams(
      new URLSearchParams('fwd=spot&tenor=10y&structureType=curve&structureTenors=[2,10]'),
    )
    expect(out.ok).toBe(true)
    if (out.ok) {
      expect(out.value.tenor).toBe('10y')
      expect(out.value.structureType).toBe('curve')
    }
  })
})

// ---------------------------------------------------------------------------
// Structure mode SQL builders
// ---------------------------------------------------------------------------

describe('buildStructureTimeseriesSql', () => {
  it('builds a structure_match + risk_leg CTE query', () => {
    const sql = buildStructureTimeseriesSql({
      structureType: 'curve',
      tenors: [2, 10],
      tolerance: 0.125,
      fwdPredicateSql: 'forward_start_years < 0.0192',
      pkgTypePlaceholders: '$2, $3, $4, $5',
    })
    expect(sql).toContain('structure_match')
    expect(sql).toContain('risk_leg')
    expect(sql).toContain('ARRAY[2::numeric, 10::numeric]')
    expect(sql).toContain('leg_count = 2')
    // For curves, risk leg = max tenor = leg_count
    expect(sql).toContain('leg_rank = leg_count')
    expect(sql).toContain('GROUP BY day')
  })

  it('uses rank 2 for fly structures', () => {
    const sql = buildStructureTimeseriesSql({
      structureType: 'fly',
      tenors: [2, 5, 10],
      tolerance: 0.125,
      fwdPredicateSql: 'TRUE',
      pkgTypePlaceholders: '$2',
    })
    expect(sql).toContain('leg_count = 3')
    expect(sql).toContain('leg_rank = 2')
  })
})

describe('buildStructureIntradaySeasonalitySql', () => {
  it('builds intraday query with structure_match CTE', () => {
    const sql = buildStructureIntradaySeasonalitySql({
      metric: 'dv01',
      structureType: 'curve',
      tenors: [2, 10],
      tolerance: 0.125,
      fwdPredicateSql: 'TRUE',
      pkgTypePlaceholders: '$4, $5',
    })
    expect(sql).toContain('structure_match')
    expect(sql).toContain('generate_series')
    expect(sql).toContain('baseline_cumulative')
    expect(sql).toContain('current_cumulative')
    expect(sql).toContain('SUM(dv01)')
  })
})

describe('buildStructureRecentTradesSql', () => {
  it('builds recent trades query with structure_match and is_risk_leg', () => {
    const sql = buildStructureRecentTradesSql({
      structureType: 'curve',
      tenors: [2, 10],
      tolerance: 0.125,
      fwdPredicateSql: 'sm.forward_start_years < 0.0192',
      pkgTypePlaceholders: '$2, $3, $4, $5',
      limitParam: '$6',
    })
    expect(sql).toContain('structure_match')
    expect(sql).toContain('eligible_packages')
    expect(sql).toContain('is_risk_leg')
    expect(sql).toContain('json_agg')
    expect(sql).toContain('LIMIT $6')
    expect(sql).toContain('ORDER BY p.execution_start DESC')
  })

  it('includes text filter when provided', () => {
    const sql = buildStructureRecentTradesSql({
      structureType: 'fly',
      tenors: [2, 5, 10],
      tolerance: 0.125,
      fwdPredicateSql: 'TRUE',
      pkgTypePlaceholders: '$2',
      textFilterSql: "(l.tape_label ILIKE '%' || $3::text || '%')",
      limitParam: '$4',
    })
    expect(sql).toContain('tape_label ILIKE')
  })
})
