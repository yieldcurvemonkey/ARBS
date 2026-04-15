// URL-synced UI controls for the USD swaps tape DataTable: fuzzy search, sort
// field, and sort direction. Mirrors the `useColumnFilters` hook's pattern of
// reading and writing through `next/navigation` so the URL is always the
// source of truth — paste a URL and the table ends up in the exact same
// filter/sort/search state.
import { useCallback, useMemo } from 'react'
import { usePathname, useRouter, useSearchParams } from 'next/navigation'

export type SortDirection = 1 | -1 | 0

export const SEARCH_QUERY_KEY = 'q'
export const SORT_FIELD_QUERY_KEY = 'sortField'
export const SORT_ORDER_QUERY_KEY = 'sortOrder'

export interface UseTableControlsReturn {
  search: string
  setSearch: (next: string) => void
  sortField: string | null
  setSortField: (next: string | null) => void
  sortOrder: SortDirection
  setSortOrder: (next: SortDirection) => void
  setSort: (field: string | null, order: SortDirection) => void
  reset: () => void
}

function parseSortOrder(raw: string | null): SortDirection {
  if (raw === '1') return 1
  if (raw === '-1') return -1
  return 0
}

export function useTableControls(): UseTableControlsReturn {
  const router = useRouter()
  const pathname = usePathname()
  const searchParams = useSearchParams()

  const search = useMemo(
    () => searchParams.get(SEARCH_QUERY_KEY) ?? '',
    [searchParams],
  )
  const sortField = useMemo(
    () => searchParams.get(SORT_FIELD_QUERY_KEY),
    [searchParams],
  )
  const sortOrder = useMemo(
    () => parseSortOrder(searchParams.get(SORT_ORDER_QUERY_KEY)),
    [searchParams],
  )

  // Small helper — debouncing the URL writes is the caller's job (typically
  // via the controlled-input pattern used in TradeTapeTable's filter bar).
  const writeParams = useCallback(
    (mutator: (params: URLSearchParams) => void) => {
      const next = new URLSearchParams(searchParams?.toString())
      mutator(next)
      const qs = next.toString()
      router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false })
    },
    [pathname, router, searchParams],
  )

  const setSearch = useCallback(
    (next: string) => {
      writeParams((params) => {
        if (next) params.set(SEARCH_QUERY_KEY, next)
        else params.delete(SEARCH_QUERY_KEY)
      })
    },
    [writeParams],
  )

  const setSortField = useCallback(
    (next: string | null) => {
      writeParams((params) => {
        if (next) params.set(SORT_FIELD_QUERY_KEY, next)
        else {
          params.delete(SORT_FIELD_QUERY_KEY)
          params.delete(SORT_ORDER_QUERY_KEY)
        }
      })
    },
    [writeParams],
  )

  const setSortOrder = useCallback(
    (next: SortDirection) => {
      writeParams((params) => {
        if (next === 0) {
          params.delete(SORT_ORDER_QUERY_KEY)
          params.delete(SORT_FIELD_QUERY_KEY)
        } else {
          params.set(SORT_ORDER_QUERY_KEY, String(next))
        }
      })
    },
    [writeParams],
  )

  // Combined setter — avoids two URL-writes in a row (which would each trigger
  // a re-render) when the user toggles a column header.
  const setSort = useCallback(
    (field: string | null, order: SortDirection) => {
      writeParams((params) => {
        if (!field || order === 0) {
          params.delete(SORT_FIELD_QUERY_KEY)
          params.delete(SORT_ORDER_QUERY_KEY)
          return
        }
        params.set(SORT_FIELD_QUERY_KEY, field)
        params.set(SORT_ORDER_QUERY_KEY, String(order))
      })
    },
    [writeParams],
  )

  const reset = useCallback(() => {
    writeParams((params) => {
      params.delete(SEARCH_QUERY_KEY)
      params.delete(SORT_FIELD_QUERY_KEY)
      params.delete(SORT_ORDER_QUERY_KEY)
    })
  }, [writeParams])

  return {
    search,
    setSearch,
    sortField,
    setSortField,
    sortOrder,
    setSortOrder,
    setSort,
    reset,
  }
}
