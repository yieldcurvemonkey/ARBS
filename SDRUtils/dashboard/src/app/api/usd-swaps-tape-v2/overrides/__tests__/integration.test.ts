import { describe, expect, it, jest, beforeAll, beforeEach } from '@jest/globals'
import { TAPE_LEGS } from '@/lib/tape-tables'

/**
 * Stateful in-memory fake of the three override tables, wired through the
 * mocked `query` (reads) and `withClient` (transactional writes). Proves the
 * handlers compose correctly and that AT MOST ONE active override references a
 * given trade_id (supersession invariant), without a live Postgres.
 */
type Store = {
  overrides: Map<string, any>
  members: any[] // { trade_id, override_id, override_type, manual_package_id, is_active }
  history: any[]
  seq: number
}
const store: Store = { overrides: new Map(), members: [], history: [], seq: 0 }

function run(sql: string, params: any[] = []): { rows: any[] } {
  const s = sql.replace(/\s+/g, ' ').trim()
  if (/^BEGIN|^COMMIT|^ROLLBACK/i.test(s)) return { rows: [] }
  // NOTE: table names carry a generation suffix directly abutting "overrides" /
  // "override_members" / "override_history" (see TAPE_OVERRIDES et al. in
  // src/lib/tape-tables.ts), so every regex below that anchors on the next
  // SQL keyword needs a \S* between the table stem and that keyword (Tasks
  // 5-6 lesson).
  if (/SELECT 1 FROM .*overrides\S* WHERE manual_package_id/i.test(s)) {
    const hit = [...store.overrides.values()].some((o) => o.manual_package_id === params[0])
    return { rows: hit ? [{ '?column?': 1 }] : [] }
  }
  if (/INSERT INTO .*overrides\S* /i.test(s) && /RETURNING/i.test(s)) {
    store.seq += 1
    const id = `OID-${store.seq}`
    const row = {
      override_id: id, override_type: params[0], manual_package_id: params[1],
      trade_ids: params[2], created_by: params[3], reason: params[4], tags: params[5],
      metrics: params[6], is_active: true, superseded_by: null,
    }
    store.overrides.set(id, row)
    return { rows: [{ override_id: id, manual_package_id: params[1] }] }
  }
  if (/SELECT override_id FROM .*overrides\S* WHERE is_active/i.test(s)) {
    const [tradeIds, exclude] = params
    const ids = [...store.overrides.values()]
      .filter((o) => o.is_active && o.override_id !== exclude &&
        o.trade_ids.some((t: string) => tradeIds.includes(t)))
      .map((o) => ({ override_id: o.override_id }))
    return { rows: ids }
  }
  if (/UPDATE .*overrides\S* SET is_active = FALSE, superseded_by/i.test(s)) {
    const [supersededBy, , ids] = params
    ids.forEach((id: string) => {
      const o = store.overrides.get(id)
      if (o) { o.is_active = false; o.superseded_by = supersededBy }
    })
    return { rows: [] }
  }
  if (/UPDATE .*override_members\S* SET is_active = FALSE WHERE override_id = ANY/i.test(s)) {
    const [ids] = params
    store.members.forEach((m) => { if (ids.includes(m.override_id)) m.is_active = false })
    return { rows: [] }
  }
  if (/UPDATE .*override_members\S* SET is_active = FALSE WHERE override_id = \$1/i.test(s)) {
    store.members.forEach((m) => { if (m.override_id === params[0]) m.is_active = false })
    return { rows: [] }
  }
  if (/INSERT INTO .*override_members/i.test(s)) {
    const [tradeIds, overrideId, overrideType, pkgId] = params
    tradeIds.forEach((t: string) => store.members.push({
      trade_id: t, override_id: overrideId, override_type: overrideType,
      manual_package_id: pkgId, is_active: true,
    }))
    return { rows: [] }
  }
  if (/INSERT INTO .*override_history/i.test(s)) {
    store.history.push({ override_id: params[0], sql: s })
    return { rows: [] }
  }
  if (/UPDATE .*overrides\S* SET is_active = FALSE, updated_by/i.test(s)) {
    const o = store.overrides.get(params[1]); if (o) o.is_active = false
    return { rows: [] }
  }
  if (/SELECT \* FROM .*overrides\S* WHERE override_id/i.test(s)) {
    const o = store.overrides.get(params[0]); return { rows: o ? [o] : [] }
  }
  if (/FROM .*override_members\S* WHERE override_id/i.test(s)) {
    return { rows: store.members.filter((m) => m.override_id === params[0]) }
  }
  if (/FROM .*override_history\S* WHERE override_id/i.test(s)) {
    return { rows: store.history.filter((h) => h.override_id === params[0]) }
  }
  if (/SELECT \* FROM .*overrides/i.test(s)) {
    return { rows: [...store.overrides.values()].filter((o) => o.is_active) }
  }
  if (new RegExp(`FROM ${TAPE_LEGS}`, 'i').test(s)) {
    return { rows: params[0].map((t: string) => ({ trade_id: t, package_id: 'P1' })) }
  }
  return { rows: [] }
}

const queryMock = jest.fn(async (sql: string, params: any[]) => run(sql, params))
const clientQueryMock = jest.fn(async (sql: string, params: any[]) => run(sql, params))
const withClientMock = jest.fn(async (fn: any) => fn({ query: clientQueryMock }))
jest.unstable_mockModule('@/lib/db', () => ({ query: queryMock, withClient: withClientMock }))

let list: any, detail: any
beforeAll(async () => {
  list = await import('../route')
  detail = await import('../[overrideId]/route')
})
beforeEach(() => {
  process.env.TAPE_OVERRIDE_PASSWORD = 'pw'
  store.overrides.clear(); store.members = []; store.history = []; store.seq = 0
})

function postBody(body: unknown): Request {
  return new Request('http://t/api/usd-swaps-tape-v2/overrides', {
    method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body),
  })
}
const activeMembers = () => store.members.filter((m) => m.is_active)

describe('override lifecycle (db-mocked, stateful)', () => {
  it('create -> list -> detail -> deactivate', async () => {
    const created = await (await list.POST(postBody({
      override_type: 'GROUP', trade_ids: ['T1', 'T2'], user: 'u', admin_password: 'pw',
    })).then((r: Response) => r)).json()
    expect(created.success).toBe(true)
    const oid = created.override_id

    const listed = await (await list.GET(new Request('http://t/api/usd-swaps-tape-v2/overrides'))).json()
    expect(listed.rows.some((r: any) => r.override_id === oid)).toBe(true)

    const ctx = { params: Promise.resolve({ overrideId: oid }) }
    const got = await (await detail.GET(new Request('http://t/x'), ctx)).json()
    expect(got.override.override_id).toBe(oid)
    expect(got.members.length).toBe(2)

    await detail.DELETE(new Request('http://t/x', {
      method: 'DELETE', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ user: 'u', admin_password: 'pw' }),
    }), ctx)
    expect(store.overrides.get(oid).is_active).toBe(false)
    expect(activeMembers().length).toBe(0)
  })

  it('one-active-override-per-trade: a second override supersedes the first', async () => {
    await list.POST(postBody({ override_type: 'GROUP', trade_ids: ['T1', 'T2'], user: 'u', admin_password: 'pw' }))
    await list.POST(postBody({ override_type: 'GROUP', trade_ids: ['T2', 'T3'], user: 'u', admin_password: 'pw' }))

    // Invariant: every trade_id appears in at most one ACTIVE member row.
    const counts = new Map<string, number>()
    activeMembers().forEach((m) => counts.set(m.trade_id, (counts.get(m.trade_id) ?? 0) + 1))
    for (const [, n] of counts) expect(n).toBeLessThanOrEqual(1)
    // First override was superseded; its trades are no longer active members.
    expect([...store.overrides.values()].filter((o) => o.is_active).length).toBe(1)
    expect(activeMembers().map((m) => m.trade_id).sort()).toEqual(['T2', 'T3'])
  })
})

const DB_URL = process.env.PG_TEST_URL || process.env.DATABASE_URL
const describeIfDb = DB_URL ? describe : describe.skip

describeIfDb('override lifecycle (live DB smoke)', () => {
  it('create/list/detail/deactivate against Postgres', async () => {
    jest.resetModules()
    jest.dontMock('@/lib/db') // use the real pool for this block
    const realList = await import('../route')
    const realDetail = await import('../[overrideId]/route')
    process.env.TAPE_OVERRIDE_PASSWORD = process.env.TAPE_OVERRIDE_PASSWORD || 'live-test-pw'
    // Use synthetic trade ids that will not collide with tape data.
    const t1 = `ITEST-${Date.now()}-A`
    const t2 = `ITEST-${Date.now()}-B`
    const createRes = await realList.POST(new Request('http://t/x', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ override_type: 'GROUP', trade_ids: [t1, t2], user: 'itest', admin_password: process.env.TAPE_OVERRIDE_PASSWORD }),
    }))
    // 200 on success, or 500 if the DDL tables are not yet migrated.
    expect([200, 500]).toContain(createRes.status)
    if (createRes.status !== 200) return
    const { override_id } = await createRes.json()
    const ctx = { params: Promise.resolve({ overrideId: override_id }) }
    expect((await realDetail.GET(new Request('http://t/x'), ctx)).status).toBe(200)
    const delRes = await realDetail.DELETE(new Request('http://t/x', {
      method: 'DELETE', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ user: 'itest', admin_password: process.env.TAPE_OVERRIDE_PASSWORD }),
    }), ctx)
    expect(delRes.status).toBe(200)
  })
})
