// ABOUTME: ETag-aware fetch wrapper for SWR. Retains the last seen
// ETag + payload per URL; sends If-None-Match on subsequent fetches;
// returns the cached payload on 304. Errors on any other non-200.
//
// Pairs with the server-side LRU+ETag wrappers on the three USD swaps
// tape v2 analytics routes (analytics-timeseries / rarity / extremes).

interface CacheEntry<T> {
  etag: string
  payload: T
}

export function createFetcher() {
  const cache = new Map<string, CacheEntry<unknown>>()

  return async function fetcher<T>(url: string): Promise<T> {
    const prior = cache.get(url)
    const headers: Record<string, string> = {}
    if (prior?.etag) headers['If-None-Match'] = prior.etag

    const response = await fetch(url, { headers })

    if (response.status === 304 && prior) {
      return prior.payload as T
    }

    if (!response.ok) {
      throw new Error(
        `Request failed: ${response.status} ${response.statusText}`,
      )
    }

    const payload = (await response.json()) as T
    const etag = response.headers.get('ETag')
    if (etag) {
      cache.set(url, { etag, payload })
    }
    return payload
  }
}
