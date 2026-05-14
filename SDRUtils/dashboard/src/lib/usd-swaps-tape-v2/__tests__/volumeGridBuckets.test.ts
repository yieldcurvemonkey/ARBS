import { describe, expect, it } from '@jest/globals'
import {
  buildBucketCaseSql,
  buildBucketPredicate,
  buildFomcBucketsFromLabels,
  buildPackageTypeFilter,
  buildPkgFamilySql,
  buildVenueBucketsFromIdentifiers,
  computeImmDates,
  PACKAGE_TYPE_GROUPS,
  parseFomcLabel,
  resolveForwardSchema,
  resolveTenorSchema,
  thirdWednesdayUtc,
} from '../volumeGridBuckets'

describe('resolveForwardSchema', () => {
  it('default schema matches user-spec 8 buckets', () => {
    const out = resolveForwardSchema('default')
    expect(out.buckets.map((b) => b.id)).toEqual([
      'spot', '1w_3m', '3m_6m', '6m_1y', '1y_2y', '2y_5y', '5y_10y', '10y_plus',
    ])
    expect(out.buckets[0].label).toBe('Spot')
    expect(out.buckets[7].label).toBe('10Y+')
  })
  it('legacy schema preserves the original 5 forward buckets', () => {
    const out = resolveForwardSchema('legacy')
    expect(out.buckets.map((b) => b.id)).toEqual([
      'spot', '6m_1y', '1y_2y', '2y_5y', '5y_10y',
    ])
  })
  it('imm16 schema returns 16 dynamic IMM buckets', () => {
    const now = new Date('2026-05-05T00:00:00Z')
    const out = resolveForwardSchema('imm16', now)
    expect(out.buckets.length).toBe(16)
    // First IMM after 2026-05-05 is 2026-06-17 (third Wed of Jun 2026).
    expect(out.buckets[0].label).toMatch(/Jun26/)
    expect(out.buckets[15].label).toMatch(/Mar30/)
    expect(out.kind).toBe('years')
  })
  it('fomc schema is fomc_label kind with empty bucket list (resolved post-query)', () => {
    const out = resolveForwardSchema('fomc')
    expect(out.kind).toBe('fomc_label')
    expect(out.buckets.length).toBe(0)
    // Filter relaxed to label-only (drop the often-unset is_fomc_dated flag)
    expect(out.extraFilterSql).toMatch(/fomc_meeting_label\s+IS\s+NOT\s+NULL/)
    expect(out.extraFilterSql).not.toMatch(/is_fomc_dated/)
  })
})

describe('resolveTenorSchema venue', () => {
  it('returns venue schema with empty bucket list and venue kind', () => {
    const out = resolveTenorSchema('venue')
    expect(out.kind).toBe('venue')
    expect(out.buckets.length).toBe(0)
    expect(out.extraFilterSql).toMatch(/platform_identifier\s+IS\s+NOT\s+NULL/)
  })
})

describe('buildVenueBucketsFromIdentifiers', () => {
  it('orders IDB MICs first, CUSTY MICs second, alpha-sorts unknowns last', () => {
    const out = buildVenueBucketsFromIdentifiers([
      'BBSF', 'BGCD', 'TSEF', 'NEW1', 'AAAA', 'TWSF',
    ])
    expect(out.map((b) => b.id)).toEqual(['BGCD', 'TSEF', 'BBSF', 'TWSF', 'AAAA', 'NEW1'])
  })
  it('drops empty / null entries', () => {
    const out = buildVenueBucketsFromIdentifiers(['BBSF', '', 'BGCD'])
    expect(out.map((b) => b.id)).toEqual(['BGCD', 'BBSF'])
  })
})

describe('parseFomcLabel', () => {
  it('parses APR26 to a 2026-04 date', () => {
    const out = parseFomcLabel('APR26')
    expect(out).not.toBeNull()
    if (out) {
      expect(out.getUTCFullYear()).toBe(2026)
      expect(out.getUTCMonth()).toBe(3)
    }
  })
  it('returns null on garbage input', () => {
    expect(parseFomcLabel('FOO')).toBeNull()
    expect(parseFomcLabel('apr26')).toBeNull()
  })
})

describe('buildFomcBucketsFromLabels', () => {
  const now = new Date('2026-05-05T00:00:00Z')

  it('sorts upcoming labels chronologically and drops unparseable ones', () => {
    const out = buildFomcBucketsFromLabels(
      ['DEC26', 'JAN27', 'APR26', 'GARBAGE', 'JUN26'],
      { now, windowStart: new Date('2026-04-01T00:00:00Z') },
    )
    expect(out.map((b) => b.id)).toEqual(['APR26', 'JUN26', 'DEC26', 'JAN27'])
  })

  it('drops historical labels older than the window start', () => {
    const out = buildFomcBucketsFromLabels(
      ['JAN21', 'APR21', 'MAR26', 'APR26', 'JUN26'],
      { now },
    )
    // Default windowStart = now - 30d (≈ 2026-04-05). MAR26 falls before.
    expect(out.map((b) => b.id)).toEqual(['APR26', 'JUN26'])
  })

  it('caps the bucket count via limit', () => {
    const labels = ['JUN26', 'JUL26', 'SEP26', 'NOV26', 'DEC26', 'JAN27', 'MAR27']
    const out = buildFomcBucketsFromLabels(labels, { now, limit: 3 })
    expect(out.length).toBe(3)
    expect(out.map((b) => b.id)).toEqual(['JUN26', 'JUL26', 'SEP26'])
  })
})

describe('resolveTenorSchema', () => {
  it('default schema matches user-spec 16 tenor buckets', () => {
    const out = resolveTenorSchema('default')
    expect(out.buckets.map((b) => b.label)).toEqual([
      '1M-3M', '6M-12M', '1Y-18M', '18M-2Y', '2Y', '3Y', '4Y', '5Y',
      '6Y-7Y', '8Y-9Y', '10Y', '10Y-12Y', '12Y-15Y', '15Y-20Y', '20Y-25Y', '30Y+',
    ])
  })
})

describe('thirdWednesdayUtc', () => {
  it('returns the third Wednesday of June 2026 (2026-06-17)', () => {
    const out = thirdWednesdayUtc(2026, 5)
    expect(out.toISOString().slice(0, 10)).toBe('2026-06-17')
  })
  it('returns the third Wednesday of December 2026 (2026-12-16)', () => {
    const out = thirdWednesdayUtc(2026, 11)
    expect(out.toISOString().slice(0, 10)).toBe('2026-12-16')
  })
})

describe('computeImmDates', () => {
  it('produces 16 quarterly IMM dates strictly increasing', () => {
    const now = new Date('2026-05-05T00:00:00Z')
    const out = computeImmDates(now, 16)
    expect(out.length).toBe(16)
    for (let i = 1; i < out.length; i += 1) {
      expect(out[i].getTime()).toBeGreaterThan(out[i - 1].getTime())
    }
    for (const d of out) {
      expect(d.getUTCDay()).toBe(3) // Wednesday
      expect([2, 5, 8, 11]).toContain(d.getUTCMonth()) // Mar/Jun/Sep/Dec
    }
  })
})

describe('buildBucketCaseSql', () => {
  it('emits CASE with all bucket ids for the default forward schema', () => {
    const schema = resolveForwardSchema('default')
    const sql = buildBucketCaseSql('l', 'forward_start_years', schema.buckets)
    expect(sql).toContain('CASE')
    for (const b of schema.buckets) {
      expect(sql).toContain(`'${b.id}'`)
    }
    expect(sql).toContain("ELSE 'other'")
  })
  it('routes NULL forward_start_years to the spot bucket', () => {
    const schema = resolveForwardSchema('default')
    const sql = buildBucketCaseSql('l', 'forward_start_years', schema.buckets)
    expect(sql).toMatch(/IS NULL THEN 'spot'/)
  })
})

describe('buildBucketPredicate', () => {
  const fwd = resolveForwardSchema('default')
  const tenor = resolveTenorSchema('default')

  it('filters spot x 5Y on the right boundaries', () => {
    const out = buildBucketPredicate('l', fwd, tenor, 'spot', '5y', 1)
    expect(out.sql).toMatch(/forward_start_years IS NULL OR l\.forward_start_years < \$1/)
    expect(out.sql).toMatch(/tenor_years >= \$2/)
    expect(out.sql).toMatch(/tenor_years < \$3/)
    expect(out.params).toEqual([0.0192, 4.5, 5.5])
  })

  it('handles 10Y+ (no upper forward bound)', () => {
    const out = buildBucketPredicate('l', fwd, tenor, '10y_plus', '10y', 1)
    expect(out.sql).not.toMatch(/forward_start_years <\s+\$/)
    expect(out.params).toEqual([10.0, 9.5, 10.5])
  })

  it('handles 30Y+ (no upper tenor bound)', () => {
    const out = buildBucketPredicate('l', fwd, tenor, '5y_10y', '30y_plus', 1)
    expect(out.sql).not.toMatch(/tenor_years <\s+\$/)
    expect(out.params).toEqual([5.0, 10.0, 25.5])
  })

  it('rejects unknown bucket ids', () => {
    expect(() => buildBucketPredicate('l', fwd, tenor, 'bogus', '5y', 1)).toThrow(/forward bucket/)
    expect(() => buildBucketPredicate('l', fwd, tenor, 'spot', 'bogus', 1)).toThrow(/tenor bucket/)
  })

  it('uses fomc_meeting_label equality for fomc schema', () => {
    const fomcSchema = resolveForwardSchema('fomc')
    const out = buildBucketPredicate('l', fomcSchema, tenor, 'APR26', '5y', 2)
    expect(out.sql).toMatch(/l\.fomc_meeting_label = \$2/)
    expect(out.params).toEqual(['APR26', 4.5, 5.5])
  })

  it('rejects malformed FOMC labels', () => {
    const fomcSchema = resolveForwardSchema('fomc')
    expect(() => buildBucketPredicate('l', fomcSchema, tenor, 'foo', '5y', 1)).toThrow(/FOMC/)
  })

  it('uses platform_identifier equality for venue tenor schema', () => {
    const venueSchema = resolveTenorSchema('venue')
    const out = buildBucketPredicate('l', fwd, venueSchema, 'spot', 'BBSF', 1)
    expect(out.sql).toMatch(/l\.platform_identifier = \$\d+/)
    expect(out.params).toContain('BBSF')
  })
})

describe('PACKAGE_TYPE_GROUPS', () => {
  it('maps spreadover to SPREADOVER + MATCHED_MATURITY', () => {
    expect(PACKAGE_TYPE_GROUPS.spreadover).toEqual(['SPREADOVER', 'MATCHED_MATURITY'])
  })
  it('maps spreadover_curve to SPREADOVER_CURVE + MATCHED_MATURITY_CURVE', () => {
    expect(PACKAGE_TYPE_GROUPS.spreadover_curve).toEqual([
      'SPREADOVER_CURVE', 'MATCHED_MATURITY_CURVE',
    ])
  })
  it('maps spreadover_fly to SPREADOVER_FLY + MATCHED_MATURITY_FLY', () => {
    expect(PACKAGE_TYPE_GROUPS.spreadover_fly).toEqual([
      'SPREADOVER_FLY', 'MATCHED_MATURITY_FLY',
    ])
  })
  it('all returns empty (no filter)', () => {
    expect(PACKAGE_TYPE_GROUPS.all).toEqual([])
  })
})

describe('buildPackageTypeFilter', () => {
  it('builds an IN-list with the right placeholders for spreadover', () => {
    const out = buildPackageTypeFilter('spreadover', 'p', 6)
    expect(out.sql).toMatch(/p\.package_type IN \(\$6, \$7\)/)
    expect(out.params).toEqual(['SPREADOVER', 'MATCHED_MATURITY'])
  })

  it('returns the always-true sentinel for the all group', () => {
    const out = buildPackageTypeFilter('all', 'p', 6)
    expect(out.sql).toBe('TRUE')
    expect(out.params).toEqual([])
  })

  it('builds a single-value IN-list for outright', () => {
    const out = buildPackageTypeFilter('outright', 'p', 4)
    expect(out.sql).toBe('p.package_type IN ($4)')
    expect(out.params).toEqual(['OUTRIGHT'])
  })
})

describe('buildPackageTypeFilter regression', () => {
  it('returns TRUE with no params for the all group', () => {
    const result = buildPackageTypeFilter('all', 'p', 1)
    expect(result.sql).toBe('TRUE')
    expect(result.params).toEqual([])
  })
})

describe('buildPkgFamilySql', () => {
  it('returns a CASE expression using the given alias', () => {
    const sql = buildPkgFamilySql('p')
    expect(sql).toContain("p.package_type IN ('OUTRIGHT','SPREADOVER','MATCHED_MATURITY')")
    expect(sql).toContain("THEN 'outright'")
    expect(sql).toContain("THEN 'curve'")
    expect(sql).toContain("THEN 'fly'")
    expect(sql).toContain("ELSE 'other'")
  })

  it('uses the provided alias for column references', () => {
    const sql = buildPkgFamilySql('pkg')
    expect(sql).toContain('pkg.package_type')
    expect(sql).not.toContain('p.package_type')
  })
})
