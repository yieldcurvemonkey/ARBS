import { useCallback, useEffect, useState } from 'react'

import type { AssetType, SmileResponse, SmileXAxis } from '../types'

export function useUstfSmile(params: {
  assetType: AssetType
  product?: string
  expiry: string
  tail?: string
  dates: string[]
  xAxis: SmileXAxis
  numPoints?: number
}) {
  const [data, setData] = useState<SmileResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const { assetType, product, expiry, tail, dates, xAxis, numPoints = 21 } = params
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
      if (product) qs.set('product', product)
      qs.set('expiry', expiry)
      if (tail) qs.set('tail', tail)
      qs.set('dates', datesKey)
      qs.set('x_axis', xAxis)
      qs.set('num_points', String(numPoints))

      const res = await fetch(`/api/ustf-vol/smile?${qs}`, { cache: 'no-store' })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setData(await res.json())
    } catch (e: any) {
      setError(e?.message ?? 'Unable to load smile')
    } finally {
      setLoading(false)
    }
  }, [assetType, product, expiry, tail, datesKey, xAxis, numPoints])

  useEffect(() => { load() }, [load])

  return { data, loading, error, reload: load }
}
