import { describe, expect, it, jest, beforeAll, beforeEach } from '@jest/globals'

// Typed per the precedent in src/lib/__tests__/tape-overrides.test.ts and
// overrides/__tests__/route.test.ts: an untyped jest.fn() here infers a
// `never` parameter type from jest's UnknownFunction default, which tsc
// rejects once mockResolvedValue* / mockImplementation are called with
// concrete row shapes below.
const queryMock = jest.fn<(sql: string, params?: unknown[]) => Promise<{ rows: unknown[] }>>(
  async () => ({ rows: [] as unknown[] }),
)
// rowCount is optional (mirrors pg's QueryResult) so existing `{ rows: [] }`
// mocks stay valid; the active-guard test below sets it explicitly to 0 to
// simulate the parent UPDATE's WHERE ... AND is_active = TRUE matching no
// rows (a concurrent DELETE deactivated the override mid-PATCH).
const clientQueryMock = jest.fn<
  (sql: string, params?: unknown[]) => Promise<{ rows: unknown[]; rowCount?: number | null }>
>(async () => ({ rows: [] as unknown[] }))
const withClientMock = jest.fn(async (fn: any) => fn({ query: clientQueryMock }))
jest.unstable_mockModule('@/lib/db', () => ({ query: queryMock, withClient: withClientMock }))

let GET: any, PATCH: any, DELETE: any
beforeAll(async () => {
  const mod = await import('../route')
  GET = mod.GET; PATCH = mod.PATCH; DELETE = mod.DELETE
})

const ctx = (id: string) => ({ params: Promise.resolve({ overrideId: id }) })
function req(method: string, body?: unknown): Request {
  return new Request('http://t/api/usd-swaps-tape-v2/overrides/OID', {
    method,
    headers: { 'content-type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
}

beforeEach(() => {
  process.env.TAPE_OVERRIDE_PASSWORD = 'pw'
  queryMock.mockReset(); clientQueryMock.mockReset(); withClientMock.mockClear()
  clientQueryMock.mockResolvedValue({ rows: [] })
})

describe('GET /overrides/[overrideId]', () => {
  it('404 when override missing', async () => {
    queryMock.mockResolvedValueOnce({ rows: [] })
    const res = await GET(req('GET'), ctx('OID'))
    expect(res.status).toBe(404)
  })
  it('returns { override, members, history } with history rows carrying override_id', async () => {
    queryMock
      .mockResolvedValueOnce({ rows: [{ override_id: 'OID', trade_ids: ['T1', 'T2'], override_type: 'GROUP', manual_package_id: 'SMO-X' }] })
      .mockResolvedValueOnce({ rows: [{ trade_id: 'T1' }, { trade_id: 'T2' }] })
      .mockResolvedValueOnce({ rows: [{ history_id: 1, override_id: 'OID', action: 'CREATED' }] })
    const res = await GET(req('GET'), ctx('OID'))
    expect(res.status).toBe(200)
    const body = await res.json()
    expect(body.override.override_id).toBe('OID')
    expect(body.members.length).toBe(2)
    expect(body.history.length).toBe(1)
    expect(body.history[0].override_id).toBe('OID')
    // The history SELECT must request override_id explicitly -- omitting it
    // left OverrideHistoryRow.override_id (typed `string`) undefined at
    // runtime. Assert the actual query text, not just the mocked payload.
    const historySql = String(queryMock.mock.calls[2]?.[0])
    expect(historySql).toMatch(/SELECT[\s\S]*override_id[\s\S]*FROM\s+\S*override_history\S*/i)
  })
})

describe('PATCH /overrides/[overrideId]', () => {
  it('403 on bad password', async () => {
    const res = await PATCH(req('PATCH', { user: 'u', admin_password: 'bad' }), ctx('OID'))
    expect(res.status).toBe(403)
  })
  it('404 when override missing', async () => {
    queryMock.mockResolvedValueOnce({ rows: [] })
    const res = await PATCH(req('PATCH', { user: 'u', admin_password: 'pw', add_trades: ['T3'] }), ctx('OID'))
    expect(res.status).toBe(404)
  })
  it('recomputes set, updates parent + members in a txn', async () => {
    queryMock
      .mockResolvedValueOnce({ rows: [{ override_id: 'OID', override_type: 'GROUP', trade_ids: ['T1', 'T2'], manual_package_id: 'SMO-X' }] }) // existing
      .mockResolvedValueOnce({ rows: [{ trade_id: 'T1', package_id: 'P1' }, { trade_id: 'T2', package_id: 'P1' }, { trade_id: 'T3', package_id: 'P2' }] }) // legs
    clientQueryMock.mockImplementation(async (sql: string) => {
      if (/SELECT override_id FROM .*overrides/i.test(sql)) return { rows: [] }
      return { rows: [] }
    })
    const res = await PATCH(req('PATCH', { user: 'u', admin_password: 'pw', add_trades: ['T3'], reason: 'grew' }), ctx('OID'))
    expect(res.status).toBe(200)
    const body = await res.json()
    expect(body.success).toBe(true)
    const sqls = clientQueryMock.mock.calls.map((c: any[]) => String(c[0]))
    // Table name carries a "_v2" suffix directly abutting "overrides", so a
    // regex requiring \s+ immediately after the literal "overrides" would
    // not match "overrides_v2\n   SET ..." (see Task 5 precedent).
    expect(sqls.some((s) => /UPDATE\s+\S*overrides\S*[\s\S]*SET/i.test(s))).toBe(true)
    expect(sqls.some((s) => /INSERT INTO .*override_members/i.test(s))).toBe(true)
    expect(sqls.some((s) => /INSERT INTO .*override_history/i.test(s))).toBe(true)
    expect(sqls.some((s) => /^\s*COMMIT/i.test(s))).toBe(true)
  })
  it('409s and does not resurrect when the parent UPDATE active-guard hits zero rows (concurrent DELETE race)', async () => {
    queryMock
      .mockResolvedValueOnce({ rows: [{ override_id: 'OID', override_type: 'GROUP', trade_ids: ['T1', 'T2'], manual_package_id: 'SMO-X' }] }) // existing (still active at the pre-txn read)
      .mockResolvedValueOnce({ rows: [{ trade_id: 'T1', package_id: 'P1' }, { trade_id: 'T2', package_id: 'P1' }, { trade_id: 'T3', package_id: 'P2' }] }) // legs
    clientQueryMock.mockImplementation(async (sql: string) => {
      // Real _v2 table name (arbs_usd_swap_tape_overrides_v2): the parent-row
      // rewrite is the only statement whose SET list resurrects
      // (`is_active = TRUE,`) -- distinguish it from the member-deactivate
      // and supersede statements, which set is_active = FALSE.
      if (/UPDATE\s+\S*overrides\S*[\s\S]*is_active = TRUE,/i.test(sql)) {
        return { rows: [], rowCount: 0 }
      }
      return { rows: [] }
    })
    const res = await PATCH(req('PATCH', { user: 'u', admin_password: 'pw', add_trades: ['T3'], reason: 'grew' }), ctx('OID'))
    expect(res.status).toBe(409)
    const body = await res.json()
    expect(body.error).toBe('Override is not active.')
    const sqls = clientQueryMock.mock.calls.map((c: any[]) => String(c[0]))
    // Member-rewrite (the new-set INSERT) and COMMIT must NOT proceed past
    // the active-guard throw; the transaction must ROLLBACK instead.
    expect(sqls.some((s) => /INSERT INTO .*override_members/i.test(s))).toBe(false)
    expect(sqls.some((s) => /^\s*COMMIT/i.test(s))).toBe(false)
    expect(sqls.some((s) => /^\s*ROLLBACK/i.test(s))).toBe(true)
  })
})

describe('DELETE /overrides/[overrideId]', () => {
  it('403 on bad password', async () => {
    const res = await DELETE(req('DELETE', { user: 'u', admin_password: 'bad' }), ctx('OID'))
    expect(res.status).toBe(403)
  })
  it('404 when override missing', async () => {
    queryMock.mockResolvedValueOnce({ rows: [] })
    const res = await DELETE(req('DELETE', { user: 'u', admin_password: 'pw' }), ctx('OID'))
    expect(res.status).toBe(404)
  })
  it('soft-deactivates parent + members and returns success', async () => {
    queryMock.mockResolvedValueOnce({ rows: [{ override_id: 'OID', trade_ids: ['T1'] }] })
    const res = await DELETE(req('DELETE', { user: 'u', admin_password: 'pw', reason: 'oops' }), ctx('OID'))
    expect(res.status).toBe(200)
    expect((await res.json()).success).toBe(true)
    const sqls = clientQueryMock.mock.calls.map((c: any[]) => String(c[0]))
    expect(sqls.some((s) => /UPDATE\s+\S*overrides\S*\s+SET is_active = FALSE/i.test(s))).toBe(true)
    expect(sqls.some((s) => /UPDATE\s+\S*override_members\S*\s+SET is_active = FALSE/i.test(s))).toBe(true)
    expect(sqls.some((s) => /DEACTIVATED/i.test(s) || /override_history/i.test(s))).toBe(true)
  })
})
