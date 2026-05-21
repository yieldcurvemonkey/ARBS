// ABOUTME: Curve and fly structure definitions used by CurveStripView
// and FlyCurveView. Each StructureDef identifies a specific multi-leg
// package structure (e.g. "2s10s") by its constituent tenor years.

import type { StructureDef } from '@/features/usd-swaps-tape-v2/types/structure-grid.types'

const T = 0.125

export const BENCHMARK_CURVES: readonly StructureDef[] = [
  { id: '2s5s',   label: '2s5s',   tenors: [2, 5],   tolerance: T },
  { id: '2s10s',  label: '2s10s',  tenors: [2, 10],  tolerance: T },
  { id: '2s30s',  label: '2s30s',  tenors: [2, 30],  tolerance: T },
  { id: '5s10s',  label: '5s10s',  tenors: [5, 10],  tolerance: T },
  { id: '5s30s',  label: '5s30s',  tenors: [5, 30],  tolerance: T },
  { id: '10s30s', label: '10s30s', tenors: [10, 30], tolerance: T },
]

export const TIGHT_CURVES: readonly StructureDef[] = [
  { id: '3s5s',   label: '3s5s',   tenors: [3, 5],   tolerance: T },
  { id: '5s7s',   label: '5s7s',   tenors: [5, 7],   tolerance: T },
  { id: '7s10s',  label: '7s10s',  tenors: [7, 10],  tolerance: T },
  { id: '10s20s', label: '10s20s', tenors: [10, 20], tolerance: T },
  { id: '20s30s', label: '20s30s', tenors: [20, 30], tolerance: T },
]

export const ALL_CURVES: readonly StructureDef[] = [...BENCHMARK_CURVES, ...TIGHT_CURVES]

export const STANDARD_FLIES: readonly StructureDef[] = [
  { id: '2s5s10s',  label: '2s5s10s',  tenors: [2, 5, 10],  tolerance: T },
  { id: '2s5s30s',  label: '2s5s30s',  tenors: [2, 5, 30],  tolerance: T },
  { id: '2s10s30s', label: '2s10s30s', tenors: [2, 10, 30], tolerance: T },
  { id: '5s10s30s', label: '5s10s30s', tenors: [5, 10, 30], tolerance: T },
]

export const TIGHT_FLIES: readonly StructureDef[] = [
  { id: '3s5s7s',    label: '3s5s7s',    tenors: [3, 5, 7],    tolerance: T },
  { id: '5s7s10s',   label: '5s7s10s',   tenors: [5, 7, 10],   tolerance: T },
  { id: '7s10s20s',  label: '7s10s20s',  tenors: [7, 10, 20],  tolerance: T },
  { id: '10s20s30s', label: '10s20s30s', tenors: [10, 20, 30], tolerance: T },
]

export const ALL_FLIES: readonly StructureDef[] = [...STANDARD_FLIES, ...TIGHT_FLIES]
