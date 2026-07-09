// ABOUTME: Tape-local display transform for manual overrides. Explodes SPLIT
// packages into per-leg rows, pulls DETACH legs out as standalone rows leaving
// a remnant, and clusters GROUP packages contiguously by reusing the shared
// groupLinkedRows ordering. Pure — never mutates input, never edits the shared
// grouping helper. Stamps __rowKind + __syntheticKey (dataKey) on every row.
import { groupLinkedRows } from '@/lib/manual-links-ui/grouping'
import type { UsdSwapTapeLeg, UsdSwapTapeRow } from '../types'

export type OverrideRowKind = 'normal' | 'split-leg' | 'detached'

export type DisplayRow = UsdSwapTapeRow & {
  __rowKind?: OverrideRowKind
  __syntheticKey?: string
}

function legKey(pkg: string, verb: 'split' | 'detach', leg: UsdSwapTapeLeg, i: number): string {
  const tid = leg?.trade_id
  return tid ? `${pkg}::${verb}::${tid}` : `${pkg}::${verb}::idx${i}`
}

/**
 * Resolve view-time override columns into render rows.
 * - GROUP: rows keep their shape; clustered contiguously (via groupLinkedRows).
 * - SPLIT: one synthetic row per leg, single-leg legs_json.
 * - DETACH: standalone row per detached leg + a remnant package row of the rest.
 */
export function applyOverrides(rows: UsdSwapTapeRow[]): DisplayRow[] {
  const transformed: DisplayRow[] = []

  for (const row of rows) {
    const legs = (row.legs_json ?? []) as UsdSwapTapeLeg[]
    const type = row.override_type ?? null

    if (type === 'SPLIT' && legs.length > 0) {
      legs.forEach((leg, i) => {
        transformed.push({
          ...row,
          legs_json: [leg],
          __rowKind: 'split-leg',
          __syntheticKey: legKey(row.package_id, 'split', leg, i),
        })
      })
      continue
    }

    if (type === 'DETACH') {
      const map = row.override_map ?? {}
      const detached: Array<{ leg: UsdSwapTapeLeg; i: number }> = []
      const remnant: UsdSwapTapeLeg[] = []
      legs.forEach((leg, i) => {
        if (leg?.trade_id && map[leg.trade_id]) detached.push({ leg, i })
        else remnant.push(leg)
      })
      // Defensive: nothing actually matched -> treat as a normal row.
      if (detached.length === 0) {
        transformed.push({ ...row, __rowKind: 'normal', __syntheticKey: row.package_id })
        continue
      }
      if (remnant.length > 0) {
        transformed.push({
          ...row,
          legs_json: remnant,
          __rowKind: 'normal',
          __syntheticKey: row.package_id,
        })
      }
      detached.forEach(({ leg, i }) => {
        transformed.push({
          ...row,
          legs_json: [leg],
          __rowKind: 'detached',
          __syntheticKey: legKey(row.package_id, 'detach', leg, i),
        })
      })
      continue
    }

    // GROUP or no override: pass through as a normal row (clustering handled below).
    transformed.push({ ...row, __rowKind: 'normal', __syntheticKey: row.package_id })
  }

  // Contiguously cluster GROUP rows sharing manual_package_id. groupLinkedRows
  // clusters by manual_package_id||manual_link_id and leaves everything else in
  // source order, so split/detach synthetic rows (manual_package_id null) stay put
  // and adjacent. Returns the same array reference when no clusters exist.
  return groupLinkedRows(transformed) as DisplayRow[]
}
