import { describe, expect, it } from '@jest/globals'
import { buildVolumeGridCellUrl } from '../useVolumeGridCell'

describe('buildVolumeGridCellUrl', () => {
  it('returns null when cell is null', () => {
    expect(
      buildVolumeGridCellUrl({ cell: null, metric: 'notional', range: '3M' }),
    ).toBeNull()
  })

  it('builds URL with fwd, tenor, metric, range', () => {
    const url = buildVolumeGridCellUrl({
      cell: { fwd: 'spot', tenor: '5y' },
      metric: 'notional',
      range: '3M',
    })
    expect(url).toContain('/api/usd-swaps-tape-v2/volume-grid/cell?')
    expect(url).toContain('fwd=spot')
    expect(url).toContain('tenor=5y')
    expect(url).toContain('metric=notional')
    expect(url).toContain('range=3M')
  })

  it('appends recentLimit when provided', () => {
    const url = buildVolumeGridCellUrl({
      cell: { fwd: 'spot', tenor: '5y' },
      metric: 'dv01',
      range: '1Y',
      recentLimit: 100,
    })
    expect(url).toContain('recentLimit=100')
  })

  it('omits recentLimit when undefined', () => {
    const url = buildVolumeGridCellUrl({
      cell: { fwd: 'spot', tenor: '5y' },
      metric: 'notional',
      range: '3M',
    })
    expect(url).not.toContain('recentLimit')
  })
})
