// ABOUTME: Pure helpers for the dealer risk-bucket ladder panel — the
// diverging z ramp, formatting, and the guard that keeps a cross-bucket level
// comparison from being drawable. No React, no fetch, so all of it is testable
// directly.
import {
  DIRECTION_AMBER,
  DIRECTION_NEUTRAL,
  DIRECTION_SKY,
} from '../../utils/dealerDirection'

/** indicator.TENOR_BUCKETS, in the canonical order. The panel always renders
 *  buckets in THIS order — never sorted by value, which would turn the
 *  cross-bucket z view into a ranking and invite the level reading it exists
 *  to avoid. */
export const TENOR_BUCKETS = [
  '0-1Y', '1-2Y', '2-3Y', '3-5Y', '5-7Y',
  '7-10Y', '10-15Y', '15-20Y', '20-30Y', '30Y+',
] as const
export type TenorBucket = (typeof TENOR_BUCKETS)[number]

export const VENUE_CLASSES = ['D2C', 'D2D', 'VENUE_UNKNOWN'] as const
export type VenueClass = (typeof VENUE_CLASSES)[number]

export const VENUE_LABEL: Record<VenueClass, string> = {
  D2C: 'D2C — customer flow',
  D2D: 'D2D — the street recycling',
  VENUE_UNKNOWN: 'venue unknown',
}

export const SERIES_OPTIONS = ['FLOW', 'LIFECYCLE'] as const
export type SeriesName = (typeof SERIES_OPTIONS)[number]

/** indicator._slug */
export function slug(bucket: string): string {
  return bucket.replace(/-/g, '_').replace(/\+/g, 'plus')
}

/** The level arrives bucket-suffixed on the wire, exactly as Python names it. */
export function levelKey(bucket: string, basis: 'raw' | 'cov_adj' | 'gross' = 'raw'): string {
  const base =
    basis === 'raw' ? 'delta_dv01' : basis === 'cov_adj' ? 'delta_dv01_cov_adj' : 'abs_dv01'
  return `${base}__${slug(bucket)}`
}

export function num(v: unknown): number | null {
  if (v == null || v === '') return null
  const n = Number(v)
  return Number.isFinite(n) ? n : null
}

// ---------------------------------------------------------------------------
// The diverging ramp
// ---------------------------------------------------------------------------
//
// Two hues and a NEUTRAL GREY midpoint — never a hue at zero, never a rainbow.
// Magnitude is carried by how far the cell has travelled from the grey, so a
// quiet day is quiet rather than merely a different colour.
//
// Clamped at |z| = 3. Past that the colour stops moving and the number is
// shown instead: a ramp that keeps darkening implies a precision the tail of a
// 250-observation window does not have.
export const Z_CLAMP = 3

function hexToRgb(hex: string): [number, number, number] {
  const h = hex.replace('#', '')
  return [
    parseInt(h.slice(0, 2), 16),
    parseInt(h.slice(2, 4), 16),
    parseInt(h.slice(4, 6), 16),
  ]
}

function mix(a: string, b: string, t: number): string {
  const [ar, ag, ab] = hexToRgb(a)
  const [br, bg, bb] = hexToRgb(b)
  const r = Math.round(ar + (br - ar) * t)
  const g = Math.round(ag + (bg - ag) * t)
  const bl = Math.round(ab + (bb - ab) * t)
  return `rgb(${r}, ${g}, ${bl})`
}

/** z -> a colour on the sky/amber diverging scale. null -> transparent. */
export function zColor(z: number | null): string {
  if (z == null) return 'transparent'
  const t = Math.min(Math.abs(z) / Z_CLAMP, 1)
  return mix(DIRECTION_NEUTRAL, z >= 0 ? DIRECTION_SKY : DIRECTION_AMBER, t)
}

/** Legible ink on top of a cell of that colour. */
export function zInk(z: number | null): string {
  if (z == null) return '#475569'
  return Math.abs(z) / Z_CLAMP > 0.55 ? '#0f172a' : '#cbd5e1'
}

export function fmtZ(z: number | null): string {
  return z == null ? '—' : (z >= 0 ? '+' : '') + z.toFixed(1)
}

export function fmtPct(x: number | null, digits = 0): string {
  return x == null ? '—' : `${(x * 100).toFixed(digits)}%`
}

/** Signed USD/bp, compact. The sign is the point, so it is never dropped. */
export function fmtSignedDv01(v: number | null): string {
  if (v == null) return '—'
  const a = Math.abs(v)
  const sign = v > 0 ? '+' : v < 0 ? '−' : ''
  if (a >= 1e6) return `${sign}${(a / 1e6).toFixed(2)}MM`
  if (a >= 1e3) return `${sign}${(a / 1e3).toFixed(0)}K`
  return `${sign}${a.toFixed(0)}`
}

// ---------------------------------------------------------------------------
// The guard
// ---------------------------------------------------------------------------

export class CrossBucketLevelComparison extends Error {}

/**
 * Refuse a frame that would let a level be plotted across buckets.
 *
 * The panel calls this on anything it is about to hand to a chart that has
 * `bucket_key` as a category. The Python module refuses the same thing by
 * naming the level column for its bucket; on this side the naming survives the
 * wire (delta_dv01__5_7Y), so the check is: if rows carry more than one bucket
 * AND any key looks like a level, refuse.
 *
 * A comment saying "don't do this" is not a control. This throws.
 */
export function assertNotCrossBucketLevel(rows: Record<string, unknown>[]): void {
  const buckets = new Set(rows.map((r) => String(r.bucket_key ?? '')))
  buckets.delete('')
  if (buckets.size <= 1) return
  for (const row of rows) {
    for (const key of Object.keys(row)) {
      if (/^(delta_dv01|abs_dv01)/.test(key)) {
        throw new CrossBucketLevelComparison(
          `${buckets.size} buckets in one frame carrying the level key ${key}. ` +
            'DV01 retention runs 0.761 at 0-1Y against 0.495 at 15-20Y — a ' +
            '1.54x scaling distortion — because the packages the classifier ' +
            'cannot orient are not a random sample. "The 5y bucket against ' +
            'its own history" is supportable; "dealers are longer 5y than ' +
            '10y" is not. Use z, which is exactly invariant to a constant ' +
            'retention factor.',
        )
      }
    }
  }
}

// ---------------------------------------------------------------------------
// Shapes returned by /api/usd-swaps-tape-v2/direction/*
// ---------------------------------------------------------------------------

export type StandardisedRow = {
  bucket_key: string
  visibility_date: string
  observed: boolean
  z_raw: number | string | null
  z_cov_adj: number | string | null
  pct_raw: number | string | null
  z_n_obs: number | string | null
  n_units: number | string | null
  mean_abs_signed_weight: number | string | null
  coverage_frac: number | string | null
  /** The trailing 63-session mean. What the adjusted basis divides by, and
   *  what the panel shows, because the day's own fraction moves >25% on a
   *  quarter to two-thirds of days and that is composition, not coverage. */
  coverage_smooth: number | string | null
  coverage_drift_flag: boolean | null
  coverage_trend_pp_per_yr: number | string | null
  coverage_drift_source: string | null
  frac_dv01_block: number | string | null
  frac_dv01_capped: number | string | null
  frac_dv01_dead_zone: number | string | null
}

export type BucketRow = Record<string, unknown> & {
  visibility_date: string
  observed: boolean
  coverage_frac: number | string | null
  n_units: number | string | null
}

export type CoverageRow = {
  bucket_key?: string
  reason: string
  n_units: number | string
  dv01: number | string
  dv01_share: number | string | null
  in_ladder: boolean
}

export type LadderSummary = {
  first_day: string | null
  last_day: string | null
  kept: number | string | null
  total: number | string | null
  coverage_frac: number | string | null
  n_units: number | string | null
  n_called: number | string | null
  last_as_of: string | null
  code_vintage: string | null
  tape_generation: string | null
}

/** Latest observed date present in a standardised payload. */
export function latestDate(rows: StandardisedRow[]): string | null {
  let last: string | null = null
  for (const r of rows) {
    const d = String(r.visibility_date).slice(0, 10)
    if (last === null || d > last) last = d
  }
  return last
}

/** The last `n` distinct dates, oldest first — the heatmap's x axis. */
export function recentDates(rows: StandardisedRow[], n: number): string[] {
  const all = [...new Set(rows.map((r) => String(r.visibility_date).slice(0, 10)))].sort()
  return all.slice(Math.max(0, all.length - n))
}

export type HeatmapState = 'ready' | 'loading' | 'empty'

/**
 * Why the heatmap has no columns — because "no columns" must never render as a
 * bare empty row.
 *
 * OBSERVED, and the reason this exists: /standardised returns 6,290 rows over
 * the full window and takes long enough that a screenshot taken 2.5s after the
 * Analytics tab opens catches the panel mid-flight. It rendered ten labelled
 * bucket rows, each with an empty strip and an em-dash where z goes — which is
 * pixel-for-pixel what "we have no data for you" looks like. On a panel whose
 * governing rule is that an abstention is information rather than a blank, an
 * in-flight fetch that renders as an empty ladder is the same defect wearing a
 * different hat.
 *
 * A bare `loading` boolean is not enough on its own: loading=false with no
 * dates is a genuinely empty window, and it needs a different sentence.
 */
export function heatmapState(loading: boolean, dates: string[]): HeatmapState {
  if (dates.length > 0) return 'ready'
  return loading ? 'loading' : 'empty'
}

/** (bucket, date) -> row, for O(1) heatmap lookup. */
export function indexByBucketDate(
  rows: StandardisedRow[],
): Map<string, StandardisedRow> {
  const m = new Map<string, StandardisedRow>()
  for (const r of rows) {
    m.set(`${r.bucket_key}|${String(r.visibility_date).slice(0, 10)}`, r)
  }
  return m
}
