// ABOUTME: SWR cache key constructors for the three analytics-dock
// routes. Keys are deeply composite (route + bucket + view + range +
// groupBy + groupValueOverride + optionsHash) so future option fields
// can be added without invalidating the schema. Orthogonal display
// toggles (useGrossDv01, excludeLargeCusty) are stripped before
// hashing — they don't change the warehouse query result, only how
// the client renders it.
//
// Note: rarity and extremes have no analogous orthogonal toggles
// today; their option-bag entries (lookback, primaryTol, sizeTol,
// binMetric) all change which rows / aggregations the warehouse
// returns and therefore must remain in the cache key.
//
// Hash is FNV-1a 32-bit (sync, isomorphic) — this file is imported
// by client code (useAnalyticsPrefetch) so node:crypto is unavailable.
// Cache-key hashing has no security requirement.

export type AnalyticsCacheKey = readonly [
  namespace: 'usd-swaps-tape-v2',
  route: 'analytics-timeseries' | 'rarity' | 'extremes',
  bucket: string,
  view: string | null,
  range: string,
  groupBy: string,
  groupValueOverride: string | null,
  optionsHash: string,
]

const ORTHOGONAL_DISPLAY_OPTIONS = new Set<string>([
  'useGrossDv01',
  'excludeLargeCusty',
])

function fnv1a32(input: string): string {
  let h = 0x811c9dc5
  for (let i = 0; i < input.length; i++) {
    h ^= input.charCodeAt(i)
    h = Math.imul(h, 0x01000193) >>> 0
  }
  return h.toString(16).padStart(8, '0')
}

function hashOptions(options: Record<string, unknown>): string {
  const filtered = Object.entries(options)
    .filter(([k]) => !ORTHOGONAL_DISPLAY_OPTIONS.has(k))
    .sort(([a], [b]) => a.localeCompare(b))
  return fnv1a32(JSON.stringify(filtered))
}

export interface TimeseriesKeyArgs {
  bucket: string
  view: 'INTRADAY' | 'DAILY_CLOSE' | 'DAILY_OHLC' | 'VOLUME'
  range: '1D' | '1W' | '1M' | '1Y' | 'CUSTOM' | string
  groupBy: string
  groupValueOverride: string | null
  options: Record<string, unknown>
}

export function timeseriesKey(a: TimeseriesKeyArgs): AnalyticsCacheKey {
  return [
    'usd-swaps-tape-v2',
    'analytics-timeseries',
    a.bucket,
    a.view,
    a.range,
    a.groupBy,
    a.groupValueOverride,
    hashOptions(a.options),
  ] as const
}

export interface RarityKeyArgs {
  bucket: string
  groupBy: string
  groupValueOverride: string | null
  options: Record<string, unknown>
}

export function rarityKey(a: RarityKeyArgs): AnalyticsCacheKey {
  return [
    'usd-swaps-tape-v2',
    'rarity',
    a.bucket,
    null,
    '1Y',
    a.groupBy,
    a.groupValueOverride,
    hashOptions(a.options),
  ] as const
}

export interface ExtremesKeyArgs {
  bucket: string
  groupBy: string
  groupValueOverride: string | null
  options: Record<string, unknown>
}

export function extremesKey(a: ExtremesKeyArgs): AnalyticsCacheKey {
  return [
    'usd-swaps-tape-v2',
    'extremes',
    a.bucket,
    null,
    '1Y',
    a.groupBy,
    a.groupValueOverride,
    hashOptions(a.options),
  ] as const
}
