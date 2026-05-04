// ABOUTME: Pure-function helper that summarises a FocusedTrade
// sequence into the SequenceAggregate that SequenceBar +
// SequenceTab + the wrapper hook all read. Lives in its own file so
// the unit tests don't have to spin up the React component to
// exercise the math.
import type {
  FocusedTrade,
  SequenceAggregate,
} from './analytics-types'

function tsMs(ts: string | null | undefined): number | null {
  if (!ts) return null
  const ms = Date.parse(ts)
  return Number.isFinite(ms) ? ms : null
}

export function computeSequenceAggregate(
  sequence: readonly FocusedTrade[],
): SequenceAggregate {
  // Defensive guard: callers should never pass an empty sequence
  // (the dock branches on mode === 'sequence' which requires N>=2),
  // but if they do we return a safe zero shape rather than NaN.
  if (sequence.length === 0) {
    return {
      count: 0,
      totalDv01Usd: 0,
      weightedFixedRateBps: 0,
      totalNotionalUsd: 0,
      timeSpanMs: null,
      startTs: null,
      endTs: null,
      sideMix: { pay: 0, rcv: 0 },
      venueMix: {},
    }
  }

  let totalDv01 = 0
  let totalNotional = 0
  let weightedRateNumerator = 0
  let weightedRateDenominator = 0
  const sideMix = { pay: 0, rcv: 0 }
  const venueMix: Record<string, number> = {}
  let minTs: number | null = null
  let maxTs: number | null = null
  let minTsStr: string | null = null
  let maxTsStr: string | null = null

  for (const trade of sequence) {
    const dv01 = Number.isFinite(trade.dv01_usd_per_bp) ? Math.abs(trade.dv01_usd_per_bp) : 0
    const notional = Number.isFinite(trade.notional_usd) ? Math.abs(trade.notional_usd) : 0
    const rate = Number.isFinite(trade.fixed_rate_bps) ? trade.fixed_rate_bps : 0

    totalDv01 += dv01
    totalNotional += notional

    // DV01-weighted rate. When DV01 is missing we fall back to a
    // notional weight; when both are missing the trade contributes 0
    // to the numerator + 0 to the denominator (i.e. is silently
    // skipped from the weighted average).
    const weight = dv01 > 0 ? dv01 : notional
    if (weight > 0) {
      weightedRateNumerator += rate * weight
      weightedRateDenominator += weight
    }

    if (trade.side === 'PAY') sideMix.pay += 1
    else if (trade.side === 'RCV') sideMix.rcv += 1

    const venue = trade.venue || 'UNKNOWN'
    venueMix[venue] = (venueMix[venue] ?? 0) + 1

    const ms = tsMs(trade.execution_start)
    if (ms != null) {
      if (minTs == null || ms < minTs) {
        minTs = ms
        minTsStr = trade.execution_start
      }
      if (maxTs == null || ms > maxTs) {
        maxTs = ms
        maxTsStr = trade.execution_start
      }
    }
  }

  const timeSpanMs =
    minTs != null && maxTs != null ? maxTs - minTs : null

  const weightedFixedRateBps =
    weightedRateDenominator > 0
      ? weightedRateNumerator / weightedRateDenominator
      : 0

  return {
    count: sequence.length,
    totalDv01Usd: totalDv01,
    weightedFixedRateBps,
    totalNotionalUsd: totalNotional,
    timeSpanMs,
    startTs: minTsStr,
    endTs: maxTsStr,
    sideMix,
    venueMix,
  }
}
