import { describe, expect, it, jest } from '@jest/globals'

jest.mock('@/lib/db', () => ({
  query: jest.fn(async () => ({ rows: [] })),
}))
jest.mock('@/lib/usd-swaps-tape-v2', () => ({
  resolveDisplayView: jest.fn(async () => ({
    view: 'arbs_usd_swap_tape_display_v2',
    columns: 'd.*',
  })),
}))

describe('GET /api/usd-swaps-tape-v2 cache-control', () => {
  it('caches initial unfiltered fetch (no cursor / since / columnFilters)', async () => {
    const { GET } = await import('../route')
    const res = await GET(
      new Request('http://x/api/usd-swaps-tape-v2?limit=5'),
    )
    expect(res.headers.get('Cache-Control')).toContain('s-maxage=5')
  })

  it('skips cache header when columnFilters is non-empty', async () => {
    const { GET } = await import('../route')
    const cf = encodeURIComponent(
      JSON.stringify({
        tape_label: {
          operator: 'and',
          constraints: [{ value: '10Y', matchMode: 'contains' }],
        },
      }),
    )
    const res = await GET(
      new Request(`http://x/api/usd-swaps-tape-v2?limit=5&columnFilters=${cf}`),
    )
    expect(res.headers.get('Cache-Control')).toBeNull()
  })

  it('skips cache header when cursor is present (existing behaviour)', async () => {
    const { GET } = await import('../route')
    const res = await GET(
      new Request(
        'http://x/api/usd-swaps-tape-v2?limit=5&cursor=2026-04-23T00:00:00Z',
      ),
    )
    expect(res.headers.get('Cache-Control')).toBeNull()
  })

  it('skips cache header when since is present (existing behaviour)', async () => {
    const { GET } = await import('../route')
    const res = await GET(
      new Request(
        'http://x/api/usd-swaps-tape-v2?limit=5&since=2026-04-23T00:00:00Z',
      ),
    )
    expect(res.headers.get('Cache-Control')).toBeNull()
  })

  it('caches when columnFilters is the empty object {}', async () => {
    const { GET } = await import('../route')
    const cf = encodeURIComponent('{}')
    const res = await GET(
      new Request(`http://x/api/usd-swaps-tape-v2?limit=5&columnFilters=${cf}`),
    )
    expect(res.headers.get('Cache-Control')).toContain('s-maxage=5')
  })
})
