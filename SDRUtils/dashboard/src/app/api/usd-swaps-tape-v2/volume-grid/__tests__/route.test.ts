import { describe, expect, it, jest, beforeEach } from '@jest/globals'

const queryMock = jest.fn(async () => ({ rows: [] as unknown[] }))

jest.unstable_mockModule('@/lib/db', () => ({
  query: queryMock,
}))

function req(qs: string = '', headers: Record<string, string> = {}): Request {
  return new Request(`http://t/api/usd-swaps-tape-v2/volume-grid${qs ? '?' + qs : ''}`, {
    method: 'GET',
    headers,
  })
}

beforeEach(() => {
  queryMock.mockReset()
  queryMock.mockResolvedValue({ rows: [] })
})

describe('GET /api/usd-swaps-tape-v2/volume-grid', () => {
  it('400 on invalid metric', async () => {
    const { GET } = await import('../route')
    const res = await GET(req('metric=foo'))
    expect(res.status).toBe(400)
  })

  it('400 on invalid packageType', async () => {
    const { GET } = await import('../route')
    const res = await GET(req('packageType=bogus'))
    expect(res.status).toBe(400)
  })

  it('200 with matrix shape on happy path', async () => {
    queryMock.mockResolvedValueOnce({
      rows: [
        {
          fwd: 'spot', tenor: '5y',
          current_value: 100, trade_count: 5,
          prior_array: [10, 20, 30],
          p25: 15, p50: 20, p75: 25, pmin: 10, pmax: 30, n: 3,
          as_of_ts: '2026-05-05T14:32:00Z',
        },
      ] as unknown[],
    })
    const { GET } = await import('../route')
    const res = await GET(req('metric=notional&period=today&lookbackDays=90&forwardSchema=default&tenorSchema=default&packageType=outright'))
    expect(res.status).toBe(200)
    const body = await res.json()
    expect(body.metric).toBe('notional')
    expect(body.forwardSchema).toBe('default')
    expect(body.tenorSchema).toBe('default')
    expect(body.packageType).toBe('outright')
    expect(body.cells.length).toBe(1)
    expect(body.axes.forward.buckets.length).toBe(8)
    expect(body.axes.tenor.buckets.length).toBe(16)
  })
})
