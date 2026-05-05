import { describe, expect, it } from '@jest/globals'
import { buildVolumeGridUrl } from '../useVolumeGrid'

describe('buildVolumeGridUrl', () => {
  it('builds URL with metric and period', () => {
    const url = buildVolumeGridUrl({ metric: 'notional', period: 'today' })
    expect(url).toContain('/api/usd-swaps-tape-v2/volume-grid?')
    expect(url).toContain('metric=notional')
    expect(url).toContain('period=today')
  })

  it('appends lookbackDays when provided', () => {
    const url = buildVolumeGridUrl({ metric: 'dv01', period: '1w', lookbackDays: 365 })
    expect(url).toContain('metric=dv01')
    expect(url).toContain('period=1w')
    expect(url).toContain('lookbackDays=365')
  })

  it('omits lookbackDays when undefined', () => {
    const url = buildVolumeGridUrl({ metric: 'notional', period: '1h' })
    expect(url).not.toContain('lookbackDays')
  })
})
