// ABOUTME: Types for the /volume-grid/structure endpoint and the
// StructureGridView shared component. Curves and flies use the same
// response shape as the standard volume grid but with a "structure"
// axis replacing "tenor".

import type { VolumeGridCell, VolumeGridTotalEntry, VolumeGridSchemaAxis } from './volume-grid.types'

export type StructureType = 'curve' | 'fly'

export interface StructureDef {
  readonly id: string
  readonly label: string
  readonly tenors: readonly number[]
  readonly tolerance: number
}

export interface StructureGridResponse {
  asOf: string
  metric: 'notional' | 'dv01'
  period: string
  lookbackDays: number
  structureType: StructureType
  forwardSchema: string
  axes: {
    forward: VolumeGridSchemaAxis
    structure: VolumeGridSchemaAxis
  }
  cells: VolumeGridCell[]
  totals: {
    rowTotals: Record<string, VolumeGridTotalEntry>
    colTotals: Record<string, VolumeGridTotalEntry>
    grand: VolumeGridTotalEntry
  }
}
