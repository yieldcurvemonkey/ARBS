// Client-side OPA sign solver — infer pay/receive direction for package legs.
//
// Port of SDRUtils/packages/opa_sign_solver.py. Used as a fallback when
// the backend hasn't pre-computed opa_sign / opa_signed_net (old data,
// partial ingestion, manual links).
//
// Brute-force 2^N for N ≤ 20, greedy heuristic above.

const TIER_THRESHOLDS: [number, OpaConfidence][] = [
  [100, 'EXACT'],
  [1_000, 'TIGHT'],
  [50_000, 'LOOSE'],
]

export type OpaConfidence = 'EXACT' | 'TIGHT' | 'LOOSE' | 'UNRESOLVED'

export interface OpaSignResult {
  signs: number[]
  net: number
  residual: number
  confidence: OpaConfidence
}

function confidenceTier(residual: number): OpaConfidence {
  for (const [threshold, label] of TIER_THRESHOLDS) {
    if (residual < threshold) return label
  }
  return 'UNRESOLVED'
}

const MAX_BRUTE_N = 20

function solveBrute(opa: number[], ptp: number): OpaSignResult {
  const n = opa.length
  const total = 1 << n
  const opaSum = opa.reduce((s, v) => s + v, 0)

  let bestMask = 0
  let bestResidual = Infinity
  let bestNet = -opaSum
  let bestDirect = Infinity

  for (let mask = 0; mask < total; mask++) {
    let plus = 0
    for (let i = 0; i < n; i++) {
      if (mask & (1 << i)) plus += opa[i]
    }
    const net = 2 * plus - opaSum
    const direct = Math.abs(net - ptp)
    const residual = Math.min(direct, Math.abs(net + ptp))

    if (
      residual < bestResidual - 1e-9 ||
      (residual <= bestResidual + 1e-9 && direct < bestDirect - 1e-9) ||
      (residual <= bestResidual + 1e-9 && direct <= bestDirect + 1e-9 && mask < bestMask)
    ) {
      bestResidual = residual
      bestDirect = direct
      bestNet = net
      bestMask = mask
    }
  }

  const signs = Array.from({ length: n }, (_, i) =>
    bestMask & (1 << i) ? 1 : -1,
  )
  return { signs, net: bestNet, residual: bestResidual, confidence: confidenceTier(bestResidual) }
}

function solveGreedy(opa: number[], ptp: number): OpaSignResult {
  const indexed = opa
    .map((v, i) => ({ v, i }))
    .sort((a, b) => b.v - a.v)

  const signs = new Array<number>(opa.length).fill(0)
  let running = 0

  for (const { v, i } of indexed) {
    const plusD = Math.min(Math.abs(running + v - ptp), Math.abs(running + v + ptp))
    const minusD = Math.min(Math.abs(running - v - ptp), Math.abs(running - v + ptp))
    if (plusD <= minusD) {
      signs[i] = 1
      running += v
    } else {
      signs[i] = -1
      running -= v
    }
  }

  const residual = Math.min(Math.abs(running - ptp), Math.abs(running + ptp))
  return { signs, net: running, residual, confidence: confidenceTier(residual) }
}

export function solveOpaSigns(
  opaValues: number[],
  ptpValue: number,
): OpaSignResult {
  const n = opaValues.length

  if (n === 0) {
    return { signs: [], net: 0, residual: Math.abs(ptpValue), confidence: 'UNRESOLVED' }
  }

  if (!Number.isFinite(ptpValue) || ptpValue === 0) {
    const net = opaValues.reduce((s, v) => s + v, 0)
    return { signs: new Array(n).fill(1), net, residual: Math.abs(net), confidence: 'UNRESOLVED' }
  }

  return n <= MAX_BRUTE_N ? solveBrute(opaValues, ptpValue) : solveGreedy(opaValues, ptpValue)
}
