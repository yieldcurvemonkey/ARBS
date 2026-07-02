// ABOUTME: Resolver for the USD swap tape v2 display view and column list.
import { query } from '@/lib/db'
import { TAPE_DISPLAY_VIEW } from '@/app/api/usd-swaps-tape-v2/route.logic'

// Phase 4 cutover: DISPLAY_VIEW reads from the Phase-4 constant. v1 is
// preserved frozen; to roll back, flip TAPE_DISPLAY_VIEW in route.logic.ts.
export const DISPLAY_VIEW = TAPE_DISPLAY_VIEW
export const PACKAGES_TABLE = 'arbs_usd_swap_tape_packages_v2'
export const LEGS_TABLE = 'arbs_usd_swap_tape_legs_v2'

// Audit C1 prevention: the old hard-coded COLUMNS allowlist silently
// dropped every new view column (the whole PTP feature shipped invisible).
// Project ALL view columns except explicit exclusions, so the failure mode
// of forgetting registration becomes harmless over-inclusion. Excluded
// columns are ones the client derives itself or never reads.
export const EXCLUDED_VIEW_COLUMNS = new Set<string>([
  // seed from Step 1's live diff — keep this comment-annotated:
  'is_off_market_any',      // client-side derived signal
  'confidence_score',       // internal scoring — not surfaced in UI
  'confidence_total',       // internal scoring — not surfaced in UI
  'confidence_tone',        // internal scoring — not surfaced in UI
  'confidence_signals',     // internal scoring — not surfaced in UI
  'summary_rate',           // pre-computed summary — not surfaced in UI
  'summary_risk',           // pre-computed summary — not surfaced in UI
  'summary_opa',            // pre-computed summary — not surfaced in UI
  'is_ccp_switch',          // CCP switch flag — not surfaced in UI
  'ccp_switch_from',        // CCP switch detail — not surfaced in UI
  'ccp_switch_to',          // CCP switch detail — not surfaced in UI
  'package_adjusted_dv01',  // excluded: payload unchanged; client recomputes a fallback via computePackageAdjustedDv01() (columns.tsx ~406, underlierMix.ts ~46); un-excluding is a deliberate future decision
  'normalized_tape_label',  // internal label normalization — not surfaced in UI
  'tape_tags',              // excluded: payload unchanged; UI reads tape_label regex + bool flags as fallback (RowBadges.helpers.ts ~322); un-excluding is a deliberate future decision (needs Chrome + jest verification)
])

/** Test-only pure helper. */
export function __projectColumns(viewColumns: string[]): string[] {
  return viewColumns
    .filter((c) => !EXCLUDED_VIEW_COLUMNS.has(c))
    .map((c) => `d.${c}`)
}

export type TapeDisplayView = {
  view: string
  columns: string
}

let cached: TapeDisplayView | null = null
let cachedAt = 0
const CACHE_TTL_MS = 60_000

export async function resolveDisplayView(): Promise<TapeDisplayView> {
  const now = Date.now()
  if (cached && now - cachedAt < CACHE_TTL_MS) {
    return cached
  }
  const [result, present] = await Promise.all([
    query<{ rel: string | null }>(
      'SELECT to_regclass($1) AS rel',
      [DISPLAY_VIEW],
    ),
    query<{ column_name: string }>(
      `SELECT column_name FROM information_schema.columns
       WHERE table_name = $1 AND table_schema = current_schema()`,
      [DISPLAY_VIEW],
    ),
  ])
  if (!result.rows[0]?.rel) {
    throw new Error(
      `tape display view ${DISPLAY_VIEW} not found — run ingest_usdswaps_tape`,
    )
  }
  const projected = __projectColumns(present.rows.map((r) => r.column_name))
  cached = { view: DISPLAY_VIEW, columns: projected.join(', ') }
  cachedAt = now
  return cached
}

/** Reset the module-level cache; test-only hook. */
export function __resetCache() {
  cached = null
  cachedAt = 0
}
