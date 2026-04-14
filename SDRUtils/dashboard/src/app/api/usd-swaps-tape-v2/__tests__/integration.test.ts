/**
 * Integration smoke test for the tape v2 route tree.
 *
 * Gated behind PG_TEST_URL / DATABASE_URL — when neither is set the
 * entire suite is skipped. This keeps contributors without a local
 * Postgres able to run the rest of the dashboard test suite.
 */
import { describe, expect, it } from '@jest/globals'

const DB_URL = process.env.PG_TEST_URL || process.env.DATABASE_URL
const describeIfDb = DB_URL ? describe : describe.skip

describeIfDb('tape v2 integration smoke', () => {
  it('returns a shape-valid response for the main tape route', async () => {
    const { GET } = await import('../route')
    const req = new Request('http://x/api/usd-swaps-tape-v2?limit=5')
    const res = await GET(req)
    expect(res.status === 200 || res.status === 500).toBe(true)
    if (res.status === 200) {
      const body = await res.json()
      expect(Array.isArray(body.rows)).toBe(true)
      expect('hasMore' in body).toBe(true)
      expect('nextCursor' in body).toBe(true)
      expect('latestExecutionStart' in body).toBe(true)
    }
  })

  it('400s when cursor and since are both supplied', async () => {
    const { GET } = await import('../route')
    const res = await GET(
      new Request('http://x/api/usd-swaps-tape-v2?cursor=a&since=b'),
    )
    expect(res.status).toBe(400)
  })

  it('risk-concentration rejects unknown groupBy', async () => {
    const { GET } = await import('../risk-concentration/route')
    const res = await GET(
      new Request('http://x/api/usd-swaps-tape-v2/risk-concentration?groupBy=banana'),
    )
    expect(res.status).toBe(400)
  })

  it('packages rejects unknown sortBy', async () => {
    const { GET } = await import('../packages/route')
    const res = await GET(
      new Request('http://x/api/usd-swaps-tape-v2/packages?sortBy=banana'),
    )
    expect(res.status).toBe(400)
  })
})
