// ABOUTME: Mounts SWRConfig at the dashboard root with an
// IndexedDB-backed cache provider. SWR's provider pattern accepts
// any Map-shaped backing store; we wrap createIndexedDBCacheProvider
// behind a Suspense-friendly loading state. Until the persistent
// cache hydrates, children render against an empty Map fallback —
// which produces no behaviour difference for code paths that don't
// use SWR.
'use client'

import { SWRConfig } from 'swr'
import { useEffect, useState, type ReactNode } from 'react'
import {
  createIndexedDBCacheProvider,
  type IndexedDBCacheProvider,
} from '@/lib/swr/IndexedDBCacheProvider'
import { createFetcher } from '@/lib/swr/SwrFetcher'

const DEFAULT_MAX_ENTRIES = 200

function readMaxEntries(): number {
  // Read at use-site so HMR / per-environment overrides flow through.
  const raw = process.env.NEXT_PUBLIC_SWR_CACHE_MAX_ENTRIES
  const n = Number(raw)
  if (!Number.isFinite(n) || n <= 0) return DEFAULT_MAX_ENTRIES
  return Math.floor(n)
}

export function SwrProvider({ children }: { children: ReactNode }) {
  const [provider, setProvider] = useState<IndexedDBCacheProvider | null>(null)

  useEffect(() => {
    let mounted = true
    createIndexedDBCacheProvider({ maxEntries: readMaxEntries() })
      .then((p) => {
        if (mounted) setProvider(p)
      })
      .catch(() => {
        // graceful fallback handled inside createIndexedDBCacheProvider;
        // surface nothing further to the user.
      })
    return () => {
      mounted = false
    }
  }, [])

  if (!provider) {
    // Pre-hydrate: render children inside a vanilla SWRConfig with the
    // ETag-aware fetcher so any in-flight requests work, but no
    // persistent cache yet.
    return <SWRConfig value={{ fetcher: createFetcher() }}>{children}</SWRConfig>
  }

  return (
    <SWRConfig
      value={{
        provider: () => provider as unknown as Map<string, unknown>,
        fetcher: createFetcher(),
        revalidateOnFocus: false,
        dedupingInterval: 5000,
      }}
    >
      {children}
    </SWRConfig>
  )
}
