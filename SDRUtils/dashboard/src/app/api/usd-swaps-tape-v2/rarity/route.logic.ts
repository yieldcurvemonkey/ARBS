import {
  percentile,
  rateToBps,
  safeNum,
} from '@/lib/usd-swaps-tape-v2/analytics'

export type SimilaritySample = {
  fixed_rate: number | null
  notional: number | null
}

export function sampleMatchesSimilarity(
  sample: SimilaritySample,
  opts: {
    focusedRateBps: number
    primaryTol: number
    focusedNotional: number
    sizeTolPct: number
  },
): boolean {
  if (!Number.isFinite(opts.focusedRateBps)) return false
  const rateOk =
    Math.abs(rateToBps(sample.fixed_rate) - opts.focusedRateBps) <= opts.primaryTol
  if (!rateOk) return false
  if (!Number.isFinite(opts.focusedNotional)) return true
  const sizeTol = opts.focusedNotional * opts.sizeTolPct
  return Math.abs(Math.abs(safeNum(sample.notional)) - opts.focusedNotional) <= sizeTol
}

export const percentileProbe = (arr: number[], p: number) =>
  percentile(arr.slice().sort((a, b) => a - b), p)
