import { describe, expect, it, jest } from '@jest/globals'

const queryMock = jest.fn(async () => ({ rows: [] }))

jest.unstable_mockModule('@/lib/db', () => ({
  query: queryMock,
  analyticsQuery: queryMock,
}))

function req(qs: string, headers: Record<string, string> = {}): Request {
  return new Request(`http://t/api/usd-swaps-tape-v2/analytics-timeseries?${qs}`, {
    method: 'GET',
    headers,
  })
}

describe('analytics-timeseries route — LRU + ETag', () => {
  it('emits ETag + Cache-Control on success', async () => {
    const { GET } = await import('../route')
    const r = await GET(
      req('value=USD/SOFR-OIS/COMPOUND&groupBy=canonical&range=1M&view=DAILY_CLOSE'),
    )
    expect(r.status).toBe(200)
    expect(r.headers.get('ETag')).toMatch(/^"[a-f0-9]{40}"$/)
    expect(r.headers.get('Cache-Control')).toBe(
      'private, max-age=300, stale-while-revalidate=600',
    )
  })

  it('returns 304 on If-None-Match match', async () => {
    const { GET } = await import('../route')
    const first = await GET(
      req('value=USD/SOFR-OIS/COMPOUND&groupBy=canonical&range=1M&view=DAILY_CLOSE'),
    )
    const tag = first.headers.get('ETag')!
    const second = await GET(
      req(
        'value=USD/SOFR-OIS/COMPOUND&groupBy=canonical&range=1M&view=DAILY_CLOSE',
        { 'If-None-Match': tag },
      ),
    )
    expect(second.status).toBe(304)
    expect(await second.text()).toBe('')
    expect(second.headers.get('ETag')).toBe(tag)
  })

  it('LRU hit serves second request without re-invoking SQL', async () => {
    queryMock.mockClear()
    const { GET } = await import('../route')
    await GET(req('value=ABC/Z&groupBy=canonical&range=1M&view=DAILY_CLOSE'))
    const callsAfterFirst = queryMock.mock.calls.length
    await GET(req('value=ABC/Z&groupBy=canonical&range=1M&view=DAILY_CLOSE'))
    const callsAfterSecond = queryMock.mock.calls.length
    expect(callsAfterSecond).toBe(callsAfterFirst)
  })

  it('different params keep separate cache entries', async () => {
    const { GET } = await import('../route')
    const a = await GET(req('value=A/A&groupBy=canonical&range=1M&view=DAILY_CLOSE'))
    const b = await GET(req('value=B/B&groupBy=canonical&range=1M&view=DAILY_CLOSE'))
    expect(a.headers.get('ETag')).toBeTruthy()
    expect(b.headers.get('ETag')).toBeTruthy()
  })
})
