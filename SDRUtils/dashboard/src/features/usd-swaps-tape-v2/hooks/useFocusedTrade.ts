// Derives a canonical FocusedTrade off the currently-selected tape row
// (or null when nothing is selected). Flattens leg-level fields up to the
// analytics surface so tabs can read fixed_rate_bps / dv01_usd_per_bp /
// notional_usd directly rather than walking legs_json every render.
import { useCallback, useState } from 'react'
import type {
  FocusedTrade,
  PlatformKind,
} from '../components/AnalyticsPanel/analytics-types'
import { computeLegSummary } from '../components/TradeTapeTable/LegsSubTable.helpers'
import type { UsdSwapTapeLeg, UsdSwapTapeRow } from '../types'
import { computePackageConfidence } from '../utils/packageConfidence'

function aggregateLeg<T extends number | null | undefined>(
  legs: UsdSwapTapeLeg[] | undefined,
  pick: (l: UsdSwapTapeLeg) => T,
): number {
  if (!legs || legs.length === 0) return 0
  let sum = 0
  for (const l of legs) {
    const v = pick(l)
    if (typeof v === 'number' && Number.isFinite(v)) sum += Math.abs(v)
  }
  return sum
}

function absRowNumber(value: number | null | undefined): number | null {
  if (typeof value !== 'number' || !Number.isFinite(value)) return null
  return Math.abs(value)
}

// Mirrors the server-side platformCaseSql in lib/usd-swaps-tape-v2/analytics.ts:
// D2D venue → IDB, else MIC code lookup, else custy. Dealer MIC list
// is authoritative — see the comment in analytics.ts for the SEF
// breakdown (BGC / Dealerweb / ICAP-Global × 2 / TP / Tradition).
const IDB_MICS = new Set(['BGCD', 'DWSF', 'IGDL', 'ISWV', 'TPSE', 'TSEF'])

function inferPlatform(row: UsdSwapTapeRow | null): PlatformKind {
  if (!row) return 'CUSTY'
  const venue = String(row.venue ?? '').toUpperCase()
  if (venue === 'D2D') return 'IDB'
  const mic = String(
    row.platform_identifier ?? row.legs_json?.[0]?.platform_identifier ?? '',
  ).toUpperCase()
  if (IDB_MICS.has(mic)) return 'IDB'
  return 'CUSTY'
}

function inferSide(row: UsdSwapTapeRow | null): 'PAY' | 'RCV' {
  if (!row) return 'PAY'
  // The leg-level direction isn't always projected; fall back to a rate
  // sign heuristic (rare) → default PAY.
  const legs = row.legs_json ?? []
  for (const l of legs) {
    const dir = ((l as unknown as { direction?: string }).direction ?? '').toUpperCase()
    if (dir === 'PAY' || dir === 'RCV') return dir
  }
  return 'PAY'
}

export function normalizeFocusedTrade(row: UsdSwapTapeRow | null): FocusedTrade | null {
  if (!row) return null
  const legs = row.legs_json ?? []
  const firstLeg = legs[0]
  const legSummary = computeLegSummary(row)
  const summaryRate = typeof legSummary.rate === 'number' && Number.isFinite(legSummary.rate)
    ? legSummary.rate
    : null
  const weightedRate = summaryRate ??
    (typeof row.weighted_fixed_rate === 'number'
      ? row.weighted_fixed_rate
      : typeof firstLeg?.fixed_rate === 'number'
        ? firstLeg.fixed_rate
        : 0)
  // weighted_fixed_rate is a decimal (0.03842); the analytics surface
  // speaks basis points (384.2). Convert once at the boundary.
  const fixedRateBps = weightedRate * 10_000
  const tenorYears =
    typeof firstLeg?.tenor_years === 'number' ? firstLeg.tenor_years : 0
  const dv01 =
    absRowNumber(legSummary.risk) ??
    absRowNumber(row.total_risk) ??
    absRowNumber(row.gross_risk) ??
    aggregateLeg(legs, (l) => l.risk as number | null | undefined)
  const notional =
    absRowNumber(row.total_notional) ??
    absRowNumber(row.gross_notional) ??
    aggregateLeg(legs, (l) => l.notional as number | null | undefined)
  const label =
    row.tape_label ?? row.package_tenors ?? String(row.package_type ?? 'USD-SOFR')
  const platform = inferPlatform(row)
  const side = inferSide(row)
  const legLifecycle = firstLeg?.lifecycle_type ?? null
  const confidence = computePackageConfidence(row)
  const analyticsTradeType = String(
    confidence.inferredType ?? row.trade_type ?? row.package_type ?? 'OUTRIGHT',
  )
  return {
    id: String(row.package_id ?? 'UNKNOWN'),
    tape_label: label,
    package_structure: String(row.package_structure ?? row.package_type ?? 'OUTRIGHT'),
    package_tenors: row.package_tenors ?? null,
    trade_type: analyticsTradeType,
    tenor_years: tenorYears,
    fixed_rate_bps: +fixedRateBps.toFixed(2),
    weighted_fixed_rate: weightedRate,
    dv01_usd_per_bp: dv01,
    notional_usd: notional,
    side,
    platform,
    venue: String(row.venue ?? 'UNKNOWN'),
    execution_start: row.execution_start ?? null,
    execution_session: row.execution_session ?? null,
    lifecycle_type: legLifecycle,
    is_block: Boolean(row.is_block_any),
    source: row,
  }
}

export interface UseFocusedTradeReturn {
  focused: FocusedTrade | null
  setFocused: (row: UsdSwapTapeRow | null) => void
  setFocusedRaw: (f: FocusedTrade | null) => void
  clear: () => void
}

export function useFocusedTrade(initial?: UsdSwapTapeRow | null): UseFocusedTradeReturn {
  const [focused, setFocusedRaw] = useState<FocusedTrade | null>(
    initial ? normalizeFocusedTrade(initial) : null,
  )
  const setFocused = useCallback((row: UsdSwapTapeRow | null) => {
    setFocusedRaw(normalizeFocusedTrade(row))
  }, [])
  const clear = useCallback(() => setFocusedRaw(null), [])
  return { focused, setFocused, setFocusedRaw, clear }
}
