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

  it('400 when tenor missing', async () => {
    const { GET } = await import('../route')
    const res = await GET(req('fwd=spot'))
    expect(res.status).toBe(400)
  })

  it('200 returns timeseries + recentTrades', async () => {
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
    const { GET } = await import('../route')
    const res = await GET(req('fwd=spot&tenor=5y'))
    expect(res.status).toBe(200)
    const body = await res.json()
    expect(body.timeseries.length).toBe(1)
    expect(body.recentTrades.length).toBe(1)
    expect(body.recentTrades[0].package_id).toBe('pkg-1')
    expect(body.fwd).toBe('spot')
    expect(body.tenor).toBe('5y')
    expect(body.range).toBe('3M')
  })

  it('emits ETag + Cache-Control on success', async () => {
    queryMock.mockResolvedValueOnce({ rows: [] }).mockResolvedValueOnce({ rows: [] })
    const { GET } = await import('../route')
    const r = await GET(req('fwd=spot&tenor=5y&_=etag'))
    expect(r.status).toBe(200)
    expect(r.headers.get('ETag')).toMatch(/^"[a-f0-9]{40}"$/)
    expect(r.headers.get('Cache-Control')).toBe('private, max-age=60, must-revalidate')
  })
})
