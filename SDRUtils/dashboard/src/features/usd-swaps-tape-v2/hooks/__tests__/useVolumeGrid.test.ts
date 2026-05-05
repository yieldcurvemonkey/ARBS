import { describe, expect, it } from '@jest/globals'
import { buildVolumeGridUrl } from '../useVolumeGrid'

describe('buildVolumeGridUrl', () => {
  it('builds URL with all required params', () => {
    const url = buildVolumeGridUrl({
      metric: 'notional', period: 'today',
      forwardSchema: 'default', tenorSchema: 'default', packageType: 'outright',
    })
    expect(url).toContain('/api/usd-swaps-tape-v2/volume-grid?')
    expect(url).toContain('metric=notional')
    expect(url).toContain('period=today')
    expect(url).toContain('forwardSchema=default')
    expect(url).toContain('tenorSchema=default')
    expect(url).toContain('packageType=outright')
  })

  it('appends lookbackDays when provided', () => {
    const url = buildVolumeGridUrl({
      metric: 'dv01', period: '1w', lookbackDays: 365,
      forwardSchema: 'imm16', tenorSchema: 'default', packageType: 'spreadover',
    })
    expect(url).toContain('lookbackDays=365')
    expect(url).toContain('forwardSchema=imm16')
    expect(url).toContain('packageType=spreadover')
  })

  it('omits lookbackDays when undefined', () => {
    const url = buildVolumeGridUrl({
      metric: 'notional', period: '1h',
      forwardSchema: 'default', tenorSchema: 'default', packageType: 'outright',
    })
    expect(url).not.toContain('lookbackDays')
  })
})
