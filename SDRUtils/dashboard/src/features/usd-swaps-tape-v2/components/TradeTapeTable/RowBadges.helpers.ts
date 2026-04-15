// Pure helpers extracted from RowBadges.tsx — testable without React.
import { FLAG_CHIP_TONES, LIFECYCLE_LABELS, LIFECYCLE_ORDER, LIFECYCLE_TONES } from '../../constants'
import type { LifecycleType, UsdSwapTapeRow } from '../../types'

export function lifecyclePillsFor(row: UsdSwapTapeRow): Array<{
  type: LifecycleType
  count: number
  className: string
  label: string
}> {
  const mix = row.lifecycle_mix ?? {}
  const pills: Array<{
    type: LifecycleType
    count: number
    className: string
    label: string
  }> = []
  for (const type of LIFECYCLE_ORDER) {
    const count = Number(mix[type] ?? 0)
    if (count > 0) {
      pills.push({
        type,
        count,
        className: LIFECYCLE_TONES[type],
        label: LIFECYCLE_LABELS[type],
      })
    }
  }
  // Drop the NEW pill when the mix also contains any non-NEW lifecycle —
  // e.g. an unwind/termination that started as a new risk shouldn't read as "new".
  const hasNonNew = pills.some((p) => p.type !== 'NEW_RISK')
  if (hasNonNew) {
    return pills.filter((p) => p.type !== 'NEW_RISK')
  }
  return pills
}

export function flagBadgesFor(row: UsdSwapTapeRow): Array<{
  key: string
  className: string
  label: string
  ariaLabel: string
}> {
  const badges: Array<{
    key: string
    className: string
    label: string
    ariaLabel: string
  }> = []
  if (row.is_block_any) {
    badges.push({
      key: 'BLK',
      className: FLAG_CHIP_TONES.BLK,
      label: 'BLK',
      ariaLabel: 'block trade',
    })
  }
  if (row.is_ufro_any) {
    badges.push({
      key: 'UFRO',
      className: FLAG_CHIP_TONES.UFRO,
      label: 'UFRO',
      ariaLabel: 'off-market rate',
    })
  }
  if (row.is_capped_any) {
    badges.push({
      key: 'CAP',
      className: FLAG_CHIP_TONES.CAPPED,
      label: 'CAP',
      ariaLabel: 'notional capped',
    })
  }
  if (row.is_off_date_any) {
    badges.push({
      key: 'ODT',
      className: FLAG_CHIP_TONES.OFF_DATE,
      label: '~',
      ariaLabel: 'off-date',
    })
  }
  return badges
}
