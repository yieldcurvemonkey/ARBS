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
    const res = await GET(req('metric=notional&period=today&lookbackDays=90'))
    expect(res.status).toBe(200)
    const body = await res.json()
    expect(body.metric).toBe('notional')
    expect(body.period).toBe('today')
    expect(body.cells.length).toBe(1)
    expect(body.cells[0]).toMatchObject({
      fwd: 'spot', tenor: '5y',
      current: 100, tradeCount: 5,
      baseline: { p25: 15, p50: 20, p75: 25, min: 10, max: 30, n: 3 },
      percentile: 100,
    })
    expect(body.totals.grand.current).toBe(100)
  })

  it('emits ETag + Cache-Control on success', async () => {
    queryMock.mockResolvedValueOnce({ rows: [] })
    const { GET } = await import('../route')
    const r = await GET(req('metric=notional&period=today&lookbackDays=90&_=etag'))
    expect(r.status).toBe(200)
    expect(r.headers.get('ETag')).toMatch(/^"[a-f0-9]{40}"$/)
    expect(r.headers.get('Cache-Control')).toBe('private, max-age=60, must-revalidate')
  })

  it('returns 304 on If-None-Match match', async () => {
    queryMock.mockResolvedValueOnce({ rows: [] })
    const { GET } = await import('../route')
    const first = await GET(req('metric=notional&period=today&lookbackDays=90&_=ifnone'))
    const tag = first.headers.get('ETag')!
    const second = await GET(
      req('metric=notional&period=today&lookbackDays=90&_=ifnone', { 'If-None-Match': tag }),
    )
    expect(second.status).toBe(304)
  })
})
