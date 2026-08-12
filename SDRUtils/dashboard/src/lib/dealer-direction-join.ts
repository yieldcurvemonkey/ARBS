// ABOUTME: Resolves whether the dealer-direction unit table is present, and
// the SELECT list / JOIN clause the tape route uses to hang direction off each
// rendered row.
//
// Probed rather than assumed, and cached for 60s like the display-view
// resolver, for one reason: the tape grid is the primary view of this app and
// it must not go dark because a new analytics table has not been created yet
// in some environment. When the table is absent the join is omitted and every
// dd_* field arrives undefined, which the grid already renders as an
// abstention.
//
// THE JOIN KEY IS package_id. Measured over five days spanning the whole tape,
// arbs_dd_unit_v1.package_id matches arbs_usd_swap_tape_display_v3.package_id
// 100.0000% in both directions, while unit_key — the dealer_direction module's
// own identity — matches only 21.7-29.3%, because a single-leg print that
// carries a package id is keyed by that id in the view and by its raw trade_id
// in unit_key. Both columns are stored; this is the one to join on.
import { query } from '@/lib/db'
import { DD_UNIT } from '@/lib/dealer-direction-tables'

/** Fields hung off each tape row. Prefixed dd_ so a future view column with
 *  the same name cannot collide silently. */
const DIRECTION_FIELDS: [string, string][] = [
  ['dealer_direction', 'dd_dealer_direction'],
  ['dealer_sign', 'dd_dealer_sign'],
  ['p', 'dd_p'],
  ['signed_weight', 'dd_signed_weight'],
  ['rule', 'dd_rule'],
  ['deviation_bps', 'dd_deviation_bps'],
  ['tau_bps', 'dd_tau_bps'],
  ['in_dead_zone', 'dd_in_dead_zone'],
  ['exclusion_reason', 'dd_exclusion_reason'],
  ['exclusion_detail', 'dd_exclusion_detail'],
  ['venue_class', 'dd_venue_class'],
  ['series', 'dd_series'],
  ['total_delta_dv01', 'dd_total_delta_dv01'],
  ['total_dv01_if_received', 'dd_total_dv01_if_received'],
  ['visibility_timestamp', 'dd_visibility_timestamp'],
  ['visibility_lag_seconds', 'dd_visibility_lag_seconds'],
  ['visibility_source', 'dd_visibility_source'],
  ['curve_name', 'dd_curve_name'],
  ['curve_timestamp', 'dd_curve_timestamp'],
  ['snapshot_lag_seconds', 'dd_snapshot_lag_seconds'],
  ['snapshot_policy', 'dd_snapshot_policy'],
  ['notional_imputed', 'dd_notional_imputed'],
  ['code_vintage', 'dd_code_vintage'],
  ['tape_generation', 'dd_tape_generation'],
]

export type DirectionJoin = {
  present: boolean
  /** ", dd.x AS dd_x, ..." or "" */
  columns: string
  /** "LEFT JOIN ... ON ..." or "" */
  join: string
}

const ABSENT: DirectionJoin = { present: false, columns: '', join: '' }

export function __buildDirectionJoin(): DirectionJoin {
  const columns = DIRECTION_FIELDS.map(([col, alias]) => `dd.${col} AS ${alias}`)
  return {
    present: true,
    columns: `, ${columns.join(', ')}`,
    // package_id is the display view's grain and arbs_dd_unit_v1's primary
    // key, so this is a one-row index lookup per rendered row.
    join: `LEFT JOIN ${DD_UNIT} dd ON dd.package_id = d.package_id`,
  }
}

let cached: DirectionJoin | null = null
let cachedAt = 0
const CACHE_TTL_MS = 60_000

export async function resolveDirectionJoin(): Promise<DirectionJoin> {
  const now = Date.now()
  if (cached && now - cachedAt < CACHE_TTL_MS) return cached
  try {
    const res = await query<{ rel: string | null }>(
      'SELECT to_regclass($1) AS rel',
      [DD_UNIT],
    )
    cached = res.rows[0]?.rel ? __buildDirectionJoin() : ABSENT
  } catch {
    // A probe failure must not take the tape down with it.
    cached = ABSENT
  }
  cachedAt = now
  return cached
}

/** Reset the module-level cache; test-only hook. */
export function __resetDirectionCache() {
  cached = null
  cachedAt = 0
}
