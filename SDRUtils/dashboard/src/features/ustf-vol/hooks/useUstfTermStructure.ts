import { useCallback, useEffect, useState } from 'react'

import type { AssetType, TermStructureResponse } from '../types'

export function useUstfTermStructure(params: {
  assetType: AssetType
  expiry: string
  dates: string[]
  strikeOffsetBps: number
}) {
  const [data, setData] = useState<TermStructureResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const { assetType, expiry, dates, strikeOffsetBps } = params
  const datesKey = dates.join(',')

  const load = useCallback(async () => {
    if (dates.length === 0) {
      setData(null)
      setLoading(false)
      return
    }
    setLoading(true)
    setError(null)
    try {
      const qs = new URLSearchParams()
      qs.set('asset_type', assetType)
      qs.set('expiry', expiry)
      qs.set('dates', datesKey)
      qs.set('strike_offset_bps', String(strikeOffsetBps))

      const res = await fetch(`/api/ustf-vol/term-structure?${qs}`, { cache: 'no-store' })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setData(await res.json())
    } catch (e: any) {
      setError(e?.message ?? 'Unable to load term structure')
    } finally {
      setLoading(false)
    }
  }, [assetType, expiry, datesKey, strikeOffsetBps])

  useEffect(() => { load() }, [load])

  return { data, loading, error, reload: load }
}
