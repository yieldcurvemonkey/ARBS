import { describe, expect, it } from '@jest/globals'
import { buildValidationItems, computeLinkMetrics } from '../manual-sofr-swap-links'

describe('manual-sofr-swap-links', () => {
  it('computes swaps link metrics from legs', () => {
    const metrics = computeLinkMetrics([
      {
        trade_id: 'T1',
        package_id: 'P1',
        notional: 100_000_000,
        risk: 25_000,
        fixed_rate: 0.041,
        execution_timestamp: '2026-02-05T14:00:00Z'
      },
      {
        trade_id: 'T2',
        package_id: 'P2',
        notional: -80_000_000,
        risk: -21_000,
        fixed_rate: 0.042,
        execution_timestamp: '2026-02-05T14:00:45Z'
      }
    ] as any)

    expect(metrics.trade_count).toBe(2)
    expect(metrics.total_notional).toBe(20_000_000)
    expect(metrics.gross_notional).toBe(180_000_000)
    expect(metrics.total_risk).toBe(4_000)
    expect(metrics.gross_risk).toBe(46_000)
    expect(metrics.avg_fixed_rate).toBeCloseTo(0.0415, 8)
    expect(metrics.time_spread_seconds).toBe(45)
  })

  it('flags validation errors on conflicts', () => {
    const legs = [
      { trade_id: 'T1', package_id: 'P1', execution_timestamp: '2026-02-05T14:00:00Z' },
      { trade_id: 'T2', package_id: 'P2', execution_timestamp: '2026-02-05T14:02:00Z' }
    ] as any
    const metrics = computeLinkMetrics(legs)
    const { hasErrors, items } = buildValidationItems(
      legs,
      metrics,
      [{ link_id: 'abc', manual_package_id: 'SML-20260205-AAAA1111', linked_trade_ids: ['T1'] }] as any
    )
    expect(hasErrors).toBe(true)
    expect(items.some((item) => item.key === 'conflicts' && item.status === 'error')).toBe(true)
  })
})
