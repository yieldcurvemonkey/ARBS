import { EMPTY_VALUE } from '../../constants'
import type { UsdSwapTapeRow } from '../../types'

export function displayTapeLabel(row: UsdSwapTapeRow): string {
  const labels = [row.tape_label, row.legs_json?.[0]?.tape_label]
  for (const label of labels) {
    if (typeof label === 'string' && label.trim().length > 0) {
      return label.trim()
    }
  }
  return EMPTY_VALUE
}
