// Augmented timeseries hook for the analytics dock — returns custy + IDB
// daily close series (plus intraday ticks) keyed off a focused trade.
// Client-side mock today; the real implementation will extend
// /api/usd-swaps-tape-v2/timeseries with ?platform=custy|idb|all,
// range=1D|...|1Y|CUSTOM, view=VOLUME.
import { useMemo } from 'react'
import type {
  AnalyticsViewKey,
  FocusedTrade,
  TimeseriesPointAug,
} from '../components/AnalyticsPanel/analytics-types'
import {
  generateDailyClose,
  generateIntraday,
} from '../components/AnalyticsPanel/mock-analytics'

export interface UseAnalyticsTimeseriesReturn {
  dailyClose: TimeseriesPointAug[]
  intraday: TimeseriesPointAug[]
  loading: boolean
  error: string | null
  // Selects the right series for a given view; daily for everything
  // except INTRADAY.
  pickForView: (view: AnalyticsViewKey) => TimeseriesPointAug[]
}

export function useAnalyticsTimeseries(focused: FocusedTrade | null): UseAnalyticsTimeseriesReturn {
  const dailyClose = useMemo(() => generateDailyClose(focused), [focused])
  const intraday = useMemo(() => generateIntraday(focused), [focused])
  const pickForView = (view: AnalyticsViewKey) =>
    view === 'INTRADAY' ? intraday : dailyClose
  return { dailyClose, intraday, loading: false, error: null, pickForView }
}
