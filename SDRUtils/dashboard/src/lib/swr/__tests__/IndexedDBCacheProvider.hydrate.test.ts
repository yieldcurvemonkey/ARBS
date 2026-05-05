// Pin the hydrate-on-mount behaviour: a second provider instance
// pointing at the same IDB DB sees entries set by the first.
// Mirrors the dev-server behaviour of "open dashboard, hard reload,
// rows render instantly from cache".
import 'fake-indexeddb/auto'
import { describe, expect, it } from '@jest/globals'
import { createIndexedDBCacheProvider } from '../IndexedDBCacheProvider'

let dbCounter = 0
function uniqueDbName(): string {
  return `arbs-swr-cache-hydrate-test-${++dbCounter}`
}

async function flush(): Promise<void> {
  await new Promise((r) => setTimeout(r, 50))
}

describe('IndexedDBCacheProvider hydrate-on-remount', () => {
  it('hydrates persisted entries on re-create (close + reopen)', async () => {
    const dbName = uniqueDbName()

    const a = (await createIndexedDBCacheProvider({
      maxEntries: 10,
      dbName,
    })) as ReturnType<typeof createIndexedDBCacheProvider> extends Promise<
      infer P
    >
      ? P & { _closeForTesting?: () => void }
      : never

    a.set('key', { data: 'value' })
    a.set('other', 42)
    await flush()
    a._closeForTesting?.()

    const b = await createIndexedDBCacheProvider({ maxEntries: 10, dbName })
    expect(b.get('key')).toEqual({ data: 'value' })
    expect(b.get('other')).toBe(42)
  })

  it('hydrate preserves insertion order (oldest first)', async () => {
    const dbName = uniqueDbName()

    const a = (await createIndexedDBCacheProvider({
      maxEntries: 5,
      dbName,
    })) as ReturnType<typeof createIndexedDBCacheProvider> extends Promise<
      infer P
    >
      ? P & { _closeForTesting?: () => void }
      : never
    a.set('first', 1)
    await flush()
    a.set('second', 2)
    await flush()
    a.set('third', 3)
    await flush()
    a._closeForTesting?.()

    // Re-mount with a tighter maxEntries to force eviction; the oldest
    // entries should evict first.
    const b = (await createIndexedDBCacheProvider({
      maxEntries: 2,
      dbName,
    })) as ReturnType<typeof createIndexedDBCacheProvider> extends Promise<
      infer P
    >
      ? P & { _closeForTesting?: () => void }
      : never
    // After hydrate: order = [first, second, third]; maxEntries=2 so
    // 'first' should be evicted on the next set.
    b.set('fourth', 4)
    expect(b.get('first')).toBeUndefined()
    // After this set, only the 2 most recent (third, fourth) survive.
    expect(b.get('third')).toBe(3)
    expect(b.get('fourth')).toBe(4)
  })
})
