// URL-synced flag/lifecycle/category filter state + Clean Tape preset.
import { useCallback, useMemo } from 'react'
import { usePathname, useRouter, useSearchParams } from 'next/navigation'
import { CLEAN_TAPE_HIDDEN_LIFECYCLES, LIFECYCLE_ORDER } from '../constants'
import type { FlagFilterState, LifecycleType } from '../types'

const ALL_LIFECYCLES: LifecycleType[] = LIFECYCLE_ORDER

function parseCsvSet(raw: string | null, lower = false): Set<string> {
  if (!raw) return new Set()
  return new Set(
    raw
      .split(',')
      .map((s) => (lower ? s.trim().toLowerCase() : s.trim()))
      .filter(Boolean),
  )
}

function csvFromSet(s: Set<string>): string | null {
  if (s.size === 0) return null
  return Array.from(s).sort().join(',')
}

export interface UseFlagFiltersReturn {
  state: FlagFilterState
  toggleLifecycle: (t: LifecycleType) => void
  toggleTradeType: (v: string) => void
  toggleVenue: (v: string) => void
  toggleCcp: (v: string) => void
  toggleSession: (v: string) => void
  toggleRateIndex: (v: string) => void
  toggleTenor: (v: string) => void
  setFomcMeeting: (v: string | null) => void
  setClean: (clean: boolean) => void
  applyCleanPreset: () => void
  resetAll: () => void
  queryString: string
}

export function useFlagFilters(): UseFlagFiltersReturn {
  const router = useRouter()
  const pathname = usePathname()
  const searchParams = useSearchParams()

  const state = useMemo<FlagFilterState>(() => {
    const lifecycleRaw = searchParams.get('lifecycle')
    let lifecycle: Set<LifecycleType>
    if (lifecycleRaw) {
      const lower = parseCsvSet(lifecycleRaw, true)
      lifecycle = new Set(
        ALL_LIFECYCLES.filter((lc) => lower.has(lc.toLowerCase())),
      ) as Set<LifecycleType>
    } else {
      lifecycle = new Set(ALL_LIFECYCLES)
    }

    return {
      lifecycle,
      tradeTypes: parseCsvSet(searchParams.get('tradeTypes')),
      venues: parseCsvSet(searchParams.get('venues')),
      ccps: parseCsvSet(searchParams.get('ccps')),
      sessions: parseCsvSet(searchParams.get('sessions')),
      rateIndex: parseCsvSet(searchParams.get('rateIndex')),
      tenors: parseCsvSet(searchParams.get('tenors')),
      fomcMeeting: searchParams.get('fomcMeeting'),
      clean: searchParams.get('clean') === 'true',
    }
  }, [searchParams])

  const writeParams = useCallback(
    (mutator: (params: URLSearchParams) => void) => {
      const next = new URLSearchParams(searchParams?.toString())
      mutator(next)
      router.replace(`${pathname}?${next.toString()}`, { scroll: false })
    },
    [pathname, router, searchParams],
  )

  const setCsvParam = useCallback(
    (name: string, values: Set<string>, writeWhenFull?: Set<string>) => {
      writeParams((params) => {
        if (writeWhenFull && values.size === writeWhenFull.size) {
          params.delete(name)
          return
        }
        const csv = csvFromSet(values)
        if (csv) params.set(name, csv)
        else params.delete(name)
      })
    },
    [writeParams],
  )

  const toggleLifecycle = useCallback(
    (t: LifecycleType) => {
      const next = new Set(state.lifecycle)
      if (next.has(t)) next.delete(t)
      else next.add(t)
      writeParams((params) => {
        if (next.size === ALL_LIFECYCLES.length) {
          params.delete('lifecycle')
        } else {
          params.set(
            'lifecycle',
            Array.from(next).sort().map((l) => l.toLowerCase()).join(','),
          )
        }
      })
    },
    [state.lifecycle, writeParams],
  )

  const toggleCategory = useCallback(
    (name: keyof FlagFilterState, v: string) => {
      const current = state[name] as Set<string>
      const next = new Set(current)
      if (next.has(v)) next.delete(v)
      else next.add(v)
      setCsvParam(name as string, next)
    },
    [state, setCsvParam],
  )

  const setFomcMeeting = useCallback(
    (v: string | null) => {
      writeParams((params) => {
        if (v) params.set('fomcMeeting', v)
        else params.delete('fomcMeeting')
      })
    },
    [writeParams],
  )

  const setClean = useCallback(
    (clean: boolean) => {
      writeParams((params) => {
        if (clean) params.set('clean', 'true')
        else params.delete('clean')
      })
    },
    [writeParams],
  )

  const applyCleanPreset = useCallback(() => {
    const survivors = ALL_LIFECYCLES.filter(
      (l) => !CLEAN_TAPE_HIDDEN_LIFECYCLES.includes(l),
    )
    writeParams((params) => {
      params.set('clean', 'true')
      params.set(
        'lifecycle',
        survivors.map((l) => l.toLowerCase()).sort().join(','),
      )
    })
  }, [writeParams])

  const resetAll = useCallback(() => {
    writeParams((params) => {
      params.delete('clean')
      params.delete('lifecycle')
      params.delete('tradeTypes')
      params.delete('venues')
      params.delete('ccps')
      params.delete('sessions')
      params.delete('rateIndex')
      params.delete('tenors')
      params.delete('fomcMeeting')
    })
  }, [writeParams])

  const queryString = useMemo(() => {
    const q = new URLSearchParams()
    if (state.clean) q.set('clean', 'true')
    if (state.lifecycle.size !== ALL_LIFECYCLES.length) {
      q.set(
        'lifecycle',
        Array.from(state.lifecycle)
          .sort()
          .map((l) => l.toLowerCase())
          .join(','),
      )
    }
    for (const [k, set] of Object.entries({
      tradeTypes: state.tradeTypes,
      venues: state.venues,
      ccps: state.ccps,
      sessions: state.sessions,
      rateIndex: state.rateIndex,
      tenors: state.tenors,
    })) {
      const csv = csvFromSet(set)
      if (csv) q.set(k, csv)
    }
    if (state.fomcMeeting) q.set('fomcMeeting', state.fomcMeeting)
    return q.toString()
  }, [state])

  return {
    state,
    toggleLifecycle,
    toggleTradeType: (v: string) => toggleCategory('tradeTypes', v),
    toggleVenue: (v: string) => toggleCategory('venues', v),
    toggleCcp: (v: string) => toggleCategory('ccps', v),
    toggleSession: (v: string) => toggleCategory('sessions', v),
    toggleRateIndex: (v: string) => toggleCategory('rateIndex', v),
    toggleTenor: (v: string) => toggleCategory('tenors', v),
    setFomcMeeting,
    setClean,
    applyCleanPreset,
    resetAll,
    queryString,
  }
}

export const __internal = { parseCsvSet, csvFromSet }
