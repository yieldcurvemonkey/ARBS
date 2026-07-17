// ABOUTME: Pure aggregation helpers for the unrecognised-underliers
// watchdog (design-doc §5.19). The route fetches recent legs and
// passes them in; this file owns the canonical-key whitelist + the
// per-raw-string rollup so the logic is easy to unit-test.

import { CANONICAL_BUCKETS } from '@/features/usd-swaps-tape-v2/utils/canonicalDisplay'

const RECOGNISED_KEYS = new Set<string>(CANONICAL_BUCKETS.map((b) => b.key))

export function isUnrecognisedCanonicalKey(key: string | null | undefined): boolean {
  if (!key) return true
  if (key === 'UNKNOWN') return true
  return !RECOGNISED_KEYS.has(key)
}

export type UnrecognisedRow = {
  floating_rate_index: string | null
  canonical_underlier_key: string | null
  notional: number | null
  // Coalesced original-execution anchor (was misleadingly named
  // execution_timestamp on the wire; 2026-07-17 anchor unification).
  anchor_ts: string | null
}

export type UnrecognisedAggregate = {
  floating_rate_index: string
  count: number
  totalNotional: number
  firstSeen: string
  lastSeen: string
}

export function aggregateUnrecognisedUnderliers(
  rows: readonly UnrecognisedRow[],
): UnrecognisedAggregate[] {
  const map = new Map<
    string,
    { count: number; totalNotional: number; firstSeen: number; lastSeen: number }
  >()
  for (const row of rows) {
    if (!isUnrecognisedCanonicalKey(row.canonical_underlier_key)) continue
    const raw = row.floating_rate_index
    if (!raw) continue
    const ts = row.anchor_ts ? Date.parse(row.anchor_ts) : NaN
    const tsMs = Number.isFinite(ts) ? ts : 0
    const notional = Math.abs(Number(row.notional ?? 0))
    const existing = map.get(raw) ?? {
      count: 0,
      totalNotional: 0,
      firstSeen: Number.POSITIVE_INFINITY,
      lastSeen: Number.NEGATIVE_INFINITY,
    }
    existing.count += 1
    existing.totalNotional += notional
    if (tsMs && tsMs < existing.firstSeen) existing.firstSeen = tsMs
    if (tsMs && tsMs > existing.lastSeen) existing.lastSeen = tsMs
    map.set(raw, existing)
  }
  const out: UnrecognisedAggregate[] = []
  for (const [key, agg] of map.entries()) {
    out.push({
      floating_rate_index: key,
      count: agg.count,
      totalNotional: agg.totalNotional,
      firstSeen:
        Number.isFinite(agg.firstSeen) && agg.firstSeen > 0
          ? new Date(agg.firstSeen).toISOString()
          : '',
      lastSeen:
        Number.isFinite(agg.lastSeen) && agg.lastSeen > 0
          ? new Date(agg.lastSeen).toISOString()
          : '',
    })
  }
  out.sort((a, b) => b.totalNotional - a.totalNotional)
  return out
}
