// ABOUTME: UI side bucket-label helpers. Looks up labels from the axes
// the server returns in the response payload — those drive the IMM
// dynamic bucket labels too.

import type { VolumeGridSchemaAxis } from '../../types/volume-grid.types'

export function lookupLabel(
  axis: VolumeGridSchemaAxis | undefined,
  id: string,
): string {
  return axis?.buckets.find((b) => b.id === id)?.label ?? id
}
