// Derives a canonical FocusedTrade off the currently-selected tape row
// (or null when nothing is selected). Flattens leg-level fields up to the
// analytics surface so tabs can read fixed_rate_bps / dv01_usd_per_bp /
// notional_usd directly rather than walking legs_json every render.
import { useCallback, useMemo, useState } from 'react'
import type {
  FocusedTrade,
  PlatformKind,
} from '../components/AnalyticsPanel/analytics-types'
import type { UsdSwapTapeLeg, UsdSwapTapeRow } from '../types'

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

// Heuristic: venues like TULLETT / ICAP / TRADITION / BGC are interdealer.
// Anything else — TRADEWEB / BLOOMBERG / MARKETAXESS / direct — treat as
// dealer-to-client (custy). Mirrors the swaptions-tape isCustyPlatform logic
// without pulling in that package's types.
const IDB_VENUES = new Set([
  'TULLETT', 'TULLETT PREBON', 'ICAP', 'TRADITION', 'BGC', 'BGC PARTNERS',
  'DEALERWEB', 'IDB', 'BROKERTEC',
])

function inferPlatform(row: UsdSwapTapeRow | null): PlatformKind {
  if (!row) return 'IDB'
  const venue = String(row.venue ?? '').toUpperCase()
  if (IDB_VENUES.has(venue)) return 'IDB'
  // Broker keys can arrive as "tullett prebon" substrings too.
  for (const v of IDB_VENUES) if (venue.includes(v)) return 'IDB'
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
  const weightedRate = typeof row.weighted_fixed_rate === 'number'
    ? row.weighted_fixed_rate
    : typeof firstLeg?.fixed_rate === 'number'
      ? firstLeg.fixed_rate
      : 0
  // weighted_fixed_rate is a decimal (0.03842); the analytics surface
  // speaks basis points (384.2). Convert once at the boundary.
  const fixedRateBps = weightedRate * 10_000
  const tenorYears =
    typeof firstLeg?.tenor_years === 'number' ? firstLeg.tenor_years : 0
  const dv01 = aggregateLeg(legs, (l) => l.risk as number | null | undefined)
  const notional = aggregateLeg(legs, (l) => l.notional as number | null | undefined)
  const label =
    row.tape_label ?? row.package_tenors ?? String(row.package_type ?? 'USD-SOFR')
  const platform = inferPlatform(row)
  const side = inferSide(row)
  return {
    id: String(row.package_id ?? row.trade_id ?? 'UNKNOWN'),
    tape_label: label,
    package_structure: String(row.package_structure ?? row.package_type ?? 'OUTRIGHT'),
    package_tenors: row.package_tenors ?? null,
    trade_type: String(row.trade_type ?? row.package_type ?? 'OUTRIGHT'),
    tenor_years: tenorYears,
    fixed_rate_bps: +fixedRateBps.toFixed(2),
    weighted_fixed_rate: weightedRate,
    dv01_usd_per_bp: dv01,
    notional_usd: notional,
    side,
    platform,
    venue: String(row.venue ?? 'UNKNOWN'),
    execution_start: row.execution_start ?? row.execution_timestamp ?? null,
    execution_session: row.execution_session ?? null,
    lifecycle_type: (row.lifecycle_type as string | null) ?? null,
    is_block: Boolean(row.is_block_any),
    source: row,
  }
}

// Demo focused trade used when no row is selected — matches the
// prototype's mock so the dock looks populated out of the box.
const DEMO_FOCUSED: FocusedTrade = {
  id: 'USDS-10Y-DEMO',
  tape_label: 'USD-SOFR 10Y Outright',
  package_structure: 'OUTRIGHT',
  package_tenors: '10Y',
  trade_type: 'OUTRIGHT',
  tenor_years: 10,
  fixed_rate_bps: 384.2,
  weighted_fixed_rate: 0.03842,
  dv01_usd_per_bp: 150_000,
  notional_usd: 173_410_000,
  side: 'PAY',
  platform: 'IDB',
  venue: 'TRADEWEB',
  execution_start: null,
  execution_session: 'US',
  lifecycle_type: 'NEW_RISK',
  is_block: true,
}

export interface UseFocusedTradeReturn {
  focused: FocusedTrade | null
  setFocused: (row: UsdSwapTapeRow | null) => void
  setFocusedRaw: (f: FocusedTrade | null) => void
  clear: () => void
  // Convenience: returns demo trade when focused is null so the dock
  // always has something to render.
  focusedOrDemo: FocusedTrade
  isDemo: boolean
}

export function useFocusedTrade(initial?: UsdSwapTapeRow | null): UseFocusedTradeReturn {
  const [focused, setFocusedRaw] = useState<FocusedTrade | null>(
    initial ? normalizeFocusedTrade(initial) : null,
  )
  const setFocused = useCallback((row: UsdSwapTapeRow | null) => {
    setFocusedRaw(normalizeFocusedTrade(row))
  }, [])
  const clear = useCallback(() => setFocusedRaw(null), [])
  const focusedOrDemo = useMemo(() => focused ?? DEMO_FOCUSED, [focused])
  return {
    focused,
    setFocused,
    setFocusedRaw,
    clear,
    focusedOrDemo,
    isDemo: focused === null,
  }
}
