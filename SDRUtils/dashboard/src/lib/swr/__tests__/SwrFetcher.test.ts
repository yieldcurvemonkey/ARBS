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

  it('caches ETag for next request via If-None-Match', async () => {
    const fetcher = createFetcher()
    ;(global.fetch as jest.Mock).mockResolvedValueOnce(
      new Response(JSON.stringify({ v: 1 }), {
        status: 200,
        headers: { ETag: '"abc"' },
      }),
    )
    await fetcher('/api/x')

    ;(global.fetch as jest.Mock).mockResolvedValueOnce(
      new Response(null, { status: 304 }),
    )
    const r = await fetcher('/api/x')

    const secondCall = (global.fetch as jest.Mock).mock.calls[1]
    expect((secondCall[1] as { headers: Record<string, string> }).headers['If-None-Match']).toBe('"abc"')
    expect(r).toEqual({ v: 1 }) // 304 reuses prior payload
  })

  it('throws on non-200/304 responses', async () => {
    ;(global.fetch as jest.Mock).mockResolvedValueOnce(
      new Response('err', { status: 500 }),
    )
    const fetcher = createFetcher()
    await expect(fetcher('/api/x')).rejects.toThrow(/500/)
  })

  it('does not send If-None-Match on first request', async () => {
    const fetcher = createFetcher()
    ;(global.fetch as jest.Mock).mockResolvedValueOnce(
      new Response('{}', { status: 200, headers: { ETag: '"a"' } }),
    )
    await fetcher('/api/y')
    const firstCall = (global.fetch as jest.Mock).mock.calls[0]
    expect(
      (firstCall[1] as { headers: Record<string, string> }).headers['If-None-Match'],
    ).toBeUndefined()
  })

  it('keeps separate ETag caches per URL', async () => {
    const fetcher = createFetcher()
    ;(global.fetch as jest.Mock).mockResolvedValueOnce(
      new Response(JSON.stringify({ v: 'a' }), {
        status: 200,
        headers: { ETag: '"a"' },
      }),
    )
    await fetcher('/api/a')

    ;(global.fetch as jest.Mock).mockResolvedValueOnce(
      new Response(JSON.stringify({ v: 'b' }), {
        status: 200,
        headers: { ETag: '"b"' },
      }),
    )
    await fetcher('/api/b')

    ;(global.fetch as jest.Mock).mockResolvedValueOnce(
      new Response(null, { status: 304 }),
    )
    await fetcher('/api/a')

    const aCall = (global.fetch as jest.Mock).mock.calls[2]
    expect(
      (aCall[1] as { headers: Record<string, string> }).headers['If-None-Match'],
    ).toBe('"a"')
  })
})
