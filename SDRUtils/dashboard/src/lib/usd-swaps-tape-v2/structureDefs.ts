// ABOUTME: Curve and fly structure definitions used by CurveStripView
// and FlyCurveView. Each StructureDef identifies a specific multi-leg
// package structure (e.g. "2s10s") by its constituent tenor years.

import type { StructureDef } from '@/features/usd-swaps-tape-v2/types/structure-grid.types'

const T = 0.125

function c(tenors: number[]): StructureDef {
  const label = tenors.map(t => `${t}s`).join('')
  return { id: label, label, tenors, tolerance: T }
}

// ── Curves (2-leg) ──────────────────────────────────────────────────

export const BENCHMARK_CURVES: readonly StructureDef[] = [
  c([2, 5]), c([2, 10]), c([2, 30]),
  c([5, 10]), c([5, 30]),
  c([10, 30]),
]

export const MICRO_CURVES: readonly StructureDef[] = [
  c([1, 2]), c([2, 3]), c([3, 4]), c([4, 5]),
  c([5, 6]), c([6, 7]), c([7, 8]), c([8, 9]), c([9, 10]),
  c([10, 12]), c([12, 15]), c([15, 20]), c([20, 25]), c([25, 30]),
]

export const WIDE_CURVES: readonly StructureDef[] = [
  c([2, 7]), c([2, 20]),
  c([3, 5]), c([3, 7]), c([3, 10]), c([3, 30]),
  c([4, 10]),
  c([5, 7]), c([5, 20]),
  c([7, 10]), c([7, 20]), c([7, 30]),
  c([10, 15]), c([10, 20]), c([10, 25]),
  c([15, 30]), c([20, 30]),
]

export const ALL_CURVES: readonly StructureDef[] = (() => {
  const seen = new Set<string>()
  const all: StructureDef[] = []
  for (const s of [...BENCHMARK_CURVES, ...WIDE_CURVES, ...MICRO_CURVES]) {
    if (!seen.has(s.id)) { seen.add(s.id); all.push(s) }
  }
  return all.sort((a, b) => a.tenors[0] - b.tenors[0] || a.tenors[1] - b.tenors[1])
})()

// ── Flies (3-leg) ───────────────────────────────────────────────────

export const BENCHMARK_FLIES: readonly StructureDef[] = [
  c([2, 5, 10]), c([2, 5, 30]), c([2, 10, 30]), c([5, 10, 30]),
]

export const MICRO_FLIES: readonly StructureDef[] = [
  c([1, 2, 3]), c([2, 3, 4]), c([3, 4, 5]), c([4, 5, 6]),
  c([5, 6, 7]), c([6, 7, 8]), c([7, 8, 9]), c([8, 9, 10]),
  c([9, 10, 12]), c([10, 12, 15]), c([12, 15, 20]), c([15, 20, 25]), c([20, 25, 30]),
]

export const WIDE_FLIES: readonly StructureDef[] = [
  c([2, 3, 5]), c([2, 3, 10]), c([2, 5, 7]),
  c([2, 7, 10]), c([2, 7, 30]), c([2, 10, 20]),
  c([3, 5, 7]), c([3, 5, 10]), c([3, 7, 10]), c([3, 10, 30]),
  c([5, 7, 10]), c([5, 7, 30]), c([5, 10, 20]), c([5, 10, 15]),
  c([5, 15, 30]), c([5, 20, 30]),
  c([7, 10, 15]), c([7, 10, 20]), c([7, 10, 30]),
  c([7, 15, 30]), c([7, 20, 30]),
  c([10, 15, 20]), c([10, 15, 30]), c([10, 20, 30]),
  c([15, 20, 30]),
]

export const ALL_FLIES: readonly StructureDef[] = (() => {
  const seen = new Set<string>()
  const all: StructureDef[] = []
  for (const s of [...BENCHMARK_FLIES, ...WIDE_FLIES, ...MICRO_FLIES]) {
    if (!seen.has(s.id)) { seen.add(s.id); all.push(s) }
  }
  return all.sort((a, b) =>
    a.tenors[0] - b.tenors[0] || a.tenors[1] - b.tenors[1] || a.tenors[2] - b.tenors[2])
})()

// Legacy aliases
export const STANDARD_FLIES = BENCHMARK_FLIES
export const TIGHT_CURVES = MICRO_CURVES
export const TIGHT_FLIES = MICRO_FLIES
