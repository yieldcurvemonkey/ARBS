import { describe, expect, it, beforeEach, jest } from '@jest/globals'
import { createFetcher } from '../SwrFetcher'

describe('SwrFetcher', () => {
  beforeEach(() => {
    ;(global as unknown as { fetch: jest.Mock }).fetch = jest.fn()
  })

  it('returns parsed JSON on 200', async () => {
    ;(global.fetch as jest.Mock).mockResolvedValueOnce(
      new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { ETag: '"abc"' },
      }),
    )
    const fetcher = createFetcher()
    const r = await fetcher('/api/x')
    expect(r).toEqual({ ok: true })
  })

  it('throws on non-2xx responses', async () => {
    ;(global.fetch as jest.Mock).mockResolvedValueOnce(
      new Response('err', { status: 500 }),
    )
    const fetcher = createFetcher()
    await expect(fetcher('/api/x')).rejects.toThrow(/500/)
  })

  it('hands the URL to fetch() with default cache mode (no manual ETag layer)', async () => {
    // The browser's HTTP cache handles ETag + If-None-Match natively
    // when the response carries Cache-Control + ETag. We deliberately
    // do NOT add a parallel JS-level ETag cache — that path doesn't
    // survive page reload, while the browser's HTTP cache does.
    ;(global.fetch as jest.Mock).mockImplementation(
      () => Promise.resolve(new Response(JSON.stringify({ v: 1 }), { status: 200 })),
    )
    const fetcher = createFetcher()
    await fetcher('/api/x')
    await fetcher('/api/x')
    const firstCall = (global.fetch as jest.Mock).mock.calls[0]
    const secondCall = (global.fetch as jest.Mock).mock.calls[1]
    // No If-None-Match header injected by JS — the browser owns that.
    expect(firstCall[1]).toBeUndefined()
    expect(secondCall[1]).toBeUndefined()
  })
})
