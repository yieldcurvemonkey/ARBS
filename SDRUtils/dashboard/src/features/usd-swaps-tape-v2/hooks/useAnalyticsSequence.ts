// ABOUTME: Wrapper hook that delegates to the single-trade
// analytics hooks (useAnalyticsTimeseries / useRarityData /
// useExtremesData) for each trade in a selected sequence and
// aggregates sequence-level summaries on top. Preserves the SWR-
// style caching + dedup that the single-trade hooks already provide
// because every inner call hits the same cache keys.
//
// React's rules-of-hooks forbid conditional or dynamic-length hook
// calls, so we allocate a fixed pool of MAX_SEQUENCE slots and
// invoke the inner hooks unconditionally. Slots that aren't backed
// by an active trade pass null to each inner hook (which already
// no-ops when its `focused` argument is null), so the additional
// invocations are essentially free at the network layer.
//
// Soft cap: traders selecting more than MAX_SEQUENCE rows see only
// the first MAX_SEQUENCE in the dock. The SequenceBar surfaces a
// warning chip when the cap trips so the trader can disambiguate
// between 'I selected too many' and 'the sequence renders fewer
// than I expect'.
import { useMemo } from 'react'
import type {
  AnalyticsRangeKey,
  AnalyticsViewKey,
  FocusedTrade,
  SequenceAggregate,
} from '../components/AnalyticsPanel/analytics-types'
import { computeSequenceAggregate } from '../components/AnalyticsPanel/sequence-aggregate'
import {
  useAnalyticsTimeseries,
  type AnalyticsTimeseriesOptions,
  type UseAnalyticsTimeseriesReturn,
} from './useAnalyticsTimeseries'
import { useExtremesData, type UseExtremesDataReturn } from './useExtremesData'
import { useRarityData, type UseRarityDataReturn } from './useRarityData'

export const MAX_SEQUENCE = 20

export interface SequenceOptions {
  range?: AnalyticsRangeKey
  view?: AnalyticsViewKey
  tsOptions?: AnalyticsTimeseriesOptions
  rarityOptions?: Parameters<typeof useRarityData>[1]
  extremesOptions?: Parameters<typeof useExtremesData>[1]
}

export interface SequencePerTradeEntry {
  trade: FocusedTrade
  timeseries: UseAnalyticsTimeseriesReturn
  rarity: UseRarityDataReturn
  extremes: UseExtremesDataReturn
}

export interface UseAnalyticsSequenceReturn {
  perTrade: SequencePerTradeEntry[]
  aggregate: SequenceAggregate | null
  truncated: boolean
  warning: string | null
}

export function useAnalyticsSequence(
  sequence: readonly FocusedTrade[] | null,
  options: SequenceOptions = {},
): UseAnalyticsSequenceReturn {
  const truncated = (sequence?.length ?? 0) > MAX_SEQUENCE
  const capped = useMemo(
    () => (sequence ? sequence.slice(0, MAX_SEQUENCE) : []),
    [sequence],
  )

  // Allocate a stable array of MAX_SEQUENCE inner-hook invocations.
  // Slot[i] passes capped[i] (or null) to each inner hook. The
  // single-trade hooks already gracefully no-op when focused is
  // null, so the invocations don't fire fetches in unused slots.
  const slots: SequencePerTradeEntry[] = []
  for (let i = 0; i < MAX_SEQUENCE; i += 1) {
    const trade = capped[i] ?? null
    // eslint-disable-next-line react-hooks/rules-of-hooks
    const tsRet = useAnalyticsTimeseries(
      trade,
      options.range ?? '1Y',
      options.view ?? 'DAILY_CLOSE',
      options.tsOptions ?? {},
    )
    // eslint-disable-next-line react-hooks/rules-of-hooks
    const rarityRet = useRarityData(trade, options.rarityOptions ?? {})
    // eslint-disable-next-line react-hooks/rules-of-hooks
    const extremesRet = useExtremesData(trade, options.extremesOptions ?? {})

    if (trade) {
      slots.push({
        trade,
        timeseries: tsRet,
        rarity: rarityRet,
        extremes: extremesRet,
      })
    }
  }

  const aggregate = useMemo(
    () => (capped.length === 0 ? null : computeSequenceAggregate(capped)),
    [capped],
  )

  const warning = truncated
    ? `Selection capped at ${MAX_SEQUENCE} (${sequence?.length ?? 0} selected)`
    : null

  return {
    perTrade: slots,
    aggregate,
    truncated,
    warning,
  }
}

export type { UseAnalyticsTimeseriesReturn }
