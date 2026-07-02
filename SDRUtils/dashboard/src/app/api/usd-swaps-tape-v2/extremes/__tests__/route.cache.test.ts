import { describe, expect, it, jest } from '@jest/globals'

const queryMock = jest.fn(async () => ({ rows: [] }))

jest.unstable_mockModule('@/lib/db', () => ({
  query: queryMock,
  analyticsQuery: queryMock,
}))

function req(qs: string, headers: Record<string, string> = {}): Request {
  return new Request(`http://t/api/usd-swaps-tape-v2/extremes?${qs}`, {
    method: 'GET',
    headers,
  })
}

describe('extremes route — LRU + ETag', () => {
  it('emits ETag + Cache-Control on success', async () => {
    const { GET } = await import('../route')
    const r = await GET(req('value=USD/SOFR-OIS/COMPOUND&groupBy=canonical'))
    expect(r.status).toBe(200)
    expect(r.headers.get('ETag')).toMatch(/^"[a-f0-9]{40}"$/)
    expect(r.headers.get('Cache-Control')).toBe(
      'private, max-age=300, stale-while-revalidate=600',
    )
  })

  it('returns 304 on If-None-Match match', async () => {
    const { GET } = await import('../route')
    const first = await GET(req('value=USD/SOFR-OIS/COMPOUND&groupBy=canonical'))
    const tag = first.headers.get('ETag')!
    const second = await GET(
      req('value=USD/SOFR-OIS/COMPOUND&groupBy=canonical', {
        'If-None-Match': tag,
      }),
    )
    expect(second.status).toBe(304)
    expect(await second.text()).toBe('')
    expect(second.headers.get('ETag')).toBe(tag)
  })

  it('LRU hit serves second request without re-invoking SQL', async () => {
    queryMock.mockClear()
    const { GET } = await import('../route')
    await GET(req('value=ABC/Z&groupBy=canonical'))
    const callsAfterFirst = queryMock.mock.calls.length
    await GET(req('value=ABC/Z&groupBy=canonical'))
    const callsAfterSecond = queryMock.mock.calls.length
    expect(callsAfterSecond).toBe(callsAfterFirst)
  })

  it('400 errors do not pollute the cache', async () => {
    const { GET } = await import('../route')
    const r = await GET(req('groupBy=canonical'))
    expect(r.status).toBe(400)
    expect(r.headers.get('ETag')).toBeNull()
  })
})
