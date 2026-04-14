// Shared helper used by sidecar hooks; abstracts the polling/abort/loading
// machinery so each sidecar only has to describe its endpoint and query params.
import { useCallback, useEffect, useRef, useState } from 'react'
import { POLL_INTERVAL_MS, TAPE_V2_API_BASE } from '../constants'

export interface UseSidecarFetchResult<T> {
  data: T | null
  isLoading: boolean
  error: Error | null
  refetch: () => void
}

export function useSidecarFetch<T>(
  endpoint: string,
  params: Record<string, string | number | null | undefined>,
  options?: { pollingEnabled?: boolean },
): UseSidecarFetchResult<T> {
  const [data, setData] = useState<T | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<Error | null>(null)
  const abortRef = useRef<AbortController | null>(null)

  const serializedParams = JSON.stringify(params)

  const fetchOnce = useCallback(async () => {
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    setIsLoading(true)
    setError(null)
    try {
      const q = new URLSearchParams()
      for (const [k, v] of Object.entries(params)) {
        if (v !== null && v !== undefined && v !== '') q.set(k, String(v))
      }
      const res = await fetch(`${TAPE_V2_API_BASE}/${endpoint}?${q}`, {
        signal: controller.signal,
      })
      if (!res.ok) throw new Error(`${endpoint} failed: ${res.statusText}`)
      const json = (await res.json()) as T
      setData(json)
    } catch (e) {
      if ((e as any)?.name === 'AbortError') return
      setError(e instanceof Error ? e : new Error(String(e)))
    } finally {
      setIsLoading(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [endpoint, serializedParams])

  useEffect(() => {
    fetchOnce()
  }, [fetchOnce])

  useEffect(() => {
    if (options?.pollingEnabled === false) return
    const id = setInterval(fetchOnce, POLL_INTERVAL_MS)
    return () => clearInterval(id)
  }, [fetchOnce, options?.pollingEnabled])

  return { data, isLoading, error, refetch: fetchOnce }
}
