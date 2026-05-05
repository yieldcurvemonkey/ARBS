import 'fake-indexeddb/auto'
import { describe, expect, it } from '@jest/globals'
import { createIndexedDBCacheProvider } from '../IndexedDBCacheProvider'

let dbCounter = 0
function uniqueDbName(): string {
  return `arbs-swr-cache-test-${++dbCounter}`
}

async function flush(): Promise<void> {
  // Let pending IDB transactions drain.
  await new Promise((r) => setTimeout(r, 50))
}

describe('IndexedDBCacheProvider', () => {
  it('round-trips set/get/delete', async () => {
    const provider = await createIndexedDBCacheProvider({
      maxEntries: 200,
      dbName: uniqueDbName(),
    })
    provider.set('k', { foo: 'bar' })
    expect(provider.get('k')).toEqual({ foo: 'bar' })
    provider.delete('k')
    expect(provider.get('k')).toBeUndefined()
  })

  it('persists across re-creates', async () => {
    const dbName = uniqueDbName()
    const a = await createIndexedDBCacheProvider({
      maxEntries: 200,
      dbName,
    }) as ReturnType<typeof createIndexedDBCacheProvider> extends Promise<infer P>
      ? P & { _closeForTesting?: () => void }
      : never
    a.set('k', { v: 1 })
    await flush()
    a._closeForTesting?.()

    const b = await createIndexedDBCacheProvider({
      maxEntries: 200,
      dbName,
    })
    expect(b.get('k')).toEqual({ v: 1 })
  })

  it('evicts oldest when over maxEntries', async () => {
    const provider = await createIndexedDBCacheProvider({
      maxEntries: 2,
      dbName: uniqueDbName(),
    })
    provider.set('a', 1)
    provider.set('b', 2)
    provider.set('c', 3)
    expect(provider.get('a')).toBeUndefined()
    expect(provider.get('b')).toBe(2)
    expect(provider.get('c')).toBe(3)
  })

  it('exposes keys() and clear()', async () => {
    const provider = await createIndexedDBCacheProvider({
      maxEntries: 10,
      dbName: uniqueDbName(),
    })
    provider.set('x', 1)
    provider.set('y', 2)
    expect([...provider.keys()].sort()).toEqual(['x', 'y'])
    provider.clear()
    expect([...provider.keys()]).toEqual([])
  })

  it('Symbol.iterator yields key/value entries', async () => {
    const provider = await createIndexedDBCacheProvider({
      maxEntries: 10,
      dbName: uniqueDbName(),
    })
    provider.set('a', 1)
    provider.set('b', 2)
    const entries = [...provider]
    expect(
      entries.sort((a, b) => String(a[0]).localeCompare(String(b[0]))),
    ).toEqual([
      ['a', 1],
      ['b', 2],
    ])
  })

  it('overwriting an existing key promotes it to most-recent', async () => {
    const provider = await createIndexedDBCacheProvider({
      maxEntries: 2,
      dbName: uniqueDbName(),
    })
    provider.set('a', 1)
    provider.set('b', 2)
    provider.set('a', 11) // promotes 'a'
    provider.set('c', 3) // should evict 'b' (now LRU)
    expect(provider.get('a')).toBe(11)
    expect(provider.get('b')).toBeUndefined()
    expect(provider.get('c')).toBe(3)
  })
})
