// ABOUTME: SWR fetcher used by the analytics-dock hooks. Pairs with
// the server-side LRU + ETag wrappers on the three USD swaps tape v2
// analytics routes (analytics-timeseries / rarity / extremes).
//
// The browser's native HTTP cache handles ETag + If-None-Match
// automatically when the response carries `Cache-Control: max-age=...,
// must-revalidate`: within max-age the browser serves from cache with
// no network round-trip, and after max-age it sends If-None-Match
// transparently and substitutes the cached body on 304. We don't need
// (or want) a parallel JS-level ETag cache — that path doesn't survive
// page reload, so the browser cache is strictly more capable. fetcher
// just hands the URL to fetch() and parses the JSON response.

export function createFetcher() {
  return async function fetcher<T>(url: string): Promise<T> {
    const response = await fetch(url)
    if (!response.ok) {
      throw new Error(
        `Request failed: ${response.status} ${response.statusText}`,
      )
    }
    return (await response.json()) as T
  }
}
