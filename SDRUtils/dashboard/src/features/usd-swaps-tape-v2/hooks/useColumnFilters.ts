// URL-synced PrimeReact column filter state.
import { useCallback, useMemo } from 'react'
import { usePathname, useRouter, useSearchParams } from 'next/navigation'
import type { ColumnFilterPayload } from '../types'

export const SERVER_FILTER_FIELDS = [
  'time',
  'tape_label',
  'trade_type',
  'package_structure',
  'tenor',
  'notional',
  'dv01',
  'rate',
  'venue',
  'ccp',
  'session',
  'rate_index',
  'fomc_meeting',
  'lifecycle',
  'flags',
] as const

export interface UseColumnFiltersReturn {
  filters: ColumnFilterPayload
  operator: 'and' | 'or'
  setFilters: (next: ColumnFilterPayload) => void
  setOperator: (op: 'and' | 'or') => void
  reset: () => void
  queryString: string
}

export function useColumnFilters(): UseColumnFiltersReturn {
  const router = useRouter()
  const pathname = usePathname()
  const searchParams = useSearchParams()

  const filters = useMemo<ColumnFilterPayload>(() => {
    const raw = searchParams.get('columnFilters')
    if (!raw) return {}
    try {
      const parsed = JSON.parse(raw)
      return parsed && typeof parsed === 'object' ? parsed : {}
    } catch {
      return {}
    }
  }, [searchParams])

  const operator = useMemo<'and' | 'or'>(() => {
    return searchParams.get('columnFilterOp') === 'or' ? 'or' : 'and'
  }, [searchParams])

  const writeParams = useCallback(
    (mutator: (params: URLSearchParams) => void) => {
      const next = new URLSearchParams(searchParams?.toString())
      mutator(next)
      router.replace(`${pathname}?${next.toString()}`, { scroll: false })
    },
    [pathname, router, searchParams],
  )

  const setFilters = useCallback(
    (next: ColumnFilterPayload) => {
      writeParams((params) => {
        if (next && Object.keys(next).length) {
          params.set('columnFilters', JSON.stringify(next))
        } else {
          params.delete('columnFilters')
        }
      })
    },
    [writeParams],
  )

  const setOperator = useCallback(
    (op: 'and' | 'or') => {
      writeParams((params) => {
        if (op === 'or') params.set('columnFilterOp', 'or')
        else params.delete('columnFilterOp')
      })
    },
    [writeParams],
  )

  const reset = useCallback(() => {
    writeParams((params) => {
      params.delete('columnFilters')
      params.delete('columnFilterOp')
    })
  }, [writeParams])

  const queryString = useMemo(() => {
    const q = new URLSearchParams()
    if (Object.keys(filters).length) q.set('columnFilters', JSON.stringify(filters))
    if (operator === 'or') q.set('columnFilterOp', 'or')
    return q.toString()
  }, [filters, operator])

  return { filters, operator, setFilters, setOperator, reset, queryString }
}
