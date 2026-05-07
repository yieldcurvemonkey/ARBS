import { describe, expect, it, jest, beforeAll } from '@jest/globals'

const queryMock = jest.fn(async () => ({ rows: [] }))

jest.mock('@/lib/db', () => ({
  query: queryMock,
}))

function req(qs: string, headers: Record<string, string> = {}): Request {
  return new Request(`http://t/api/usd-swaps-tape-v2/rarity?${qs}`, {
    method: 'GET',
    headers,
  })
}

let GET: (request: Request) => Promise<Response>

beforeAll(async () => {
  const mod = await import('../route')
  GET = mod.GET
})

describe('rarity route — LRU + ETag', () => {
  it(
    'emits ETag + Cache-Control on success',
    async () => {
      const r = await GET(
        req('value=USD/SOFR-OIS/COMPOUND&groupBy=canonical&lookback=90&binMetric=fixed_rate'),
      )
      expect(r.status).toBe(200)
      expect(r.headers.get('ETag')).toMatch(/^"[a-f0-9]{40}"$/)
      expect(r.headers.get('Cache-Control')).toBe(
        'private, max-age=300, stale-while-revalidate=600',
      )
    },
    60_000,
  )

  it(
    'returns 304 on If-None-Match match',
    async () => {
      const first = await GET(
        req('value=A/A&groupBy=canonical&lookback=90&binMetric=fixed_rate'),
      )
      const tag = first.headers.get('ETag')!
      expect(tag).toBeTruthy()
      const second = await GET(
        req(
          'value=A/A&groupBy=canonical&lookback=90&binMetric=fixed_rate',
          { 'If-None-Match': tag },
        ),
      )
      expect(second.status).toBe(304)
      expect(await second.text()).toBe('')
      expect(second.headers.get('ETag')).toBe(tag)
    },
    60_000,
  )

  it(
    'LRU hit serves second request without re-invoking SQL',
    async () => {
      queryMock.mockClear()
      await GET(req('value=B/B&groupBy=canonical&lookback=90&binMetric=fixed_rate'))
      const callsAfterFirst = queryMock.mock.calls.length
      await GET(req('value=B/B&groupBy=canonical&lookback=90&binMetric=fixed_rate'))
      const callsAfterSecond = queryMock.mock.calls.length
      expect(callsAfterSecond).toBe(callsAfterFirst)
    },
    60_000,
  )

  it('400 errors do not pollute the cache', async () => {
    const r = await GET(req('groupBy=canonical&lookback=90'))
    expect(r.status).toBe(400)
    expect(r.headers.get('ETag')).toBeNull()
  })
})
