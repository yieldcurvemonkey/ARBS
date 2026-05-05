import { describe, expect, it, jest, beforeEach } from '@jest/globals'

const queryMock = jest.fn(async () => ({ rows: [] as unknown[] }))

jest.unstable_mockModule('@/lib/db', () => ({
  query: queryMock,
}))

function req(qs: string = '', headers: Record<string, string> = {}): Request {
  return new Request(`http://t/api/usd-swaps-tape-v2/volume-grid/cell${qs ? '?' + qs : ''}`, {
    method: 'GET',
    headers,
  })
}

beforeEach(() => {
  queryMock.mockReset()
  queryMock.mockResolvedValue({ rows: [] })
})

describe('GET /api/usd-swaps-tape-v2/volume-grid/cell', () => {
  it('400 when fwd missing', async () => {
    const { GET } = await import('../route')
    const res = await GET(req('tenor=5y'))
    expect(res.status).toBe(400)
  })

  it('400 when bucket id is invalid for the active schema', async () => {
    const { GET } = await import('../route')
    const res = await GET(req('fwd=spot&tenor=5_10y')) // 5_10y is legacy-only
    expect(res.status).toBe(400)
  })

  it('200 returns timeseries + recentTrades with schema echoed back', async () => {
    queryMock
      .mockResolvedValueOnce({
        rows: [
          { day: '2026-05-04', notional: 1e9, dv01: 50000, trade_count: 5, idb_count: 3, custy_count: 2 },
        ] as unknown[],
      })
      .mockResolvedValueOnce({
        rows: [
          {
            package_id: 'pkg-1', execution_start: '2026-05-05T13:00:00Z',
            tape_label: '5Y Outright', package_type: 'OUTRIGHT',
            weighted_fixed_rate: 0.0384, total_risk: 50000, total_notional: 1e9,
            venue: 'D2D', is_block_any: false,
          },
        ] as unknown[],
      })
      .mockResolvedValueOnce({
        rows: [
          {
            bucket_index: 0,
            minute_of_day: 30,
            current_value: 1e9,
            average_value: 8e8,
            observed_days: 12,
            as_of_ts: '2026-05-05T13:00:00Z',
          },
        ] as unknown[],
      })
    const { GET } = await import('../route')
    const res = await GET(req('fwd=spot&tenor=5y&forwardSchema=default&tenorSchema=default&packageType=outright'))
    expect(res.status).toBe(200)
    const body = await res.json()
    expect(body.timeseries.length).toBe(1)
    expect(body.recentTrades.length).toBe(1)
    expect(body.intradaySeasonality.points.length).toBe(1)
    expect(body.intradaySeasonality.observedDays).toBe(12)
    expect(body.forwardSchema).toBe('default')
    expect(body.packageType).toBe('outright')
  })
})
