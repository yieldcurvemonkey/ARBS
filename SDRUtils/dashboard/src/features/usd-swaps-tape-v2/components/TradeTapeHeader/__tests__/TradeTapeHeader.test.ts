import { describe, expect, it } from '@jest/globals'
import { summarize } from '../TradeTapeHeader.helpers'

const row = (overrides: Record<string, any>): any => ({
  package_id: overrides.package_id ?? 'P1',
  package_type: 'OUTRIGHT',
  legs_count: overrides.legs_count ?? 1,
  execution_start: '2026-04-14T14:30:00Z',
  execution_end: '2026-04-14T14:30:00Z',
  package_metrics: {},
  legs_json: [],
  lifecycle_mix: {},
  ...overrides,
})

describe('summarize', () => {
  it('returns zeroes for an empty tape', () => {
    const s = summarize([])
    expect(s.tradeCount).toBe(0)
    expect(s.grossDv01).toBe(0)
    expect(s.grossNotional).toBe(0)
    expect(s.packageCount).toBe(0)
    expect(s.clusterCount).toBe(0)
  })

  it('sums gross risk / notional using absolute values', () => {
    const s = summarize([
      row({ gross_risk: 10_000, gross_notional: 100_000_000 }),
      row({ package_id: 'P2', gross_risk: -5_000, gross_notional: -40_000_000 }),
    ])
    expect(s.grossDv01).toBe(15_000)
    expect(s.grossNotional).toBe(140_000_000)
    expect(s.packageCount).toBe(2)
  })

  it('counts unique clusters', () => {
    const s = summarize([
      row({ cluster_id: 'C1' }),
      row({ package_id: 'P2', cluster_id: 'C1' }),
      row({ package_id: 'P3', cluster_id: 'C2' }),
    ])
    expect(s.clusterCount).toBe(2)
  })

  it('tallies lifecycle_mix counts across rows', () => {
    const s = summarize([
      row({ lifecycle_mix: { NEW_RISK: 2, UNWIND: 1 } }),
      row({ package_id: 'P2', lifecycle_mix: { NEW_RISK: 3 } }),
    ])
    expect(s.lifecycleCounts.NEW_RISK).toBe(5)
    expect(s.lifecycleCounts.UNWIND).toBe(1)
  })

  it('propagates legs_count to trade count and new-risk count', () => {
    const s = summarize([
      row({ legs_count: 2, is_new_risk: true }),
      row({ package_id: 'P2', legs_count: 3, is_new_risk: false }),
    ])
    expect(s.tradeCount).toBe(5)
    expect(s.newRisk).toBe(2)
  })
})
