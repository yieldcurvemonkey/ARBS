import { describe, expect, it, jest, beforeAll, beforeEach } from '@jest/globals'

// Typed per the precedent in src/lib/__tests__/tape-overrides.test.ts and
// overrides/__tests__/route.test.ts: an untyped jest.fn() here infers a
// `never` parameter type from jest's UnknownFunction default, which tsc
// rejects once mockResolvedValue* is called with concrete row shapes below.
const queryMock = jest.fn<(sql: string, params?: unknown[]) => Promise<{ rows: unknown[] }>>(
  async () => ({ rows: [] as unknown[] }),
)
jest.unstable_mockModule('@/lib/db', () => ({ query: queryMock }))

let GET: any, POST: any
beforeAll(async () => {
  const mod = await import('../route')
  GET = mod.GET; POST = mod.POST
})
beforeEach(() => {
  queryMock.mockReset()
  queryMock.mockResolvedValue({ rows: [] })
})
function post(body: unknown): Request {
  return new Request('http://t/api/usd-swaps-tape-v2/notes', {
    method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body),
  })
}

describe('POST /notes', () => {
  it('400 on bad target_type', async () => {
    const res = await POST(post({ target_type: 'BOGUS', target_id: 'P1', author: 'me', body: 'hi' }))
    expect(res.status).toBe(400)
  })
  it('400 when author or body missing', async () => {
    expect((await POST(post({ target_type: 'TRADE', target_id: 'T1', author: '', body: 'hi' }))).status).toBe(400)
    expect((await POST(post({ target_type: 'TRADE', target_id: 'T1', author: 'me', body: '  ' }))).status).toBe(400)
  })
  it('inserts and returns note_id', async () => {
    queryMock.mockResolvedValueOnce({ rows: [{ note_id: 'N1' }] })
    const res = await POST(post({ target_type: 'PACKAGE', target_id: 'P1', author: 'me', body: 'looks like a switch' }))
    expect(res.status).toBe(200)
    const body = await res.json()
    expect(body.success).toBe(true)
    expect(body.note_id).toBe('N1')
  })
})

describe('GET /notes', () => {
  it('400 when target params missing', async () => {
    const res = await GET(new Request('http://t/api/usd-swaps-tape-v2/notes'))
    expect(res.status).toBe(400)
  })
  it('returns { rows }', async () => {
    queryMock.mockResolvedValueOnce({ rows: [{ note_id: 'N1' }] })
    const res = await GET(new Request('http://t/api/usd-swaps-tape-v2/notes?target_type=TRADE&target_id=T1'))
    expect(res.status).toBe(200)
    expect((await res.json()).rows).toEqual([{ note_id: 'N1' }])
  })
})
