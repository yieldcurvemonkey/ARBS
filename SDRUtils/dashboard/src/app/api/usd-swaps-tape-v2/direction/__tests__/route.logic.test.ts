// ABOUTME: The cross-bucket-level refusal, asserted rather than commented.
//
// Every test here exists because the forbidden view is the NATURAL one. A
// reader wants "dealers are longer 5y than 10y" and the data will happily
// produce a number for it; the number is wrong by a factor that runs to 1.54x
// and nothing on a rendered chart would say so.
import { describe, expect, it } from '@jest/globals'
import {
  assertNoLevelKeys,
  BadRequest,
  bucketSql,
  BUCKET_COLUMNS,
  coverageSql,
  levelColumn,
  parseBucket,
  parseCommon,
  SAMPLE_FLOOR,
  slug,
  STANDARDISED_COLUMNS,
  standardisedSql,
  suffixLevels,
  summarySql,
  TENOR_BUCKETS,
} from '../route.logic'

const sp = (q: string) => new URLSearchParams(q)

describe('the level endpoint serves exactly one bucket', () => {
  it('accepts a single known bucket', () => {
    expect(parseBucket(sp('bucket=5-7Y'))).toBe('5-7Y')
    for (const b of TENOR_BUCKETS) {
      expect(parseBucket(sp(`bucket=${encodeURIComponent(b)}`))).toBe(b)
    }
  })

  it('refuses a repeated bucket param', () => {
    expect(() => parseBucket(sp('bucket=5-7Y&bucket=7-10Y'))).toThrow(BadRequest)
  })

  it('refuses a comma list', () => {
    expect(() => parseBucket(sp('bucket=5-7Y,7-10Y'))).toThrow(BadRequest)
  })

  it('refuses no bucket at all rather than defaulting to every bucket', () => {
    // Defaulting would be the friendly thing and it would ship the forbidden
    // view by accident.
    expect(() => parseBucket(sp(''))).toThrow(BadRequest)
  })

  it('refuses an unknown bucket', () => {
    expect(() => parseBucket(sp('bucket=6Y'))).toThrow(BadRequest)
  })
})

describe('the all-bucket endpoint carries no level', () => {
  it('selects no level column', () => {
    const sql = standardisedSql()
    expect(sql).not.toMatch(/delta_dv01/)
    expect(sql).not.toMatch(/abs_dv01/)
  })

  it('has no level in its published column list', () => {
    for (const c of STANDARDISED_COLUMNS) {
      expect(c).not.toMatch(/^(delta_dv01|abs_dv01)/)
    }
  })

  it('throws if a level key ever reaches the payload', () => {
    // The list above could be edited; this is the check that survives that.
    expect(() =>
      assertNoLevelKeys([{ bucket_key: '5-7Y', z_raw: 1 }]),
    ).not.toThrow()
    expect(() =>
      assertNoLevelKeys([{ bucket_key: '5-7Y', delta_dv01: 1_000_000 }]),
    ).toThrow(/not comparable across buckets/)
    expect(() =>
      assertNoLevelKeys([{ bucket_key: '5-7Y', abs_dv01: 1 }]),
    ).toThrow(/not comparable across buckets/)
    expect(() =>
      assertNoLevelKeys([{ bucket_key: '5-7Y', delta_dv01_cov_adj: 1 }]),
    ).toThrow(/not comparable across buckets/)
  })

  it('does serve z, which is what makes the endpoint useful', () => {
    expect(STANDARDISED_COLUMNS).toContain('z_raw')
    expect(STANDARDISED_COLUMNS).toContain('z_cov_adj')
    expect(STANDARDISED_COLUMNS).toContain('coverage_frac')
  })
})

describe('the level keys are bucket-suffixed on the wire', () => {
  it('matches indicator._slug exactly', () => {
    expect(slug('5-7Y')).toBe('5_7Y')
    expect(slug('30Y+')).toBe('30Yplus')
    expect(slug('10-15Y')).toBe('10_15Y')
    expect(slug('0-1Y')).toBe('0_1Y')
  })

  it('matches indicator.level_column exactly', () => {
    expect(levelColumn('5-7Y')).toBe('delta_dv01__5_7Y')
    expect(levelColumn('30Y+')).toBe('delta_dv01__30Yplus')
    expect(levelColumn('5-7Y', 'cov_adj')).toBe('delta_dv01_cov_adj__5_7Y')
    expect(levelColumn('5-7Y', 'gross')).toBe('abs_dv01__5_7Y')
  })

  it('renames only the level keys, and two buckets do not align', () => {
    const a = suffixLevels([{ visibility_date: 'd', delta_dv01: 1, z_raw: 2 }], '5-7Y')
    const b = suffixLevels([{ visibility_date: 'd', delta_dv01: 3, z_raw: 4 }], '7-10Y')
    expect(a[0]).toHaveProperty('delta_dv01__5_7Y', 1)
    expect(b[0]).toHaveProperty('delta_dv01__7_10Y', 3)
    // z DOES align — that is the point.
    expect(a[0]).toHaveProperty('z_raw', 2)
    expect(b[0]).toHaveProperty('z_raw', 4)
    // and the level does NOT.
    const merged = { ...a[0], ...b[0] }
    expect(Object.keys(merged).filter((k) => k.startsWith('delta_dv01')).length).toBe(2)
    expect(merged).not.toHaveProperty('delta_dv01')
  })
})

describe('venue classes and series are never merged', () => {
  it('defaults to D2C / FLOW', () => {
    const p = parseCommon(sp(''))
    expect(p.venueClass).toBe('D2C')
    expect(p.series).toBe('FLOW')
  })

  it('accepts each venue class by its exact name', () => {
    expect(parseCommon(sp('venueClass=D2D')).venueClass).toBe('D2D')
    expect(parseCommon(sp('venueClass=VENUE_UNKNOWN')).venueClass).toBe('VENUE_UNKNOWN')
  })

  it('refuses UNKNOWN, which is not the constant', () => {
    // types.VENUE_UNKNOWN is the string "VENUE_UNKNOWN"; accepting "UNKNOWN"
    // would silently serve an empty series that looks like no flow.
    expect(() => parseCommon(sp('venueClass=UNKNOWN'))).toThrow(BadRequest)
  })

  it('refuses an aggregate venue class', () => {
    expect(() => parseCommon(sp('venueClass=ALL'))).toThrow(BadRequest)
  })

  it('refuses an unknown series', () => {
    expect(() => parseCommon(sp('series=BOTH'))).toThrow(BadRequest)
  })
})

describe('the sample floor', () => {
  it('defaults from to the floor', () => {
    expect(parseCommon(sp('')).from).toBe(SAMPLE_FLOOR)
  })

  it('refuses a window that starts before it', () => {
    expect(() => parseCommon(sp('from=2024-01-01'))).toThrow(BadRequest)
  })

  it('refuses a malformed date rather than passing it to Postgres', () => {
    expect(() => parseCommon(sp('from=last-tuesday'))).toThrow(BadRequest)
    expect(() => parseCommon(sp('to=2024/07/01'))).toThrow(BadRequest)
  })
})

describe('the SQL is parameterised and reads the right tables', () => {
  it('bucketSql binds every filter', () => {
    const sql = bucketSql()
    expect(sql).toMatch(/arbs_dd_ladder_v1/)
    for (const n of [1, 2, 3, 4, 5, 6]) expect(sql).toContain(`$${n}`)
    for (const c of BUCKET_COLUMNS) expect(sql).toContain(c)
  })

  it('standardisedSql binds every filter', () => {
    const sql = standardisedSql()
    expect(sql).toMatch(/arbs_dd_ladder_v1/)
    for (const n of [1, 2, 3, 4, 5]) expect(sql).toContain(`$${n}`)
  })

  it('coverageSql reads the coverage table and reports the share', () => {
    const sql = coverageSql(true)
    expect(sql).toMatch(/arbs_dd_coverage_v1/)
    expect(sql).toMatch(/dv01_share/)
    expect(sql).toMatch(/PARTITION BY bucket_key/)
    expect(coverageSql(false)).not.toMatch(/PARTITION BY bucket_key/)
  })

  it('summarySql takes coverage from the COVERAGE table, not the ladder', () => {
    // A ladder cell only exists where at least one unit was oriented, so
    // averaging coverage over ladder cells conditions on the thing being
    // measured. Measured on one window: 67.0% that way against 44.8% over
    // the complete partition -- a 22-point overstatement on the one number
    // whose job is to stop the panel reading as complete.
    const sql = summarySql()
    expect(sql).toMatch(/arbs_dd_coverage_v1/)
    expect(sql).toMatch(/FILTER \(WHERE reason = 'IN_LADDER'\)/)
    // and NOT from the ladder's per-cell copies
    expect(sql).not.toMatch(/SUM\(coverage_dv01_kept\)/)
    expect(sql).not.toMatch(/SUM\(coverage_dv01_total\)/)
  })
})
