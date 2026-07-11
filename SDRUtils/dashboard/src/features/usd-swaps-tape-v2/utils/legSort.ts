// Shared leg-display ordering for the tape.
//
// The backend assigns a structure-aware `leg_order` per package: tenor for
// normal packages, forward-start for gap structures (same tail tenor), and
// effective date for FOMC-dated packages whose meeting periods have slightly
// different lengths. Sorting the UI by raw tenor scrambled FOMC curves
// ("SEP26/JUL26") and gap flies — always prefer `leg_order` and fall back to
// tenor-ascending only when the orders tie (e.g. manual-linked groups merge
// legs from different original packages, all with leg_order 0).
import type { UsdSwapTapeLeg } from '../types'

export function sortLegsForDisplay(
  legs: ReadonlyArray<UsdSwapTapeLeg>,
): UsdSwapTapeLeg[] {
  return [...legs].sort((a, b) => {
    const ao = typeof a?.leg_order === 'number' ? a.leg_order : null
    const bo = typeof b?.leg_order === 'number' ? b.leg_order : null
    if (ao !== null && bo !== null && ao !== bo) return ao - bo
    const at = typeof a?.tenor_years === 'number' ? a.tenor_years : Number.POSITIVE_INFINITY
    const bt = typeof b?.tenor_years === 'number' ? b.tenor_years : Number.POSITIVE_INFINITY
    return at - bt
  })
}
