// ABOUTME: View-layer types for volume-grid views — cell identifiers,
// bucket overrides, FOMC label modes, and the view/controls component
// interfaces used by DefaultGridView and FomcStripView.

import type { ComponentType } from 'react'
import type {
  VolumeGridResponse,
  VolumeMetric,
  VolumePeriod,
} from './volume-grid.types'
import type {
  BucketDef,
  ForwardSchemaId,
  PackageTypeGroupId,
  TenorSchemaId,
} from '@/lib/usd-swaps-tape-v2/volumeGridBuckets'

export type CollapseAxis = 'tenor' | 'forward'

export type CellId =
  | { kind: 'matrix'; fwd: string; tenor: string }
  | { kind: 'collapsed_tenor'; fwd: string }
  | { kind: 'structure'; fwd: string; structure: string; structureType: 'curve' | 'fly' }

export interface BucketOverrides {
  hidden: string[]
  merged: Array<{ ids: string[]; label: string }>
}

export type FomcLabelMode = 'absolute' | 'constant_maturity'

export interface CellContext {
  packageType?: PackageTypeGroupId
  forwardSchema?: ForwardSchemaId
  tenorSchema?: TenorSchemaId
  customForwardBuckets?: BucketDef[]
  customTenorBuckets?: BucketDef[]
  viewLabel?: string
}

export interface ViewProps {
  metric: VolumeMetric
  period: VolumePeriod
  lookbackDays: number
  textFilter: string
  onCellClick: (cell: CellId, context?: CellContext) => void
}

export interface ControlsProps {
  metric: VolumeMetric
  setMetric: (m: VolumeMetric) => void
  period: VolumePeriod
  setPeriod: (p: VolumePeriod) => void
  lookbackDays: number
  setLookbackDays: (d: number) => void
}

export interface VolumeGridViewDef {
  id: string
  label: string
  component: ComponentType<ViewProps>
  controls: ComponentType<ControlsProps>
}
