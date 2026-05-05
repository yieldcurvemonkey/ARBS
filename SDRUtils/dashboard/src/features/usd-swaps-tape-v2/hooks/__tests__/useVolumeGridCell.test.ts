import { describe, expect, it } from '@jest/globals'
import { buildVolumeGridCellUrl } from '../useVolumeGridCell'

describe('buildVolumeGridCellUrl', () => {
  it('returns null when cell is null', () => {
    expect(
      buildVolumeGridCellUrl({
        cell: null, metric: 'notional', range: '3M',
        forwardSchema: 'default', tenorSchema: 'default', packageType: 'outright',
      }),
    ).toBeNull()
  })

  it('builds URL with all required params', () => {
    const url = buildVolumeGridCellUrl({
      cell: { fwd: 'spot', tenor: '5y' },
      metric: 'notional', range: '3M',
      forwardSchema: 'default', tenorSchema: 'default', packageType: 'outright',
    })
    expect(url).toContain('/api/usd-swaps-tape-v2/volume-grid/cell?')
    expect(url).toContain('fwd=spot')
    expect(url).toContain('tenor=5y')
    expect(url).toContain('metric=notional')
    expect(url).toContain('range=3M')
    expect(url).toContain('forwardSchema=default')
    expect(url).toContain('tenorSchema=default')
    expect(url).toContain('packageType=outright')
  })

  it('threads through schema + packageType selections', () => {
    const url = buildVolumeGridCellUrl({
      cell: { fwd: 'imm_1', tenor: '2y' },
      metric: 'dv01', range: '1Y',
      forwardSchema: 'imm16', tenorSchema: 'default', packageType: 'spreadover_curve',
    })
    expect(url).toContain('forwardSchema=imm16')
    expect(url).toContain('packageType=spreadover_curve')
  })
})
