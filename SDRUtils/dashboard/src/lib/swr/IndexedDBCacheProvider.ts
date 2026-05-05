// ABOUTME: SWR cache provider backed by IndexedDB. Keeps an in-memory
// shadow Map for synchronous reads (SWR requires sync get); persists
// asynchronously in the background. Evicts oldest entries beyond
// maxEntries via a per-set insertion-order list.
//
// Falls back to in-memory-only mode when IndexedDB is unavailable
// (e.g. private-browsing or older browsers) so callers don't need to
// branch on environment.

interface PersistedEntry {
  key: string
  value: unknown
  ts: number
}

export interface IndexedDBCacheProviderOptions {
  maxEntries: number
  /** Override the default DB name. Useful for tests. */
  dbName?: string
}

export interface IndexedDBCacheProvider {
  get: (key: string) => unknown
  set: (key: string, value: unknown) => void
  delete: (key: string) => void
  clear: () => void
  keys: () => IterableIterator<string>
  [Symbol.iterator]: () => IterableIterator<[string, unknown]>
}

const DEFAULT_DB_NAME = 'arbs-swr-cache'
const STORE = 'entries'

function isIndexedDbAvailable(): boolean {
  return (
    typeof indexedDB !== 'undefined' &&
    typeof indexedDB.open === 'function'
  )
}

async function openDb(dbName: string): Promise<IDBDatabase> {
  return new Promise((res, rej) => {
    const req = indexedDB.open(dbName, 1)
    req.onupgradeneeded = () => {
      req.result.createObjectStore(STORE, { keyPath: 'key' })
    }
    req.onsuccess = () => res(req.result)
    req.onerror = () => rej(req.error)
  })
}

async function loadAll(db: IDBDatabase): Promise<PersistedEntry[]> {
  return new Promise((res, rej) => {
    const tx = db.transaction(STORE, 'readonly')
    const req = tx.objectStore(STORE).getAll()
    req.onsuccess = () => res(req.result as PersistedEntry[])
    req.onerror = () => rej(req.error)
  })
}

function inMemoryProvider(maxEntries: number): IndexedDBCacheProvider {
  const memory = new Map<string, unknown>()
  const order: string[] = []
  return {
    get: (key) => memory.get(key),
    set: (key, value) => {
      if (memory.has(key)) {
        const idx = order.indexOf(key)
        if (idx >= 0) order.splice(idx, 1)
      }
      memory.set(key, value)
      order.push(key)
      while (order.length > maxEntries) {
        const oldest = order.shift()!
        memory.delete(oldest)
      }
    },
    delete: (key) => {
      memory.delete(key)
      const idx = order.indexOf(key)
      if (idx >= 0) order.splice(idx, 1)
    },
    clear: () => {
      memory.clear()
      order.length = 0
    },
    keys: () => memory.keys(),
    [Symbol.iterator]: () => memory.entries(),
  }
}

export async function createIndexedDBCacheProvider(
  opts: IndexedDBCacheProviderOptions,
): Promise<IndexedDBCacheProvider> {
  if (!isIndexedDbAvailable()) {
    if (typeof console !== 'undefined' && console.warn) {
      console.warn(
        'IndexedDBCacheProvider: indexedDB unavailable; falling back to in-memory cache',
      )
    }
    return inMemoryProvider(opts.maxEntries)
  }

  let db: IDBDatabase
  try {
    db = await openDb(opts.dbName ?? DEFAULT_DB_NAME)
  } catch (err) {
    if (typeof console !== 'undefined' && console.warn) {
      console.warn(
        'IndexedDBCacheProvider: failed to open IDB; falling back to in-memory cache',
        err,
      )
    }
    return inMemoryProvider(opts.maxEntries)
  }

  const memory = new Map<string, unknown>()
  const order: string[] = []

  // Hydrate from disk. Sort by ts ascending so the in-memory order
  // matches insertion order; entries with no ts (from older versions)
  // get pushed to the front and evicted first.
  const persisted = await loadAll(db)
  persisted.sort((a, b) => (a.ts ?? 0) - (b.ts ?? 0))
  for (const e of persisted) {
    memory.set(e.key, e.value)
    order.push(e.key)
  }

  const persist = (key: string, value: unknown) => {
    try {
      const tx = db.transaction(STORE, 'readwrite')
      tx.objectStore(STORE).put({ key, value, ts: Date.now() })
    } catch {
      // Quota / closed-db errors silently swallow — in-memory shadow
      // remains correct, and the next mount will skip the missing entry.
    }
  }

  const drop = (key: string) => {
    try {
      const tx = db.transaction(STORE, 'readwrite')
      tx.objectStore(STORE).delete(key)
    } catch {
      // see above
    }
  }

  return {
    get: (key) => memory.get(key),
    set: (key, value) => {
      if (memory.has(key)) {
        const idx = order.indexOf(key)
        if (idx >= 0) order.splice(idx, 1)
      }
      memory.set(key, value)
      order.push(key)
      persist(key, value)
      while (order.length > opts.maxEntries) {
        const oldest = order.shift()!
        memory.delete(oldest)
        drop(oldest)
      }
    },
    delete: (key) => {
      memory.delete(key)
      const idx = order.indexOf(key)
      if (idx >= 0) order.splice(idx, 1)
      drop(key)
    },
    clear: () => {
      memory.clear()
      order.length = 0
      try {
        const tx = db.transaction(STORE, 'readwrite')
        tx.objectStore(STORE).clear()
      } catch {
        // see persist
      }
    },
    keys: () => memory.keys(),
    [Symbol.iterator]: () => memory.entries(),
    /**
     * Test helper — close the underlying IDBDatabase. Production code
     * never calls this; tests use it between fixtures so deleteDatabase
     * doesn't block on an open connection.
     */
    _closeForTesting: () => {
      try {
        db.close()
      } catch {
        // ignore
      }
    },
  } as IndexedDBCacheProvider & { _closeForTesting: () => void }
}
