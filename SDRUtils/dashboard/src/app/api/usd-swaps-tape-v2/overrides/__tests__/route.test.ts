import { describe, expect, it, jest, beforeAll, beforeEach } from '@jest/globals'

// Typed per the precedent in src/lib/__tests__/tape-overrides.test.ts: an
// untyped jest.fn() here infers a `never` parameter type from jest's
// UnknownFunction default, which tsc rejects once mockResolvedValue /
// mockImplementation are called with concrete row shapes below.
const queryMock = jest.fn<(sql: string, params?: unknown[]) => Promise<{ rows: unknown[] }>>(
  async () => ({ rows: [] as unknown[] }),
)
const clientQueryMock = jest.fn<(sql: string, params?: unknown[]) => Promise<{ rows: unknown[] }>>(
  async () => ({ rows: [] as unknown[] }),
)
const withClientMock = jest.fn(async (fn: any) => fn({ query: clientQueryMock }))
jest.unstable_mockModule('@/lib/db', () => ({
  query: queryMock,
  withClient: withClientMock,
}))

let POST: any
let GET: any
beforeAll(async () => {
  const mod = await import('../route')
  POST = mod.POST
  GET = mod.GET
})

function post(body: unknown): Request {
  return new Request('http://t/api/usd-swaps-tape-v2/overrides', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  })
}

beforeEach(() => {
  process.env.TAPE_OVERRIDE_PASSWORD = 'pw'
  queryMock.mockReset()
  clientQueryMock.mockReset()
  withClientMock.mockClear()
  // Default: legs lookup returns two legs in one package.
  queryMock.mockResolvedValue({ rows: [
    { trade_id: 'T1', package_id: 'P1' },
    { trade_id: 'T2', package_id: 'P1' },
  ] })
  // Route the transactional statements by SQL text.
  clientQueryMock.mockImplementation(async (sql: string) => {
    if (/^\s*BEGIN/i.test(sql) || /^\s*COMMIT/i.test(sql) || /^\s*ROLLBACK/i.test(sql)) return { rows: [] }
    if (/SELECT 1 FROM .*overrides/i.test(sql)) return { rows: [] } // pkg id free
    if (/INSERT INTO .*overrides/i.test(sql)) {
      return { rows: [{ override_id: 'NEW-OID', manual_package_id: 'SMO-20260708-AAAA1111' }] }
    }
    if (/SELECT override_id FROM .*overrides/i.test(sql)) return { rows: [] } // no overlap
    return { rows: [] }
  })
})

describe('POST /overrides', () => {
  it('400 on invalid JSON', async () => {
    const bad = new Request('http://t/api/usd-swaps-tape-v2/overrides', { method: 'POST', body: '{' })
    expect((await POST(bad)).status).toBe(400)
  })
  it('400 on bad override_type', async () => {
    const res = await POST(post({ override_type: 'MERGE', trade_ids: ['T1', 'T2'], user: 'u', admin_password: 'pw' }))
    expect(res.status).toBe(400)
  })
  it('validate_only returns validation/metrics/linked_trade_ids and never writes', async () => {
    const res = await POST(post({ override_type: 'GROUP', trade_ids: 'T1,T2', validate_only: true }))
    expect(res.status).toBe(200)
    const body = await res.json()
    expect(body.linked_trade_ids).toEqual(['T1', 'T2'])
    expect(body.metrics.trade_count).toBe(2)
    expect(Array.isArray(body.validation)).toBe(true)
    expect(withClientMock).not.toHaveBeenCalled()
  })
  it('409 when validation fails (GROUP with one trade)', async () => {
    queryMock.mockResolvedValueOnce({ rows: [{ trade_id: 'T1', package_id: 'P1' }] })
    const res = await POST(post({ override_type: 'GROUP', trade_ids: ['T1'], user: 'u', admin_password: 'pw' }))
    expect(res.status).toBe(409)
  })
  it('403 with the fixed error when password is wrong', async () => {
    const res = await POST(post({ override_type: 'GROUP', trade_ids: ['T1', 'T2'], user: 'u', admin_password: 'bad' }))
    expect(res.status).toBe(403)
    expect((await res.json()).error).toBe('Invalid override password.')
  })
  it('creates transactionally and returns override_id + manual_package_id', async () => {
    const res = await POST(post({ override_type: 'GROUP', trade_ids: ['T1', 'T2'], reason: 'test', user: 'u', admin_password: 'pw' }))
    expect(res.status).toBe(200)
    const body = await res.json()
    expect(body.success).toBe(true)
    expect(body.override_id).toBe('NEW-OID')
    expect(body.manual_package_id).toBe('SMO-20260708-AAAA1111')
    const sqls = clientQueryMock.mock.calls.map((c: any[]) => String(c[0]))
    expect(sqls.some((s: string) => /^\s*BEGIN/i.test(s))).toBe(true)
    expect(sqls.some((s: string) => /INSERT INTO .*override_members/i.test(s))).toBe(true)
    expect(sqls.some((s: string) => /INSERT INTO .*override_history/i.test(s) && /CREATED/i.test(s) === false)).toBe(true)
    expect(sqls.some((s: string) => /^\s*COMMIT/i.test(s))).toBe(true)
  })
  it('supersession invariant: overlapping active members are deactivated before new insert', async () => {
    const order: string[] = []
    clientQueryMock.mockImplementation(async (sql: string) => {
      if (/SELECT override_id FROM .*overrides/i.test(sql)) return { rows: [{ override_id: 'OLD' }] }
      if (/INSERT INTO .*overrides/i.test(sql)) return { rows: [{ override_id: 'NEW-OID', manual_package_id: 'SMO-X' }] }
      if (/SELECT 1 FROM .*overrides/i.test(sql)) return { rows: [] }
      // Table name carries a "_v2" suffix directly after "override_members", so
      // match loosely across the statement rather than requiring immediate
      // whitespace after the bare "override_members" token.
      if (/UPDATE\s+\S*override_members\S*[\s\S]*SET is_active = FALSE/i.test(sql)) order.push('deactivate-members')
      if (/INSERT INTO .*override_members/i.test(sql)) order.push('insert-members')
      return { rows: [] }
    })
    await POST(post({ override_type: 'GROUP', trade_ids: ['T1', 'T2'], user: 'u', admin_password: 'pw' }))
    expect(order).toEqual(['deactivate-members', 'insert-members'])
  })
  it('rolls back and 500s when a write throws', async () => {
    clientQueryMock.mockImplementation(async (sql: string) => {
      if (/INSERT INTO .*override_members/i.test(sql)) throw new Error('boom')
      if (/INSERT INTO .*overrides/i.test(sql)) return { rows: [{ override_id: 'NEW-OID', manual_package_id: 'X' }] }
      return { rows: [] }
    })
    const res = await POST(post({ override_type: 'GROUP', trade_ids: ['T1', 'T2'], user: 'u', admin_password: 'pw' }))
    expect(res.status).toBe(500)
    expect(clientQueryMock.mock.calls.map((c: any[]) => String(c[0])).some((s) => /^\s*ROLLBACK/i.test(s))).toBe(true)
  })
})

describe('GET /overrides', () => {
  it('lists with filters and returns { rows }', async () => {
    queryMock.mockReset()
    queryMock.mockResolvedValueOnce({ rows: [{ override_id: 'A' }] })
    const res = await GET(new Request('http://t/api/usd-swaps-tape-v2/overrides?is_active=true&created_by=u&limit=10'))
    expect(res.status).toBe(200)
    expect((await res.json()).rows).toEqual([{ override_id: 'A' }])
  })
})
