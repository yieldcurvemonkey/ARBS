// ABOUTME: Human-readable labels and ordering for the volume-grid axes.
// Server-side authority is volumeGridBuckets.ts in src/lib; this module
// is the UI copy of the labels + bucket id ordering.

import { FORWARD_BUCKETS, TENOR_BUCKETS } from '@/lib/usd-swaps-tape-v2/volumeGridBuckets'

export const FORWARD_AXIS = FORWARD_BUCKETS
export const TENOR_AXIS = TENOR_BUCKETS

export function fwdLabel(id: string): string {
  return FORWARD_BUCKETS.find((b) => b.id === id)?.label ?? id
}
export function tenorLabel(id: string): string {
  return TENOR_BUCKETS.find((b) => b.id === id)?.label ?? id
}
