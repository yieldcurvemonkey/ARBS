// URL-synced PrimeReact column filter state + sort.
// NOTE(feedback-round-1): replaced fuzzy/operator params with a full
// DataTableFilterMeta round-trip plus sort_field / sort_order.
import { useCallback, useMemo } from 'react'
import { usePathname, useRouter, useSearchParams } from 'next/navigation'
import type { DataTableFilterMeta } from 'primereact/datatable'
import { buildColumnFilterPayload } from '../components/TradeTapeTable/filter-utils'
import {
  DEFAULT_SORT_FIELD,
  DEFAULT_SORT_ORDER,
  mergeWithInitialFilters,
  parseSortField,
  parseSortOrder,
  rehydrateFilters,
} from './useColumnFilters.helpers'

export const COLUMN_FILTER_QUERY_KEY = 'columnFilters'
export const SORT_FIELD_QUERY_KEY = 'sort_field'
export const SORT_ORDER_QUERY_KEY = 'sort_order'
export { DEFAULT_SORT_FIELD, DEFAULT_SORT_ORDER } from './useColumnFilters.helpers'

// Kept for backward compat with any remaining SWR cache keys that referenced
// this constant. The field list is no longer authoritative — filtering is
// fully client-side and every column is filterable.
export const SERVER_FILTER_FIELDS: readonly string[] = []

export type SortOrder = 1 | -1 | null

export interface UseColumnFiltersReturn {
  filters: DataTableFilterMeta
  sortField: string | null
  sortOrder: SortOrder
  setFilters: (next: DataTableFilterMeta) => void
  setSort: (field: string | null, order: SortOrder) => void
  reset: () => void
  queryString: string
}

export function useColumnFilters(): UseColumnFiltersReturn {
  const router = useRouter()
  const pathname = usePathname()
  const searchParams = useSearchParams()

  const filters = useMemo<DataTableFilterMeta>(() => {
    return mergeWithInitialFilters(
      rehydrateFilters(searchParams?.get(COLUMN_FILTER_QUERY_KEY) ?? null),
    )
  }, [searchParams])

  const sortField = useMemo<string | null>(() => {
    return parseSortField(searchParams?.get(SORT_FIELD_QUERY_KEY))
  }, [searchParams])

  const sortOrder = useMemo<SortOrder>(() => {
    return parseSortOrder(searchParams?.get(SORT_ORDER_QUERY_KEY))
  }, [searchParams])

  const writeParams = useCallback(
    (mutator: (params: URLSearchParams) => void) => {
      const next = new URLSearchParams(searchParams?.toString() ?? '')
      mutator(next)
      router.replace(`${pathname}?${next.toString()}`, { scroll: false })
    },
    [pathname, router, searchParams],
  )

  const setFilters = useCallback(
    (next: DataTableFilterMeta) => {
      writeParams((params) => {
        const payload = buildColumnFilterPayload(next)
        if (Object.keys(payload).length) {
          params.set(COLUMN_FILTER_QUERY_KEY, JSON.stringify(payload))
        } else {
          params.delete(COLUMN_FILTER_QUERY_KEY)
        }
      })
    },
    [writeParams],
  )

  const setSort = useCallback(
    (field: string | null, order: SortOrder) => {
      writeParams((params) => {
        if (field && order) {
          params.set(SORT_FIELD_QUERY_KEY, field)
          params.set(SORT_ORDER_QUERY_KEY, String(order))
        } else {
          params.set(SORT_FIELD_QUERY_KEY, DEFAULT_SORT_FIELD)
          params.set(SORT_ORDER_QUERY_KEY, String(DEFAULT_SORT_ORDER))
        }
      })
    },
    [writeParams],
  )

  const reset = useCallback(() => {
    writeParams((params) => {
      params.delete(COLUMN_FILTER_QUERY_KEY)
      params.set(SORT_FIELD_QUERY_KEY, DEFAULT_SORT_FIELD)
      params.set(SORT_ORDER_QUERY_KEY, String(DEFAULT_SORT_ORDER))
    })
  }, [writeParams])

  const queryString = useMemo(() => {
    const q = new URLSearchParams()
    const payload = buildColumnFilterPayload(filters)
    if (Object.keys(payload).length) {
      q.set(COLUMN_FILTER_QUERY_KEY, JSON.stringify(payload))
    }
    if (sortField && sortOrder) {
      q.set(SORT_FIELD_QUERY_KEY, sortField)
      q.set(SORT_ORDER_QUERY_KEY, String(sortOrder))
    }
    return q.toString()
  }, [filters, sortField, sortOrder])

  return {
    filters,
    sortField,
    sortOrder,
    setFilters,
    setSort,
    reset,
    queryString,
  }
}
