import { describe, expect, it, jest, beforeAll, beforeEach } from '@jest/globals'

// Typed per the precedent in src/lib/__tests__/tape-overrides.test.ts and
// overrides/__tests__/route.test.ts: an untyped jest.fn() here infers a
// `never` parameter type from jest's UnknownFunction default, which tsc
// rejects once mockResolvedValue* is called with concrete row shapes below.
const queryMock = jest.fn<(sql: string, params?: unknown[]) => Promise<{ rows: unknown[] }>>(
  async () => ({ rows: [] as unknown[] }),
)
jest.unstable_mockModule('@/lib/db', () => ({ query: queryMock }))

let PATCH: any, DELETE: any
beforeAll(async () => {
  const mod = await import('../route')
  PATCH = mod.PATCH; DELETE = mod.DELETE
})
beforeEach(() => {
  queryMock.mockReset()
  queryMock.mockResolvedValue({ rows: [] })
})
const ctx = (id: string) => ({ params: Promise.resolve({ noteId: id }) })
function req(method: string, body: unknown): Request {
  return new Request('http://t/api/usd-swaps-tape-v2/notes/N1', {
    method, headers: { 'content-type': 'application/json' }, body: JSON.stringify(body),
  })
}

describe('PATCH /notes/[noteId]', () => {
  it('404 when note missing', async () => {
    queryMock.mockResolvedValueOnce({ rows: [] })
    const res = await PATCH(req('PATCH', { author: 'me', body: 'edit' }), ctx('N1'))
    expect(res.status).toBe(404)
  })
  it('403 when author is not the note owner', async () => {
    queryMock.mockResolvedValueOnce({ rows: [{ note_id: 'N1', author: 'someone-else' }] })
    const res = await PATCH(req('PATCH', { author: 'me', body: 'edit' }), ctx('N1'))
    expect(res.status).toBe(403)
  })
  it('updates when author matches', async () => {
    queryMock
      .mockResolvedValueOnce({ rows: [{ note_id: 'N1', author: 'me' }] })
      .mockResolvedValueOnce({ rows: [{ note_id: 'N1' }] })
    const res = await PATCH(req('PATCH', { author: 'me', body: 'edit' }), ctx('N1'))
    expect(res.status).toBe(200)
    expect((await res.json()).success).toBe(true)
  })
})

describe('DELETE /notes/[noteId]', () => {
  it('403 when author mismatches', async () => {
    queryMock.mockResolvedValueOnce({ rows: [{ note_id: 'N1', author: 'other' }] })
    const res = await DELETE(req('DELETE', { author: 'me' }), ctx('N1'))
    expect(res.status).toBe(403)
  })
  it('soft-deletes when author matches', async () => {
    queryMock
      .mockResolvedValueOnce({ rows: [{ note_id: 'N1', author: 'me' }] })
      .mockResolvedValueOnce({ rows: [] })
    const res = await DELETE(req('DELETE', { author: 'me' }), ctx('N1'))
    expect(res.status).toBe(200)
    expect((await res.json()).success).toBe(true)
    const sqls = queryMock.mock.calls.map((c: any[]) => String(c[0]))
    // Note: SQL is multiline, so use [\s\S]* instead of the dotAll `s` flag
    // -- tsconfig targets ES2017, which rejects the `s` regex flag (TS1501).
    expect(sqls.some((s) => /UPDATE [\s\S]*notes[\s\S]*is_active = FALSE/i.test(s))).toBe(true)
  })
})
