import { describe, expect, it } from '@jest/globals'
import {
  classifyForwardBucket,
  classifyTenorBucket,
  FORWARD_BUCKETS,
  TENOR_BUCKETS,
  buildBucketSqlCases,
  buildBucketPredicate,
} from '../volumeGridBuckets'

describe('classifyForwardBucket', () => {
  it.each([
    [null, 'spot'],
    [0, 'spot'],
    [0.05, 'spot'],
    [0.083, '6m_1y'],
    [0.5, '6m_1y'],
    [0.999, '6m_1y'],
    [1.0, '1y_2y'],
    [1.5, '1y_2y'],
    [1.999, '1y_2y'],
    [2.0, '2y_5y'],
    [4.999, '2y_5y'],
    [5.0, '5y_10y'],
    [9.999, '5y_10y'],
    [10.0, 'fwd_other'],
    [50, 'fwd_other'],
  ])('forward_start_years=%s -> %s', (years, bucket) => {
    expect(classifyForwardBucket(years as number | null)).toBe(bucket)
  })
})

describe('classifyTenorBucket', () => {
  it.each([
    [null, null],
    [0.5, '1y'],
    [1.0, '1y'],
    [1.4999, '1y'],
    [1.5, '2y'],
    [2.4999, '2y'],
    [2.5, '2_5y'],
    [4.4999, '2_5y'],
    [4.5, '5y'],
    [5.4999, '5y'],
    [5.5, '5_10y'],
    [9.4999, '5_10y'],
    [9.5, '10y'],
    [10.9999, '10y'],
    [11.0, '10_20y'],
    [19.4999, '10_20y'],
    [19.5, '20y'],
    [20.9999, '20y'],
    [21.0, '20_30y'],
    [29.4999, '20_30y'],
    [29.5, '30y'],
    [30.9999, '30y'],
    [31.0, '50y'],
    [60, '50y'],
  ])('tenor_years=%s -> %s', (years, bucket) => {
    expect(classifyTenorBucket(years as number | null)).toBe(bucket)
  })
})

describe('FORWARD_BUCKETS / TENOR_BUCKETS', () => {
  it('forward buckets are exactly the five rendered rows', () => {
    expect(FORWARD_BUCKETS.map((b) => b.id)).toEqual([
      'spot', '6m_1y', '1y_2y', '2y_5y', '5y_10y',
    ])
  })
  it('tenor buckets are exactly the eleven rendered cols', () => {
    expect(TENOR_BUCKETS.map((b) => b.id)).toEqual([
      '1y', '2y', '2_5y', '5y', '5_10y', '10y',
      '10_20y', '20y', '20_30y', '30y', '50y',
    ])
  })
})

describe('buildBucketSqlCases', () => {
  it('emits forward + tenor CASE expressions referencing the leg alias', () => {
    const { fwdCase, tenorCase } = buildBucketSqlCases('l')
    expect(fwdCase).toContain('l.forward_start_years')
    expect(fwdCase).toContain("'spot'")
    expect(fwdCase).toContain("'5y_10y'")
    expect(fwdCase).toContain("'fwd_other'")
    expect(tenorCase).toContain('l.tenor_years')
    expect(tenorCase).toContain("'1y'")
    expect(tenorCase).toContain("'50y'")
  })
})

describe('buildBucketPredicate', () => {
  it('returns a parameterised WHERE clause with bind values', () => {
    const out = buildBucketPredicate('l', 'spot', '5y', 1)
    expect(out.sql).toMatch(/l\.forward_start_years IS NULL OR l\.forward_start_years < \$1/)
    expect(out.sql).toMatch(/l\.tenor_years >= \$2/)
    expect(out.sql).toMatch(/l\.tenor_years < \$3/)
    expect(out.params).toEqual([0.083, 4.5, 5.5])
  })
  it('handles 50y (no upper bound)', () => {
    const out = buildBucketPredicate('l', '5y_10y', '50y', 1)
    expect(out.sql).not.toMatch(/tenor_years <\s+\$/)
    expect(out.params).toEqual([5.0, 10.0, 31.0])
  })
  it('rejects unknown bucket ids', () => {
    expect(() => buildBucketPredicate('l', 'bogus', '5y', 1)).toThrow(/forward/)
    expect(() => buildBucketPredicate('l', 'spot', 'bogus', 1)).toThrow(/tenor/)
  })
})
