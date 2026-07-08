import { afterEach, beforeEach, describe, expect, it, jest } from '@jest/globals'
import { fetchNotes, createNote, updateNote, deactivateNote } from '../noteApi'

const BASE = '/api/usd-swaps-tape-v2/notes'

describe('noteApi', () => {
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

  it('fetchNotes builds target query', async () => {
    fetchMock.mockResolvedValue(ok({ rows: [{ note_id: 'n1' }] }))
    const res = await fetchNotes('TRADE', 't1')
    expect(res.rows).toHaveLength(1)
    expect(String(fetchMock.mock.calls[0][0])).toBe(`${BASE}?target_type=TRADE&target_id=t1`)
  })

  it('createNote POSTs body and returns note_id', async () => {
    fetchMock.mockResolvedValue(ok({ success: true, note_id: 'n1' }))
    const res = await createNote({ target_type: 'PACKAGE', target_id: 'PKG1', author: 'chris', body: 'hi' })
    expect(res.note_id).toBe('n1')
    expect((fetchMock.mock.calls[0][1] as RequestInit).method).toBe('POST')
  })

  it('updateNote PATCHes base/[id]', async () => {
    fetchMock.mockResolvedValue(ok({ success: true }))
    await updateNote('n1', { body: 'edited', author: 'chris' })
    expect(String(fetchMock.mock.calls[0][0])).toBe(`${BASE}/n1`)
    expect((fetchMock.mock.calls[0][1] as RequestInit).method).toBe('PATCH')
  })

  it('deactivateNote DELETEs base/[id]', async () => {
    fetchMock.mockResolvedValue(ok({ success: true }))
    const res = await deactivateNote('n1', { author: 'chris' })
    expect(res.success).toBe(true)
    expect((fetchMock.mock.calls[0][1] as RequestInit).method).toBe('DELETE')
  })
})
