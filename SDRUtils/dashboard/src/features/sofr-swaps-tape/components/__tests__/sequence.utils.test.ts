import { describe, expect, it } from '@jest/globals'
import { buildSequenceClusters } from '../sequence.utils'
import type { SofrSwapTapeRow } from '../../types'

function row(
  packageId: string,
  executionStart: string,
  totalNotional: number,
  totalRisk: number,
  packageType = 'OUTRIGHT'
): SofrSwapTapeRow {
  return {
    package_id: packageId,
    package_type: packageType,
    as_of_date: executionStart.slice(0, 10),
    execution_start: executionStart,
    execution_end: executionStart,
    legs_count: 1,
    total_notional: totalNotional,
    total_risk: totalRisk,
    package_metrics: {},
    legs_json: []
  }
}

describe('sequence utils', () => {
  it('clusters rows by max gap and computes stats', () => {
    const rows: SofrSwapTapeRow[] = [
      row('A', '2026-02-05T14:00:00Z', 100_000_000, 20_000, 'OUTRIGHT'),
      row('B', '2026-02-05T14:01:00Z', 120_000_000, 25_000, 'CURVE'),
      row('C', '2026-02-05T14:10:00Z', 80_000_000, 15_000, 'OUTRIGHT')
    ]

    const clusters = buildSequenceClusters(rows, 90)
    expect(clusters).toHaveLength(2)
    expect(clusters[0].tradeCount).toBe(2)
    expect(clusters[0].grossNotional).toBe(220_000_000)
    expect(clusters[0].grossRisk).toBe(45_000)
    expect(clusters[0].packageMix.length).toBeGreaterThan(0)
  })

  it('returns empty clusters for empty input', () => {
    expect(buildSequenceClusters([], 60)).toEqual([])
  })
})
