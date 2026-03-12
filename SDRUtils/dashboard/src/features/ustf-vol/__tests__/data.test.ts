import { beforeEach, describe, expect, it, jest } from '@jest/globals'

const mockedQuery = jest.fn()

jest.unstable_mockModule('@/lib/db', () => ({
  query: mockedQuery,
}))

const { fetchComparisonSnapshot, fetchTimeseriesCollection } = await import('@/lib/ustf-vol/data')

describe('ustf-vol data', () => {
  beforeEach(() => {
    mockedQuery.mockReset()
  })

  it('extracts delta and strike-offset OTM vols from stored JSON payloads', async () => {
    mockedQuery.mockImplementation(async (sql) => {
      const statement = String(sql)

      if (statement.includes('arbs_ustf_vol_snapshots_v2')) {
        return {
          rows: [
            {
              as_of_date: '2026-03-03',
              atm_nvol_bps: 121.5,
              delta_otm_vols: {
                call: {
                  '10d': {
                    vol_bps: 132.4,
                  },
                },
              },
              strike_offset_otm_vols: {},
            },
          ],
        } as any
      }

      if (statement.includes('arbs_swaption_vol_snapshots_v2')) {
        return {
          rows: [
            {
              as_of_date: '2026-03-03',
              atm_nvol_bps: 98.2,
              delta_otm_vols: '{}',
              strike_offset_otm_vols: JSON.stringify({
                payer: {
                  '25': {
                    vol_bps: 104.75,
                  },
                },
              }),
            },
          ],
        } as any
      }

      throw new Error(`Unexpected query: ${statement}`)
    })

    const response = await fetchTimeseriesCollection({
      range: '1M',
      series: [
        {
          type: 'ustf',
          product: 'TY',
          expiry: '1M',
          volMetric: { kind: 'delta_otm', side: 'call', delta: 10 },
        },
        {
          type: 'swaption',
          tail: '7Y',
          expiry: '1M',
          volMetric: { kind: 'strike_offset_otm', side: 'payer', offsetBps: 25 },
        },
      ],
    })

    expect(response.warnings).toEqual([])
    expect(response.series).toEqual([
      {
        id: 'ustf:TY:1M:delta:call:10',
        label: '1M TY 10D Call',
        config: {
          type: 'ustf',
          product: 'TY',
          expiry: '1M',
          volMetric: { kind: 'delta_otm', side: 'call', delta: 10 },
        },
        points: [{ asOf: '2026-03-03', value: 132.4 }],
        stats: {
          latest: 132.4,
          mean: 132.4,
          min: 132.4,
          max: 132.4,
          stdev: 0,
          zScore: null,
          count: 1,
        },
      },
      {
        id: 'swaption:7Y:1M:offset:payer:25',
        label: '1Mx7Y 25bp Payer Swpn',
        config: {
          type: 'swaption',
          tail: '7Y',
          expiry: '1M',
          volMetric: { kind: 'strike_offset_otm', side: 'payer', offsetBps: 25 },
        },
        points: [{ asOf: '2026-03-03', value: 104.75 }],
        stats: {
          latest: 104.75,
          mean: 104.75,
          min: 104.75,
          max: 104.75,
          stdev: 0,
          zScore: null,
          count: 1,
        },
      },
    ])
  })

  it('builds the snapshot from the most recently updated comparison rows', async () => {
    mockedQuery.mockImplementation(async (sql) => {
      const statement = String(sql)

      if (statement.includes('arbs_ustf_vs_swaption_comparison_v2')) {
        return {
          rows: [
            {
              as_of_date: '2026-03-06',
              product: 'TY',
              expiry_label: '1M',
              swaption_expiry_label: '1M',
              swaption_tail_label: '7Y',
              ustf_atm_nvol_bps: 105,
              swaption_atm_nvol_bps: 100,
              updated_at: '2026-03-12T13:31:00.610Z',
            },
            {
              as_of_date: '2025-11-14',
              product: 'TY',
              expiry_label: '1M',
              swaption_expiry_label: '1M',
              swaption_tail_label: '7Y',
              ustf_atm_nvol_bps: 90,
              swaption_atm_nvol_bps: 110,
              updated_at: '2026-03-12T16:39:18.584Z',
            },
          ],
        } as any
      }

      throw new Error(`Unexpected query: ${statement}`)
    })

    const response = await fetchComparisonSnapshot()
    const targetRow = response.rows.find((row) => row.pairLabel === '1M TY vs 1Mx7Y')

    expect(response.latestUpdatedAt).toBe('2026-03-12T16:39:18.584Z')
    expect(targetRow).toEqual({
      pairLabel: '1M TY vs 1Mx7Y',
      asOfDate: '2025-11-14',
      updatedAt: '2026-03-12T16:39:18.584Z',
      listedLabel: '1M TY ATM',
      otcLabel: '1Mx7Y Swpn',
      listedVol: 90,
      otcVol: 110,
      spread: -20,
      spreadZScore: -1,
    })
  })
})
