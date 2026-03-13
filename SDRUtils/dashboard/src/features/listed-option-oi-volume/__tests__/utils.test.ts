import { describe, expect, it } from '@jest/globals'

import type { ListedOptionSearchOption, ListedOptionSnapshotResponse } from '../types'
import {
  buildSearchOptionsFromSnapshot,
  filterSnapshotRowsByAxisRange,
  formatSeriesConfigLabel,
  getSeriesConfigKey,
  parseTimeseriesFormulaCommand,
  searchTimeseriesSeriesOptions,
} from '../utils'

const SNAPSHOT: ListedOptionSnapshotResponse = {
  requestedDate: '2026-03-07',
  asOfDate: '2026-03-06',
  latestAvailableDate: '2026-03-06',
  periodBusinessDays: 1,
  field: 'open_interest_change',
  labelNamespace: 'Globex',
  contractView: 'constant_maturity',
  rowAxis: 'delta',
  availableRoots: [
    { productFamily: 'UST', productRoot: 'TY' },
    { productFamily: 'STIR', productRoot: 'SFR' },
  ],
  warnings: [],
  contractGroups: [
    {
      id: 'cm:TY:1',
      productFamily: 'UST',
      productRoot: 'TY',
      contractReferenceMode: 'constant_maturity',
      explicitContract: null,
      constantMaturityRank: 1,
      displayLabel: 'TY CM1',
      underlyingLabel: 'TYM26',
      forwardPrice: 111.625,
      expiryDate: '2026-03-27',
      dteDays: 21,
    },
  ],
  rows: [
    {
      rowKey: 'delta:25',
      rowLabel: '25D',
      axisValue: 25,
      strike: 111.5,
      deltaAbs: 25,
      bpsOffset: 12.5,
      cells: {
        'cm:TY:1': {
          call: {
            contractGroupId: 'cm:TY:1',
            side: 'C',
            value: 2100,
            strike: 111.5,
            deltaAbs: 24.8,
            atmOffsetBps: 12.5,
            explicitOptionSymbol: 'TYM26|1115C',
            chartSeries: {
              metricField: 'open_interest_change',
              productFamily: 'UST',
              productRoot: 'TY',
              labelNamespace: 'Globex',
              contractReferenceMode: 'constant_maturity',
              constantMaturityRank: 1,
              selectorType: 'delta',
              side: 'C',
              selectorValue: 25,
              rawSymbolFallback: 'TYM26|1115C',
            },
          },
          put: {
            contractGroupId: 'cm:TY:1',
            side: 'P',
            value: -1800,
            strike: 111.75,
            deltaAbs: 25.3,
            atmOffsetBps: -12.5,
            explicitOptionSymbol: 'TYM26|1117P',
            chartSeries: {
              metricField: 'open_interest_change',
              productFamily: 'UST',
              productRoot: 'TY',
              labelNamespace: 'Globex',
              contractReferenceMode: 'constant_maturity',
              constantMaturityRank: 1,
              selectorType: 'delta',
              side: 'P',
              selectorValue: 25,
              rawSymbolFallback: 'TYM26|1117P',
            },
          },
        },
      },
    },
  ],
}

describe('listed-option-oi-volume utils', () => {
  it('formats stable labels and keys for explicit and aliased series', () => {
    expect(
      formatSeriesConfigLabel({
        metricField: 'volume',
        productFamily: 'STIR',
        productRoot: 'SFR',
        labelNamespace: 'Barchart',
        contractReferenceMode: 'explicit',
        explicitContract: 'SFRZ27',
        selectorType: 'explicit_symbol',
        side: 'C',
        rawSymbolFallback: 'SQZ27|9700C',
      })
    ).toBe('SQZ27|9700C Vol')

    expect(
      getSeriesConfigKey({
        metricField: 'open_interest_change',
        productFamily: 'UST',
        productRoot: 'TY',
        contractReferenceMode: 'constant_maturity',
        constantMaturityRank: 1,
        selectorType: 'delta',
        side: 'C',
        selectorValue: 25,
      })
    ).toBe('open_interest_change:UST:TY:cm:TY:1:delta:25:C')
  })

  it('builds snapshot search options and fuzzy matches raw symbols', () => {
    const options = buildSearchOptionsFromSnapshot(SNAPSHOT)
    const rawMatches = searchTimeseriesSeriesOptions('tym26|1115c', options, 5)
    expect(rawMatches[0]?.label).toBe('TY CM1 25D Call dOI')
  })

  it('does not treat blank top and bottom inputs as zero row-axis filters', () => {
    const rows = [
      ...SNAPSHOT.rows,
      {
        ...SNAPSHOT.rows[0]!,
        rowKey: 'strike:97',
        rowLabel: '97.000',
        axisValue: 97,
        strike: 97,
      },
    ]

    expect(filterSnapshotRowsByAxisRange(rows, '', '')).toHaveLength(2)
    expect(filterSnapshotRowsByAxisRange(rows, '50', '')).toHaveLength(1)
    expect(filterSnapshotRowsByAxisRange(rows, '', '50')).toHaveLength(1)
  })

  it('parses spread and fly commands from search options', () => {
    const options = buildSearchOptionsFromSnapshot(SNAPSHOT)
    const extended: ListedOptionSearchOption[] = [
      ...options,
      {
        ...options[0]!,
        id: 'offset',
        label: 'TY CM1 25bp Call dOI',
        subtitle: 'TY CM1 | 25bp',
        bucket: 'offset' as const,
        config: {
          metricField: 'open_interest_change',
          productFamily: 'UST',
          productRoot: 'TY',
          labelNamespace: 'Globex',
          contractReferenceMode: 'constant_maturity',
          constantMaturityRank: 1,
          selectorType: 'bps_offset',
          side: 'C',
          selectorValue: 25,
          rawSymbolFallback: 'TYM26|1115C',
        },
        aliases: ['TY CM1 25bp Call dOI'],
      },
    ]

    expect(parseTimeseriesFormulaCommand('spread TY CM1 25D Call dOI vs TY CM1 25D Put dOI', extended)).toEqual({
      formulaKind: 'spread',
      name: 'TY CM1 25D Call dOI vs TY CM1 25D Put dOI',
      description: 'TY CM1 25D Call dOI - TY CM1 25D Put dOI',
      series: [extended[0]!.config, extended[1]!.config],
      legs: [
        { seriesId: extended[0]!.id, weight: 1 },
        { seriesId: extended[1]!.id, weight: -1 },
      ],
    })
  })
})
