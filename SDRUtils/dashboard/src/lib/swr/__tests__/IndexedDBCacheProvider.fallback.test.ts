// Pin the in-memory fallback path: when indexedDB is unavailable
// (private browsing, older browsers) or when openDb() rejects,
// createIndexedDBCacheProvider returns a working provider backed
// only by an in-memory Map. A console.warn is emitted so the dev
// console shows the degraded state.
import { describe, expect, it, jest, beforeEach, afterEach } from '@jest/globals'

describe('IndexedDBCacheProvider fallback', () => {
  let originalIndexedDB: typeof indexedDB | undefined

  beforeEach(() => {
    originalIndexedDB = (global as unknown as { indexedDB?: typeof indexedDB })
      .indexedDB
  })

  afterEach(() => {
    if (originalIndexedDB === undefined) {
      delete (global as unknown as { indexedDB?: typeof indexedDB }).indexedDB
    } else {
      ;(global as unknown as { indexedDB?: typeof indexedDB }).indexedDB =
        originalIndexedDB
    }
  })

  it('falls back to in-memory provider when indexedDB is undefined', async () => {
    delete (global as unknown as { indexedDB?: typeof indexedDB }).indexedDB
    const warn = jest.spyOn(console, 'warn').mockImplementation(() => {})
    try {
      const { createIndexedDBCacheProvider } = await import('../IndexedDBCacheProvider')
      const provider = await createIndexedDBCacheProvider({
        maxEntries: 5,
        dbName: 'will-not-be-used',
      })
      // Round-trips work via in-memory shadow.
      provider.set('k', { v: 1 })
      expect(provider.get('k')).toEqual({ v: 1 })
      provider.delete('k')
      expect(provider.get('k')).toBeUndefined()
      // Warning surfaced.
      expect(warn).toHaveBeenCalledWith(
        expect.stringContaining('IndexedDBCacheProvider'),
      )
    } finally {
      warn.mockRestore()
    }
  })

  it('in-memory fallback honours maxEntries eviction', async () => {
    delete (global as unknown as { indexedDB?: typeof indexedDB }).indexedDB
    const warn = jest.spyOn(console, 'warn').mockImplementation(() => {})
    try {
      const { createIndexedDBCacheProvider } = await import('../IndexedDBCacheProvider')
      const provider = await createIndexedDBCacheProvider({
        maxEntries: 2,
        dbName: 'will-not-be-used',
      })
      provider.set('a', 1)
      provider.set('b', 2)
      provider.set('c', 3)
      expect(provider.get('a')).toBeUndefined()
      expect(provider.get('b')).toBe(2)
      expect(provider.get('c')).toBe(3)
    } finally {
      warn.mockRestore()
    }
  })
})
