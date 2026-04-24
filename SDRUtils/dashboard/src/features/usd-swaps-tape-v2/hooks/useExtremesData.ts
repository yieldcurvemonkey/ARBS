// Returns the all-time / 52w / 30d extremes + recent-similar rows for the
// analytics dock's Traded Levels tab. Currently backed by the same
// deterministic mock as the rarity hook — see useRarityData for the
// eventual fetch swap pattern.
import { useMemo } from 'react'
import type {
  ExtremeRow,
  FocusedTrade,
  RecentSimilarRow,
} from '../components/AnalyticsPanel/analytics-types'
import {
  generateExtremes,
  generateRecentSimilar,
} from '../components/AnalyticsPanel/mock-analytics'

export interface UseExtremesDataReturn {
  extremes: ExtremeRow[]
  recentSimilar: RecentSimilarRow[]
  loading: boolean
  error: string | null
}

export function useExtremesData(focused: FocusedTrade | null): UseExtremesDataReturn {
  const extremes = useMemo(() => generateExtremes(focused), [focused])
  const recentSimilar = useMemo(() => generateRecentSimilar(focused), [focused])
  return { extremes, recentSimilar, loading: false, error: null }
}
