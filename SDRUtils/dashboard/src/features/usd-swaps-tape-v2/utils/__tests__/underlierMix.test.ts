import { describe, expect, it } from '@jest/globals'
import {
  computeUnderlierMix,
  type UnderlierMixMetric,
  filterRowsToWindow,
} from '../underlierMix'
import type { UsdSwapTapeRow } from '../../types'

const row = (
  partial: Partial<UsdSwapTapeRow> & {
    canonical_underlier_key?: string | null
    legs?: Array<{ risk?: number | null; canonical_underlier_key?: string | null }>
  } = {},
): UsdSwapTapeRow => {
  const legs = partial.legs ?? []
  return {
    package_id: partial.package_id ?? `P-${Math.random()}`,
    package_type: partial.package_type ?? 'OUTRIGHT',
    legs_count: legs.length,
    canonical_underlier_key: partial.canonical_underlier_key ?? null,
    total_risk: partial.total_risk ?? null,
    total_notional: partial.total_notional ?? null,
    legs_json: legs.map((l) => ({
      risk: l.risk ?? null,
      canonical_underlier_key: l.canonical_underlier_key ?? null,
    })) as any,
    execution_start: partial.execution_start ?? '2026-05-04T15:00:00Z',
  } as any
}

describe('computeUnderlierMix', () => {
  const rows: UsdSwapTapeRow[] = [
    row({
      package_id: 'A',
      canonical_underlier_key: 'USD/SOFR-OIS/COMPOUND',
      total_risk: 10_000,
      total_notional: 100_000_000,
      legs: [{ risk: 10_000, canonical_underlier_key: 'USD/SOFR-OIS/COMPOUND' }],
    }),
    row({
      package_id: 'B',
      canonical_underlier_key: 'USD/SOFR-OIS/COMPOUND',
      total_risk: 5_000,
      total_notional: 50_000_000,
      legs: [{ risk: 5_000, canonical_underlier_key: 'USD/SOFR-OIS/COMPOUND' }],
    }),
    row({
      package_id: 'C',
      canonical_underlier_key: 'USD/FED-FUNDS-OIS/COMPOUND',
      total_risk: 7_500,
      total_notional: 75_000_000,
      legs: [{ risk: 7_500, canonical_underlier_key: 'USD/FED-FUNDS-OIS/COMPOUND' }],
    }),
  ]

  const metrics: UnderlierMixMetric[] = ['count', 'risk', 'notional', 'pa_dv01']

  it.each(metrics)('returns one bucket per distinct canonical key for %s', (metric) => {
    const out = computeUnderlierMix(rows, metric)
    const keys = out.map((r) => r.key).sort()
    expect(keys).toEqual([
      'USD/FED-FUNDS-OIS/COMPOUND',
      'USD/SOFR-OIS/COMPOUND',
    ])
  })

  it('aggregates trade count correctly', () => {
    const out = computeUnderlierMix(rows, 'count')
    const sofr = out.find((r) => r.key === 'USD/SOFR-OIS/COMPOUND')
    const ff = out.find((r) => r.key === 'USD/FED-FUNDS-OIS/COMPOUND')
    expect(sofr?.value).toBe(2)
    expect(ff?.value).toBe(1)
  })

  it('aggregates Σ|risk| correctly', () => {
    const out = computeUnderlierMix(rows, 'risk')
    const sofr = out.find((r) => r.key === 'USD/SOFR-OIS/COMPOUND')
    expect(sofr?.value).toBe(15_000)
  })

  it('aggregates notional correctly', () => {
    const out = computeUnderlierMix(rows, 'notional')
    const sofr = out.find((r) => r.key === 'USD/SOFR-OIS/COMPOUND')
    expect(sofr?.value).toBe(150_000_000)
  })

  it('reports each bucket as a share of the total', () => {
    const out = computeUnderlierMix(rows, 'risk')
    const totalShare = out.reduce((a, b) => a + b.share, 0)
    expect(totalShare).toBeCloseTo(1, 6)
  })

  it('sorts buckets by descending value', () => {
    const out = computeUnderlierMix(rows, 'risk')
    expect(out[0].key).toBe('USD/SOFR-OIS/COMPOUND')
    expect(out[1].key).toBe('USD/FED-FUNDS-OIS/COMPOUND')
  })

  it('handles empty input cleanly', () => {
    expect(computeUnderlierMix([], 'count')).toEqual([])
  })

  it('falls back to first leg canonical key when row-level is null', () => {
    const out = computeUnderlierMix(
      [
        row({
          canonical_underlier_key: null,
          total_risk: 4_000,
          legs: [{ risk: 4_000, canonical_underlier_key: 'USD/OBFR-OIS/COMPOUND' }],
        }),
      ],
      'risk',
    )
    expect(out[0].key).toBe('USD/OBFR-OIS/COMPOUND')
  })
})

describe('filterRowsToWindow', () => {
  const now = new Date('2026-05-04T20:00:00Z').getTime()
  const rows: UsdSwapTapeRow[] = [
    row({ package_id: 'today', execution_start: '2026-05-04T15:00:00Z' }),
    row({ package_id: '5d', execution_start: '2026-04-29T15:00:00Z' }),
    row({ package_id: '15d', execution_start: '2026-04-19T15:00:00Z' }),
    row({ package_id: '45d', execution_start: '2026-03-20T15:00:00Z' }),
    row({ package_id: '120d', execution_start: '2026-01-04T15:00:00Z' }),
  ]

  it.each([
    ['today', 1],
    ['7d', 2],
    ['30d', 3],
    ['90d', 4],
  ] as const)('returns the right rows for window=%s', (window, expected) => {
    expect(filterRowsToWindow(rows, window, now)).toHaveLength(expected)
  })

  it('returns all rows for YTD when called in May', () => {
    expect(filterRowsToWindow(rows, 'YTD', now)).toHaveLength(5)
  })
})
