import { beforeEach, describe, expect, it, jest } from '@jest/globals'

const mockedQuery = jest.fn()

jest.unstable_mockModule('@/lib/db', () => ({
  query: mockedQuery,
}))

const {
  fetchListedOptionSnapshot,
  fetchListedOptionTimeseriesCollection,
} = await import('@/lib/listed-option-oi-volume/data')

describe('listed-option-oi-volume data', () => {
  beforeEach(() => {
    mockedQuery.mockReset()
  })

  it('falls back to the latest stored snapshot on or before the requested date', async () => {
    mockedQuery.mockImplementation(async (sql) => {
      const statement = String(sql)

      if (statement.includes('SELECT MAX(as_of_date)::text AS as_of_date') && statement.includes('WHERE as_of_date <=')) {
        return { rows: [{ as_of_date: '2026-03-06' }] } as any
      }
      if (statement.includes('SELECT MAX(as_of_date)::text AS as_of_date FROM arbs_listed_option_oi_volume_v1')) {
        return { rows: [{ as_of_date: '2026-03-06' }] } as any
      }
      if (statement.includes('SELECT DISTINCT product_family, product_root')) {
        return { rows: [{ product_family: 'UST', product_root: 'TY' }] } as any
      }
      if (statement.includes('WITH ranked_contracts AS')) {
        return {
          rows: [
            {
              as_of_date: '2026-03-06',
              product_family: 'UST',
              product_root: 'TY',
              option_contract: 'TYM26',
              option_contract_barchart: 'TYM26',
              underlying_contract: 'TYM26',
              underlying_barchart: 'TYM26',
              explicit_option_symbol: 'TYM26|1115C',
              right: 'C',
              strike: 111.5,
              delta_abs: 25.1,
              atm_offset_bps: 12.5,
              open_interest: 2500,
              volume: 500,
              forward_price: 111.625,
              expiry_date: '2026-03-27',
              dte_days: 21,
              cm_rank: 1,
            },
            {
              as_of_date: '2026-03-06',
              product_family: 'UST',
              product_root: 'TY',
              option_contract: 'TYM26',
              option_contract_barchart: 'TYM26',
              underlying_contract: 'TYM26',
              underlying_barchart: 'TYM26',
              explicit_option_symbol: 'TYM26|1117P',
              right: 'P',
              strike: 111.75,
              delta_abs: 24.9,
              atm_offset_bps: -12.5,
              open_interest: 1500,
              volume: 300,
              forward_price: 111.625,
              expiry_date: '2026-03-27',
              dte_days: 21,
              cm_rank: 1,
            },
          ],
        } as any
      }
      if (statement.includes('SELECT DISTINCT as_of_date::text AS as_of_date')) {
        return { rows: [{ as_of_date: '2026-03-05' }, { as_of_date: '2026-03-06' }] } as any
      }
      if (statement.includes('WHERE (explicit_option_symbol, as_of_date) IN')) {
        return {
          rows: [
            {
              explicit_option_symbol: 'TYM26|1115C',
              as_of_date: '2026-03-05',
              open_interest: 1000,
              volume: 250,
            },
            {
              explicit_option_symbol: 'TYM26|1117P',
              as_of_date: '2026-03-05',
              open_interest: 2000,
              volume: 450,
            },
          ],
        } as any
      }

      throw new Error(`Unexpected query: ${statement}`)
    })

    const response = await fetchListedOptionSnapshot({
      requestedDate: '2026-03-07',
      field: 'open_interest_change',
      periodBusinessDays: 1,
      labelNamespace: 'Globex',
      contractView: 'constant_maturity',
      rowAxis: 'delta',
      productFamily: 'UST',
      productRoots: ['TY'],
    })

    expect(response.asOfDate).toBe('2026-03-06')
    expect(response.warnings).toContain(
      'Requested 2026-03-07, showing latest stored snapshot on or before 2026-03-06.'
    )
    expect(response.contractGroups[0]?.displayLabel).toBe('TY CM1')
    expect(response.rows[0]?.cells['cm:TY:1']?.call?.value).toBe(1500)
    expect(response.rows[0]?.cells['cm:TY:1']?.put?.value).toBe(-500)
  })

  it('returns mixed explicit, delta, and offset timeseries selections', async () => {
    mockedQuery.mockImplementation(async (sql) => {
      const statement = String(sql)

      if (statement.includes('SELECT DISTINCT as_of_date::text AS as_of_date')) {
        return {
          rows: [
            { as_of_date: '2026-03-03' },
            { as_of_date: '2026-03-04' },
            { as_of_date: '2026-03-05' },
          ],
        } as any
      }

      if (statement.includes('WITH ranked_contracts AS')) {
        if (statement.includes('t.explicit_option_symbol =')) {
          return {
            rows: [
              {
                as_of_date: '2026-03-03',
                product_family: 'STIR',
                product_root: 'SFR',
                option_contract: 'SFRZ27',
                option_contract_barchart: 'SQZ27',
                underlying_contract: 'SFRZ27',
                underlying_barchart: 'SQZ27',
                explicit_option_symbol: 'SQZ27|9700C',
                right: 'C',
                strike: 97.0,
                delta_abs: 24.8,
                atm_offset_bps: 25,
                open_interest: 100,
                volume: 10,
                forward_price: 96.75,
                expiry_date: '2027-12-17',
                dte_days: 654,
                cm_rank: 1,
              },
              {
                as_of_date: '2026-03-04',
                product_family: 'STIR',
                product_root: 'SFR',
                option_contract: 'SFRZ27',
                option_contract_barchart: 'SQZ27',
                underlying_contract: 'SFRZ27',
                underlying_barchart: 'SQZ27',
                explicit_option_symbol: 'SQZ27|9700C',
                right: 'C',
                strike: 97.0,
                delta_abs: 25.0,
                atm_offset_bps: 25,
                open_interest: 120,
                volume: 11,
                forward_price: 96.8,
                expiry_date: '2027-12-17',
                dte_days: 653,
                cm_rank: 1,
              },
            ],
          } as any
        }

        return {
          rows: [
            {
              as_of_date: '2026-03-03',
              product_family: 'UST',
              product_root: 'TY',
              option_contract: 'TYM26',
              option_contract_barchart: 'TYM26',
              underlying_contract: 'TYM26',
              underlying_barchart: 'TYM26',
              explicit_option_symbol: 'TYM26|1115C',
              right: 'C',
              strike: 111.5,
              delta_abs: 24.6,
              atm_offset_bps: 12.5,
              open_interest: 2000,
              volume: 400,
              forward_price: 111.625,
              expiry_date: '2026-03-27',
              dte_days: 24,
              cm_rank: 1,
            },
            {
              as_of_date: '2026-03-04',
              product_family: 'UST',
              product_root: 'TY',
              option_contract: 'TYM26',
              option_contract_barchart: 'TYM26',
              underlying_contract: 'TYM26',
              underlying_barchart: 'TYM26',
              explicit_option_symbol: 'TYM26|1115C',
              right: 'C',
              strike: 111.5,
              delta_abs: 25.2,
              atm_offset_bps: 12.5,
              open_interest: 2400,
              volume: 410,
              forward_price: 111.625,
              expiry_date: '2026-03-27',
              dte_days: 23,
              cm_rank: 1,
            },
            {
              as_of_date: '2026-03-05',
              product_family: 'UST',
              product_root: 'TY',
              option_contract: 'TYM26',
              option_contract_barchart: 'TYM26',
              underlying_contract: 'TYM26',
              underlying_barchart: 'TYM26',
              explicit_option_symbol: 'TYM26|1117P',
              right: 'P',
              strike: 111.75,
              delta_abs: 24.9,
              atm_offset_bps: -12.5,
              open_interest: 2100,
              volume: 390,
              forward_price: 111.625,
              expiry_date: '2026-03-27',
              dte_days: 22,
              cm_rank: 1,
            },
          ],
        } as any
      }

      if (statement.includes('WHERE (explicit_option_symbol, as_of_date) IN')) {
        return { rows: [] } as any
      }

      throw new Error(`Unexpected query: ${statement}`)
    })

    const response = await fetchListedOptionTimeseriesCollection({
      periodBusinessDays: 1,
      range: '1M',
      series: [
        {
          metricField: 'open_interest',
          productFamily: 'STIR',
          productRoot: 'SFR',
          labelNamespace: 'Barchart',
          contractReferenceMode: 'explicit',
          explicitContract: 'SFRZ27',
          selectorType: 'explicit_symbol',
          side: 'C',
          rawSymbolFallback: 'SQZ27|9700C',
        },
        {
          metricField: 'open_interest',
          productFamily: 'UST',
          productRoot: 'TY',
          labelNamespace: 'Globex',
          contractReferenceMode: 'constant_maturity',
          constantMaturityRank: 1,
          selectorType: 'delta',
          side: 'C',
          selectorValue: 25,
        },
        {
          metricField: 'open_interest',
          productFamily: 'UST',
          productRoot: 'TY',
          labelNamespace: 'Globex',
          contractReferenceMode: 'constant_maturity',
          constantMaturityRank: 1,
          selectorType: 'bps_offset',
          side: 'P',
          selectorValue: 12.5,
        },
      ],
    })

    expect(response.warnings).toEqual([])
    expect(response.series).toHaveLength(3)
    expect(response.series[0]?.points).toEqual([
      { asOf: '2026-03-03', value: 100 },
      { asOf: '2026-03-04', value: 120 },
    ])
    expect(response.series[1]?.points).toEqual([
      { asOf: '2026-03-03', value: 2000 },
      { asOf: '2026-03-04', value: 2400 },
      { asOf: '2026-03-05', value: null },
    ])
    expect(response.series[2]?.points.at(-1)).toEqual({ asOf: '2026-03-05', value: 2100 })
  })
})
