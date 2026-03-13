import { describe, expect, it } from '@jest/globals'

import {
  parseSnapshotRouteParams,
  parseTimeseriesRouteParams,
} from '../route-logic'

describe('listed-option-oi-volume route logic', () => {
  it('rejects invalid snapshot params and parses valid ones', () => {
    const invalid = parseSnapshotRouteParams(
      new URLSearchParams('field=theta&periodBusinessDays=0')
    )
    expect(invalid.ok).toBe(false)

    const valid = parseSnapshotRouteParams(
      new URLSearchParams(
        'field=volume_change&periodBusinessDays=5&contractView=constant_maturity&rowAxis=delta&labelNamespace=Barchart&productFamily=STIR&productRoots=SFR,0Q'
      )
    )
    expect(valid.ok).toBe(true)
    if (!valid.ok) return

    expect(valid.value).toEqual({
      requestedDate: undefined,
      field: 'volume_change',
      periodBusinessDays: 5,
      labelNamespace: 'Barchart',
      contractView: 'constant_maturity',
      rowAxis: 'delta',
      productFamily: 'STIR',
      productRoots: ['SFR', '0Q'],
    })
  })

  it('validates timeseries body windows and defaults', () => {
    const invalid = parseTimeseriesRouteParams({
      range: '1M',
      startDate: '2026-03-10',
      endDate: '2026-03-01',
      series: [],
    })
    expect(invalid.ok).toBe(false)

    const valid = parseTimeseriesRouteParams({
      range: '6M',
      periodBusinessDays: 2,
      series: [
        {
          metricField: 'open_interest',
          productRoot: 'TY',
          contractReferenceMode: 'explicit',
          selectorType: 'explicit_symbol',
          side: 'C',
          rawSymbolFallback: 'TYM26|1115C',
        },
      ],
    })
    expect(valid.ok).toBe(true)
    if (!valid.ok) return

    expect(valid.value.periodBusinessDays).toBe(2)
    expect(valid.value.range).toBe('6M')
    expect(valid.value.series).toHaveLength(1)
  })
})
