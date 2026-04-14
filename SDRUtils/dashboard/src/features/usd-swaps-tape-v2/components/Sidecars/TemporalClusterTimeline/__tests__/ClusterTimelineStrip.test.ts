import { describe, expect, it } from '@jest/globals'
import { clusterGeometry } from '../ClusterTimelineStrip.helpers'

const cluster = (overrides: Record<string, any>): any => ({
  cluster_id: 'C1',
  start_ts: '2026-04-14T09:00:00Z',
  end_ts: '2026-04-14T09:02:00Z',
  trade_count: 10,
  total_risk: 0,
  gross_notional: 0,
  tape_labels: [],
  lifecycle_types: ['NEW_RISK'],
  ...overrides,
})

describe('clusterGeometry', () => {
  it('emits one bar per cluster', () => {
    const bars = clusterGeometry(
      [cluster({}), cluster({ cluster_id: 'C2' })],
      {
        width: 1000,
        startTs: Date.parse('2026-04-14T09:00:00Z'),
        endTs: Date.parse('2026-04-14T10:00:00Z'),
      },
    )
    expect(bars).toHaveLength(2)
    expect(bars[0].cluster_id).toBe('C1')
  })

  it('scales x + width linearly across the time span', () => {
    const bars = clusterGeometry(
      [
        cluster({
          start_ts: '2026-04-14T09:00:00Z',
          end_ts: '2026-04-14T09:30:00Z',
        }),
      ],
      {
        width: 1000,
        startTs: Date.parse('2026-04-14T09:00:00Z'),
        endTs: Date.parse('2026-04-14T10:00:00Z'),
      },
    )
    expect(bars[0].x).toBe(0)
    expect(bars[0].width).toBeCloseTo(500, 0)
  })

  it('uses log scaling for height by trade_count', () => {
    const bars = clusterGeometry(
      [cluster({ trade_count: 1 }), cluster({ cluster_id: 'C2', trade_count: 100 })],
      {
        width: 1000,
        startTs: Date.parse('2026-04-14T09:00:00Z'),
        endTs: Date.parse('2026-04-14T10:00:00Z'),
      },
    )
    expect(bars[1].heightPct).toBeGreaterThan(bars[0].heightPct)
  })

  it('propagates dominant lifecycle from the first entry of lifecycle_types', () => {
    const bars = clusterGeometry(
      [cluster({ lifecycle_types: ['UNWIND', 'NEW_RISK'] })],
      {
        width: 1000,
        startTs: Date.parse('2026-04-14T09:00:00Z'),
        endTs: Date.parse('2026-04-14T10:00:00Z'),
      },
    )
    expect(bars[0].dominantLifecycle).toBe('UNWIND')
  })
})
