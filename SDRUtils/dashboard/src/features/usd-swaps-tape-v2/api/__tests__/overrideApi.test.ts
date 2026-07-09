import { afterEach, beforeEach, describe, expect, it, jest } from '@jest/globals'
import {
  createOverride,
  validateOverride,
  fetchOverrides,
  fetchOverrideDetail,
  updateOverride,
  deactivateOverride,
} from '../overrideApi'

const BASE = '/api/usd-swaps-tape-v2/overrides'

describe('overrideApi', () => {
  let originalFetch: typeof fetch
  let fetchMock: jest.Mock<any>
  beforeEach(() => {
    originalFetch = global.fetch
    fetchMock = jest.fn() as jest.Mock<any>
    ;(global as any).fetch = fetchMock
  })
  afterEach(() => {
    ;(global as any).fetch = originalFetch
  })

  const ok = (body: unknown) => ({ ok: true, status: 200, json: async () => body } as any)
  const fail = (status: number, body: unknown) =>
    ({ ok: false, status, json: async () => body } as any)

  it('createOverride POSTs to base and returns the success payload', async () => {
    fetchMock.mockResolvedValue(
      ok({ success: true, override_id: 'o1', manual_package_id: 'SMO-1', validation: [], metrics: {} }),
    )
    const res = await createOverride({
      override_type: 'GROUP',
      trade_ids: ['t1', 't2'],
      user: 'chris',
      admin_password: 'pw',
    })
    expect(res.override_id).toBe('o1')
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe(BASE)
    expect((init as RequestInit).method).toBe('POST')
    const sent = JSON.parse(String((init as RequestInit).body))
    expect(sent.validate_only).toBeUndefined()
    expect(sent.trade_ids).toEqual(['t1', 't2'])
  })

  it('validateOverride forces validate_only:true and returns validation+metrics+linked_trade_ids', async () => {
    fetchMock.mockResolvedValue(
      ok({ validation: [{ level: 'warning', code: 'X', message: 'm' }], metrics: {}, linked_trade_ids: ['t1'] }),
    )
    const res = await validateOverride({
      override_type: 'SPLIT',
      trade_ids: ['t1'],
      user: 'chris',
      admin_password: '',
    })
    expect(res.linked_trade_ids).toEqual(['t1'])
    const sent = JSON.parse(String((fetchMock.mock.calls[0][1] as RequestInit).body))
    expect(sent.validate_only).toBe(true)
  })

  it('createOverride surfaces the server error message on 403', async () => {
    fetchMock.mockResolvedValue(fail(403, { error: 'Invalid override password.' }))
    await expect(
      createOverride({ override_type: 'GROUP', trade_ids: ['t1', 't2'], user: 'c', admin_password: 'x' }),
    ).rejects.toThrow('Invalid override password.')
  })

  it('fetchOverrides builds a query string and returns rows', async () => {
    fetchMock.mockResolvedValue(ok({ rows: [{ override_id: 'o1' }] }))
    const res = await fetchOverrides({ is_active: true, created_by: 'chris', limit: 50 })
    expect(res.rows).toHaveLength(1)
    expect(String(fetchMock.mock.calls[0][0])).toBe(`${BASE}?is_active=true&created_by=chris&limit=50`)
  })

  it('fetchOverrideDetail GETs base/[id]', async () => {
    fetchMock.mockResolvedValue(ok({ override: { override_id: 'o1' }, members: [], history: [] }))
    const res = await fetchOverrideDetail('o1')
    expect(res.override.override_id).toBe('o1')
    expect(String(fetchMock.mock.calls[0][0])).toBe(`${BASE}/o1`)
  })

  it('updateOverride PATCHes base/[id]', async () => {
    fetchMock.mockResolvedValue(ok({ success: true, override_id: 'o1' }))
    await updateOverride('o1', { add_trades: ['t3'], user: 'c', admin_password: 'pw' })
    expect((fetchMock.mock.calls[0][1] as RequestInit).method).toBe('PATCH')
  })

  it('deactivateOverride DELETEs base/[id]', async () => {
    fetchMock.mockResolvedValue(ok({ success: true }))
    const res = await deactivateOverride('o1', { user: 'c', admin_password: 'pw' })
    expect(res.success).toBe(true)
    expect((fetchMock.mock.calls[0][1] as RequestInit).method).toBe('DELETE')
  })
})
