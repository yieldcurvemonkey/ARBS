// ABOUTME: Pure helpers for the intraday traded-prints panel — the mid
// reconstruction, the gap rule that stops it reading as a quote, the y-domain
// that off-market prints may not enter, and the direction encoding. No React,
// no fetch, so every rule below is testable directly.
//
// ===================================================================
// THE SIGN CONVENTION, AND WHY directionOf DOES NOT RECOMPUTE IT
// ===================================================================
//
//   customer pays fixed -> dealer RECEIVED fixed -> dealer long duration
//   p = p(customer paid fixed);  weight = signed_weight = 2p - 1  (NEVER p)
//
// The classifier's call is sign(deviation_bps - mid_bias_bps), NOT
// sign(deviation_bps): b0 is a fitted per-day mid bias, and near mid the two
// disagree. Measured rows exist where dealer_direction = 'PAID' with
// deviation_bps = +0.0100 while b0 = +0.013. So directionOf reads the server's
// dealer_direction and never re-derives it — a re-derivation from the sign of
// the deviation alone would invert exactly those prints, and it would look
// completely plausible doing it. (|b0| <= 0.015bp, so sky-above-mid /
// amber-below-mid still holds to sub-pixel; a near-mid PAID print sitting a
// hair above the mid line is that, not an inversion bug.)
import {
  DIRECTION_AMBER,
  DIRECTION_NEUTRAL,
  DIRECTION_SKY,
} from '../../utils/dealerDirection'

// ---------------------------------------------------------------------------
// Wire types — the shape served by /api/usd-swaps-tape-v2/direction/prints.
// prints.logic.ts is the source of truth; these mirror it for the client.
// ---------------------------------------------------------------------------

export type PrintKind = 'OUTRIGHT' | 'CURVE' | 'FLY' | 'PKG'

export type PrintRow = {
  package_id: string
  trade_id: string
  execution_timestamp: string
  visibility_timestamp: string | null
  visibility_lag_seconds: number | null
  dealer_direction: 'RECEIVED' | 'PAID' | 'ABSTAINED'
  dealer_sign: number | null
  p: number | null
  signed_weight: number | null
  deviation_bps: number
  tau_bps: number | null
  mid_bias_bps: number | null
  in_dead_zone: boolean | null
  kind: PrintKind
  n_legs: number
  rule: string
  special_tenor_type: string
  rate_index: string
  venue_class: string
  is_block: boolean | null
  is_capped: boolean | null
  notional_imputed: boolean | null
  structure_dv01: number | null
  notional: number | null
  is_notional_capped: boolean | null
  effective_date: string
  expiration_date: string
  tenor_years: number
  tenor_display: string
  forward_start_years: number | null
  forward_label: string | null
  is_off_market: boolean | null
  traded_pct: number
  mid_pct: number | null
  curve_name: string | null
  curve_timestamp: string | null
  snapshot_lag_seconds: number | null
  snapshot_policy: string | null
  tape_generation: string | null
  code_vintage: string | null
}

export type PrintsCounts = {
  /** Rows actually returned — includes the off-market ones when they are shown. */
  drawn: number
  /** The on-market population, measured; toggle-invariant, so it is the
   *  denominator every share on screen is taken over. */
  onMarket: number
  withMid: number
  dropped: {
    offMarket: number
    forwardStart: number
    specialTenorType: number
    unknownSpecialTenorType: number
    packageLegs: number
  }
}

export type PrintsProvenance = {
  curve_name: string | null
  snapshot_policy: string | null
  median_snapshot_lag_seconds: number | null
  median_visibility_lag_seconds: number | null
  max_visibility_lag_seconds: number | null
  dead_zone_share: number
  size_not_read: number
  tape_generation: string
  code_vintage: string
  dd_generation: string
}

export type PrintsResponse = {
  date: string
  tenor: string
  rateIndex: string
  venueClass: string
  series: 'FLOW'
  clock: 'execution'
  filters: {
    kinds: PrintKind[]
    specialTenorTypes: string[]
    fwdMaxYears: number
    tenorMatch: 'strict' | 'band'
    includeOffMarket: boolean
  }
  looseTenor: boolean
  admittedByLoosening: number | null
  observedTenorYears: [number, number] | null
  rows: PrintRow[]
  mid: MidGrid
  counts: PrintsCounts
  disclosures: string[]
  provenance: PrintsProvenance
  error?: string
}

export type MidGridPoint = { ts: string; mid_pct: number }

export type MidGrid = {
  available: boolean
  points: MidGridPoint[]
  curve_name: string | null
  snapshot_policy: string | null
  window: [string, string] | null
}

export const PRINT_TENORS = ['1Y', '2Y', '3Y', '5Y', '7Y', '10Y', '20Y', '30Y'] as const
export const RATE_INDEXES = ['SOFR', 'FED_FUNDS'] as const
export const VENUE_CLASSES = ['D2C', 'D2D', 'VENUE_UNKNOWN'] as const
export const PRINT_KINDS = ['OUTRIGHT', 'CURVE', 'FLY', 'PKG'] as const
export const FWD_MAX_DEFAULT = 0.02
/** Above this the API refuses: a 10y10y is not a 10Y, measured 66bp apart. */
export const FWD_MAX_CEILING = 0.25
export const FWD_MAX_OPTIONS = [0.02, 0.08, 0.25] as const

// ---------------------------------------------------------------------------
// The mid
// ---------------------------------------------------------------------------

/**
 * mid = traded - deviation/100. EXACT, not an approximation:
 * quote_weights('OUTRIGHT', 1, RULE_RATE) == (1.0,) and structure_price is
 * percent-in / bp-out, so deviation_bps === (traded_pct - mid_pct) * 100.
 */
export function midPct(tradedPct: number, deviationBps: number): number {
  return tradedPct - deviationBps / 100
}

/**
 * GAP_MINUTES — above this, no segment is drawn between two mid points.
 *
 * Measured gaps between consecutive clean prints on the reference day/tenor:
 * p50 5.0 min, p90 23.0 min, max 177.8 min. 20 minutes keeps the core session
 * joined and ALWAYS breaks the overnight hole, which is the point: the mid does
 * not exist between prints, and a segment drawn across three hours of nothing
 * is the chart inventing a quote.
 */
export const GAP_MINUTES = 20

/**
 * Below this the line is suppressed entirely and only the dots are drawn.
 *
 * Seven points joined by a dashed line still reads as a level through the day.
 * Seven dots read as seven observations, which is what they are.
 */
export const MIN_MID_POINTS = 12

export type MidPoint = { t: number; mid: number | null }

export function tsMillis(iso: string | null | undefined): number | null {
  if (!iso) return null
  const t = new Date(iso).getTime()
  return Number.isFinite(t) ? t : null
}

/**
 * Mid points in execution order, with an explicit null spacer wherever the gap
 * exceeds `gapMinutes`. Paired with recharts `connectNulls={false}` this breaks
 * the line rather than bridging it.
 *
 * A row with no mid_pct never contributes: the server emits null for every
 * package leg and every off-market print, and this must not paper over that.
 */
export function buildMidSeries(rows: PrintRow[], gapMinutes: number = GAP_MINUTES): MidPoint[] {
  const pts: MidPoint[] = []
  for (const r of rows) {
    if (r.mid_pct == null) continue
    if (r.is_off_market === true) continue // belt-and-braces; the SQL already nulls these
    const t = tsMillis(r.execution_timestamp)
    if (t == null) continue
    pts.push({ t, mid: Number(r.mid_pct) })
  }
  pts.sort((a, b) => a.t - b.t)

  const gapMs = gapMinutes * 60_000
  const out: MidPoint[] = []
  for (let i = 0; i < pts.length; i += 1) {
    const cur = pts[i]!
    if (i > 0) {
      const prev = pts[i - 1]!
      if (cur.t - prev.t > gapMs) {
        // The spacer sits between the two points so the break is where the
        // silence is, not attached to either print.
        out.push({ t: prev.t + Math.floor((cur.t - prev.t) / 2), mid: null })
      }
    }
    out.push(cur)
  }
  return out
}

// ---------------------------------------------------------------------------
// The continuous mid — the real one
// ---------------------------------------------------------------------------

/**
 * Above this, no segment is drawn between two consecutive GRID points.
 *
 * Measured on SOFR 10Y across 7 days spanning the window: intra-day consecutive
 * gaps are 1 min (8,293x), 2 min (170), 3 min (17), 4 min (1) and 5 min (1),
 * and no intra-day gap exceeds 5 minutes on any of the seven days. Every larger
 * gap is a jump between days — the overnight hole, ~2 hours at minimum. So 10
 * minutes never breaks a live session and always breaks the hole.
 *
 * Distinct from GAP_MINUTES, which is 20 because it governs the spacing between
 * PRINTS (p50 5.0 / p90 23.0 / max 177.8 min), a completely different process.
 */
export const MID_GRID_GAP_MINUTES = 10

/** Which object the line is drawn from. Shown on screen; never inferred. */
export type MidSource = 'grid' | 'reconstructed' | 'none'

/**
 * The grid as chart points, with an explicit null spacer at every break.
 *
 * Same contract as buildMidSeries — paired with `connectNulls={false}` the line
 * breaks rather than bridging — but the input is a modelled 1-minute curve
 * rather than a polyline through wherever somebody traded.
 */
export function buildGridMidSeries(
  points: MidGridPoint[],
  gapMinutes: number = MID_GRID_GAP_MINUTES,
): MidPoint[] {
  const pts: MidPoint[] = []
  for (const p of points) {
    const t = tsMillis(p.ts)
    if (t == null) continue
    const mid = Number(p.mid_pct)
    if (!Number.isFinite(mid)) continue
    pts.push({ t, mid })
  }
  pts.sort((a, b) => a.t - b.t)

  const gapMs = gapMinutes * 60_000
  const out: MidPoint[] = []
  for (let i = 0; i < pts.length; i += 1) {
    const cur = pts[i]!
    if (i > 0) {
      const prev = pts[i - 1]!
      if (cur.t - prev.t > gapMs) {
        out.push({ t: prev.t + Math.floor((cur.t - prev.t) / 2), mid: null })
      }
    }
    out.push(cur)
  }
  return out
}

/**
 * Which mid the line gets, and why.
 *
 * The grid wins whenever it has enough points, because it is a curve rather
 * than a join-the-dots. It is ABSENT for Fed Funds 7Y, 20Y and 30Y — measured,
 * the grid carries 12 FF tenors and 21 SOFR tenors — and on those the
 * reconstruction is the only line there is. Falling back silently would let a
 * reader take a polyline through eight prints for a picture of the market, so
 * the source is returned alongside the points and rendered as a label.
 */
export function chooseMidSeries(
  rows: PrintRow[],
  grid: MidGrid | null | undefined,
): { source: MidSource; points: MidPoint[] } {
  if (grid?.available && grid.points.length >= MIN_MID_POINTS) {
    return { source: 'grid', points: buildGridMidSeries(grid.points) }
  }
  const recon = buildMidSeries(rows)
  const n = recon.filter((m) => m.mid != null).length
  if (n >= MIN_MID_POINTS) return { source: 'reconstructed', points: recon }
  // Below the floor the dots stand alone — see MIN_MID_POINTS.
  return { source: 'none', points: recon }
}

export type MidResidual = {
  n: number
  medianBps: number
  p95Bps: number
  maxBps: number
}

/**
 * How far each mark's OWN mid sits from the line above it, in bp.
 *
 * The two are independent objects: the mark's mid is traded - deviation (exact
 * for that print, and what the direction call was made against), the line is
 * the 1-minute grid. They are matched on the minute of the print's own curve
 * snapshot, which is an EQUALITY — 0 of 22.7M grid rows carry a non-zero
 * second.
 *
 * This is a diagnostic on screen rather than a hidden check, because the
 * residual is real and nameable: it is ~0 for a spot STANDARD swap, which is
 * literally the same instrument as the grid point, and grows with the maturity
 * gap for a broken-dated one. A reader looking at a mark sitting off the line
 * deserves the number rather than a guess about whether the chart is broken.
 */
export function midGridResidual(
  rows: PrintRow[],
  points: MidGridPoint[],
): MidResidual | null {
  const byMinute = new Map<number, number>()
  for (const p of points) {
    const t = tsMillis(p.ts)
    if (t == null) continue
    byMinute.set(Math.floor(t / 60_000), Number(p.mid_pct))
  }
  const resid: number[] = []
  for (const r of rows) {
    if (r.mid_pct == null || r.is_off_market === true) continue
    const t = tsMillis(r.curve_timestamp)
    if (t == null) continue
    const g = byMinute.get(Math.floor(t / 60_000))
    if (g == null || !Number.isFinite(g)) continue
    resid.push((Number(r.mid_pct) - g) * 100)
  }
  if (resid.length === 0) return null
  const abs = resid.map((x) => Math.abs(x)).sort((a, b) => a - b)
  const sorted = [...resid].sort((a, b) => a - b)
  const q = (xs: number[], f: number) => xs[Math.min(xs.length - 1, Math.floor(f * xs.length))]!
  const m = Math.floor(sorted.length / 2)
  return {
    n: resid.length,
    medianBps: sorted.length % 2 ? sorted[m]! : (sorted[m - 1]! + sorted[m]!) / 2,
    p95Bps: q(abs, 0.95),
    maxBps: abs[abs.length - 1]!,
  }
}

// ---------------------------------------------------------------------------
// The axes
// ---------------------------------------------------------------------------

/** 1bp. A quiet tenor is quiet, not magnified into noise. */
export const MIN_Y_SPAN_PCT = 0.01
const Y_PAD = 0.08

/**
 * Rows that are allowed to set the y-axis.
 *
 * OFF-MARKET PRINTS ARE NEVER ADMITTED. A muted-but-plotted mark still owns the
 * domain, so muting does not solve the problem it appears to solve: on the
 * reference day/tenor, 11 off-market prints (8.4% of rows) stretch the traded
 * band from 5.9bp to 182bp — a 31x stretch from 8% of the rows. A print with an
 * upfront is off mid BY CONSTRUCTION; its position on a rate axis is not
 * information.
 *
 * Forward-starting prints beyond the current ceiling are excluded for the same
 * reason (measured 66bp away at 10Y). When the ceiling is deliberately raised
 * they ARE the view, so the domain recomputes around them — which is why the
 * ceiling is a parameter here rather than a constant.
 */
export function domainRows(rows: PrintRow[], fwdMaxYears: number = FWD_MAX_DEFAULT): PrintRow[] {
  return rows.filter(
    (r) =>
      r.is_off_market !== true &&
      Number(r.forward_start_years ?? 0) <= fwdMaxYears,
  )
}

/**
 * `mid` IS ADMITTED TO THE DOMAIN, unlike an off-market print.
 *
 * The grid runs 15 minutes past the last mark, and the mid can move inside that
 * pad. Excluded, the line would be silently clipped at the frame edge — which
 * reads as the mid going flat rather than as the axis ending. It is the same
 * instrument as the marks and it is on-market by construction, so it belongs.
 */
export function yDomain(
  rows: PrintRow[],
  fwdMaxYears: number = FWD_MAX_DEFAULT,
  mid: MidPoint[] = [],
): [number, number] | null {
  const vals: number[] = []
  for (const r of domainRows(rows, fwdMaxYears)) {
    if (Number.isFinite(r.traded_pct)) vals.push(Number(r.traded_pct))
    if (r.mid_pct != null && Number.isFinite(r.mid_pct)) vals.push(Number(r.mid_pct))
  }
  for (const m of mid) {
    if (m.mid != null && Number.isFinite(m.mid)) vals.push(m.mid)
  }
  if (vals.length === 0) return null
  let lo = Math.min(...vals)
  let hi = Math.max(...vals)
  if (hi - lo < MIN_Y_SPAN_PCT) {
    const mid = (hi + lo) / 2
    lo = mid - MIN_Y_SPAN_PCT / 2
    hi = mid + MIN_Y_SPAN_PCT / 2
  }
  const pad = (hi - lo) * Y_PAD
  return [lo - pad, hi + pad]
}

export type Pinned = 'top' | 'bottom' | null

/**
 * Where an off-domain mark is drawn, and whether it was moved.
 *
 * Off-market prints are shown (opt-in) without letting them own the axis: they
 * are pinned to the edge as hollow chevrons and the tooltip carries the TRUE
 * rate. "See that they exist without them distorting the eye", literally.
 */
export function clampToDomain(
  value: number,
  domain: [number, number] | null,
): { value: number; pinned: Pinned } {
  if (domain == null || !Number.isFinite(value)) return { value, pinned: null }
  const [lo, hi] = domain
  if (value < lo) return { value: lo, pinned: 'bottom' }
  if (value > hi) return { value: hi, pinned: 'top' }
  return { value, pinned: null }
}

/** Epoch-ms bounds across EVERY series — recharts computes its domain from
 *  chart-level data only, so a per-series domain would silently crop. */
export function tDomain(rows: PrintRow[], mid: MidPoint[]): [number, number] | null {
  const ts: number[] = []
  for (const r of rows) {
    const t = tsMillis(r.execution_timestamp)
    if (t != null) ts.push(t)
  }
  for (const m of mid) ts.push(m.t)
  if (ts.length === 0) return null
  return [Math.min(...ts), Math.max(...ts)]
}

// ---------------------------------------------------------------------------
// The ET clock
// ---------------------------------------------------------------------------

const NY_TZ = 'America/New_York'

const ET_DATE_FMT = new Intl.DateTimeFormat('en-CA', {
  timeZone: NY_TZ, year: 'numeric', month: '2-digit', day: '2-digit',
})
const ET_CLOCK_FMT = new Intl.DateTimeFormat('en-GB', {
  timeZone: NY_TZ, hour: '2-digit', minute: '2-digit', hour12: false,
})
const ET_STAMP_FMT = new Intl.DateTimeFormat('en-GB', {
  timeZone: NY_TZ, month: 'short', day: '2-digit',
  hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
})

/** 'YYYY-MM-DD' in New York. */
export function etDateOf(t: number): string {
  return ET_DATE_FMT.format(new Date(t))
}

/** 'HH:mm' in New York. */
export function fmtEtClock(t: number): string {
  return ET_CLOCK_FMT.format(new Date(t))
}

/** 'Jun 18, 14:03:22' in New York. */
export function fmtEtStamp(t: number | null): string {
  return t == null ? '—' : ET_STAMP_FMT.format(new Date(t))
}

/**
 * The instant ET midnight falls inside the plotted window, or null.
 *
 * as_of_date is the UTC calendar date of EXECUTION, and measured execution
 * spans run from ~20:0x ET the previous evening to ~19:5x ET — one contiguous
 * block — so the ET calendar date changes MID-CHART and the reader needs to see
 * where.
 *
 * Found by bisection on the formatted ET date, never by a hardcoded 19:00/20:00
 * offset: that boundary moves with DST (19:00 EST, 20:00 EDT) and a constant
 * would put the line in the wrong place for half the year.
 */
export function etMidnightFor(rows: PrintRow[]): number | null {
  const ts = rows
    .map((r) => tsMillis(r.execution_timestamp))
    .filter((x): x is number => x != null)
  if (ts.length < 2) return null
  let lo = Math.min(...ts)
  const hi = Math.max(...ts)
  const dLo = etDateOf(lo)
  if (dLo === etDateOf(hi)) return null
  let a = lo
  let b = hi
  // Bisect to the millisecond: ~27 halvings covers a day, 60 is free.
  for (let i = 0; i < 60 && b - a > 1; i += 1) {
    const m = a + Math.floor((b - a) / 2)
    if (etDateOf(m) === dLo) a = m
    else b = m
  }
  lo = b
  return lo
}

/** Hourly ticks across the window, aligned to the ET hour. */
export function hourlyTicks(domain: [number, number] | null): number[] {
  if (domain == null) return []
  const [t0, t1] = domain
  const HOUR = 3_600_000
  const out: number[] = []
  // ET offsets are whole hours from UTC, so ceiling to the next UTC hour is
  // also the next ET hour. (Half-hour zones would need the formatter; America
  // /New_York is not one.)
  let t = Math.ceil(t0 / HOUR) * HOUR
  for (; t <= t1 && out.length < 48; t += HOUR) out.push(t)
  return out
}

// ---------------------------------------------------------------------------
// The marks
// ---------------------------------------------------------------------------

export type MarkTone = 'received' | 'paid' | 'abstained' | 'package'
export type MarkShape = 'up' | 'down' | 'circle' | 'ring' | 'diamond'

export type MarkStyle = {
  tone: MarkTone
  color: string
  shape: MarkShape
  /** The word. Direction is never encoded by colour alone. */
  label: string
  filled: boolean
}

/**
 * Direction -> colour AND shape AND word.
 *
 * A PACKAGE LEG CARRIES NO DIRECTION, DELIBERATELY. A unit's dealer_direction
 * is a STRUCTURE direction: in a steepener the dealer receives one leg and pays
 * the other, so painting one leg with the unit's direction is a guaranteed
 * inversion. The bucket table cannot rescue it either — a 7s10s curve puts both
 * legs in the single 7-10Y TENOR10 bucket, so the bucket's delta_dv01 sign
 * would mislabel both. Level only, neutral ring.
 */
export function directionOf(row: Pick<PrintRow, 'kind' | 'dealer_direction' | 'is_off_market'>): MarkStyle {
  const offMarket = row.is_off_market === true
  if (row.kind !== 'OUTRIGHT') {
    return {
      tone: 'package',
      color: DIRECTION_NEUTRAL,
      shape: 'ring',
      label: 'package leg — level only, direction not resolvable per leg',
      filled: false,
    }
  }
  if (row.dealer_direction === 'RECEIVED') {
    return {
      tone: 'received',
      color: DIRECTION_SKY,
      shape: offMarket ? 'diamond' : 'up',
      label: 'dealer RECEIVED fixed (long duration)',
      filled: !offMarket,
    }
  }
  if (row.dealer_direction === 'PAID') {
    return {
      tone: 'paid',
      color: DIRECTION_AMBER,
      shape: offMarket ? 'diamond' : 'down',
      label: 'dealer PAID fixed (short duration)',
      filled: !offMarket,
    }
  }
  return {
    tone: 'abstained',
    color: DIRECTION_NEUTRAL,
    shape: 'circle',
    label: 'no call',
    filled: true,
  }
}

/**
 * The colour of a deviation stem, and it is the SAME call the mark above it
 * makes — `directionOf`, i.e. the server's `dealer_direction`.
 *
 * NEVER `sign(deviation_bps)`. The producer sets the side from the
 * BIAS-CORRECTED deviation:
 *
 *     backfill_dealer_direction.py:961
 *       # `dealer_side` on the BIAS-CORRECTED deviation: p is a function of
 *       # (dev - b0), so the raw deviation disagrees with the weight on any
 *       # print between 0 and b0 and the ladder refuses that pair.
 *       side = conv.dealer_side(dev - fit.b0)
 *
 * so every print with `0 <= dev < b0` (or `b0 <= dev < 0`) is called on the
 * opposite side from its raw deviation. Colouring a stem by `dev >= 0` paints
 * exactly those prints the opposite colour from their own mark in the price
 * chart directly above — the same print, two directions, stacked. It also
 * paints an ABSTAINED print, which carries no call at all, in a direction hue.
 *
 * The stem's SECOND channel is its side of zero, and the b0 reference line is
 * drawn so the two can be read together: an amber stem a hair above zero but
 * below b0 is the convention working, not an inversion.
 */
export function stemColor(
  row: Pick<PrintRow, 'kind' | 'dealer_direction' | 'is_off_market'>,
): string {
  return directionOf(row).color
}

/**
 * CONSTANT. Conviction is NOT drawn as opacity.
 *
 * Measured on the reference day's default view, in_dead_zone is true for 111 of
 * 120 marks (92.5%), so conviction-by-opacity would fade nearly every mark to
 * illegibility. The schema settles it independently: in_dead_zone is
 * REPORTING-ONLY — nothing in the aggregation depends on it. So conviction
 * lives in the tooltip (p, signed_weight, tau_bps, in_dead_zone) and in one
 * header line stating the share plainly.
 */
export const MARKER_OPACITY = 0.9

/** Takes the row and ignores it, on purpose: the signature makes the constancy
 *  assertable rather than merely stated. */
export function markerOpacity(_row?: Pick<PrintRow, 'in_dead_zone' | 'signed_weight' | 'p'>): number {
  return MARKER_OPACITY
}

export const MARKER_R_MIN = 3.5
export const MARKER_R_MAX = 13
/** ~$110mm of 10y risk. The radius reference, not a cap on what is drawn. */
export const MARKER_DV01_REF = 100_000

/**
 * Radius from structure DV01 on a SQRT-AREA scale, so equal DV01 is equal INK.
 * A linear-radius scale over-reads big trades by the square.
 *
 * Not recharts ZAxis: the size legend renders its reference dots by calling
 * THIS function, so the key cannot drift from the marks.
 */
export function markerRadius(dv01: number | null | undefined): number {
  const a = dv01 == null || !Number.isFinite(Number(dv01)) ? 0 : Math.abs(Number(dv01))
  const r = MARKER_R_MAX * Math.sqrt(a / MARKER_DV01_REF)
  if (!Number.isFinite(r)) return MARKER_R_MIN
  return Math.min(MARKER_R_MAX, Math.max(MARKER_R_MIN, r))
}

export const LEGEND_DV01 = [5_000, 25_000, 100_000] as const

/** The size key. Radii come from markerRadius, never from a hand-written list. */
export function legendSizeRefs(): { dv01: number; r: number }[] {
  return LEGEND_DV01.map((d) => ({ dv01: d, r: markerRadius(d) }))
}

/** True where the size was NOT read — drawn with a dashed outline at the same
 *  radius. The level is real; the area is a floor, not a measurement. */
export function sizeNotRead(
  row: Pick<PrintRow, 'is_capped' | 'is_notional_capped' | 'notional_imputed'>,
): boolean {
  return row.is_capped === true || row.is_notional_capped === true || row.notional_imputed === true
}

/**
 * A RECEIVED print sits above its own mid and a PAID print below.
 *
 * Not a rendering rule — a consequence of the convention, and the cheapest
 * possible check that the panel has not inverted: customer pays fixed ABOVE mid
 * => dealer received fixed. Returns null where there is no mid to compare to.
 */
export function plotsAboveMid(row: Pick<PrintRow, 'traded_pct' | 'mid_pct'>): boolean | null {
  if (row.mid_pct == null) return null
  if (row.traded_pct === row.mid_pct) return null
  return row.traded_pct > row.mid_pct
}

// ---------------------------------------------------------------------------
// The triangles
// ---------------------------------------------------------------------------
//
// recharts' built-in shape="triangle" only points up, so both marks come from
// one custom shape reading props.payload, with an explicit path.

export function upTrianglePath(cx: number, cy: number, r: number): string {
  return `M ${cx},${cy - r} L ${cx + r},${cy + 0.8 * r} L ${cx - r},${cy + 0.8 * r} Z`
}

export function downTrianglePath(cx: number, cy: number, r: number): string {
  return `M ${cx},${cy + r} L ${cx + r},${cy - 0.8 * r} L ${cx - r},${cy - 0.8 * r} Z`
}

export function diamondPath(cx: number, cy: number, r: number): string {
  return `M ${cx},${cy - r} L ${cx + r},${cy} L ${cx},${cy + r} L ${cx - r},${cy} Z`
}

/** A pinned off-domain mark: a small hollow chevron at the edge it was pinned to. */
export function chevronPath(cx: number, cy: number, r: number, pinned: Pinned): string {
  const d = pinned === 'top' ? -1 : 1
  return `M ${cx - r},${cy - d * r * 0.5} L ${cx},${cy + d * r * 0.5} L ${cx + r},${cy - d * r * 0.5}`
}

// ---------------------------------------------------------------------------
// Formatting
// ---------------------------------------------------------------------------

export function fmtRate(x: number | null | undefined, digits = 5): string {
  return x == null || !Number.isFinite(Number(x)) ? '—' : Number(x).toFixed(digits)
}

export function fmtSignedBps(x: number | null | undefined, digits = 3): string {
  if (x == null || !Number.isFinite(Number(x))) return '—'
  const n = Number(x)
  return `${n >= 0 ? '+' : ''}${n.toFixed(digits)} bp`
}

export function fmtNum(x: number | null | undefined, digits = 3): string {
  return x == null || !Number.isFinite(Number(x)) ? '—' : Number(x).toFixed(digits)
}

export function fmtNotional(x: number | null | undefined): string {
  if (x == null || !Number.isFinite(Number(x))) return '—'
  const a = Math.abs(Number(x))
  if (a >= 1e9) return `${(a / 1e9).toFixed(2)}bn`
  if (a >= 1e6) return `${(a / 1e6).toFixed(1)}mm`
  if (a >= 1e3) return `${(a / 1e3).toFixed(0)}k`
  return a.toFixed(0)
}

export function fmtLagSeconds(x: number | null | undefined): string {
  if (x == null || !Number.isFinite(Number(x))) return '—'
  const s = Number(x)
  if (s < 90) return `${s.toFixed(0)}s`
  return `${(s / 60).toFixed(1)}min`
}

export function fmtPctShare(x: number | null | undefined, digits = 1): string {
  return x == null || !Number.isFinite(Number(x)) ? '—' : `${(Number(x) * 100).toFixed(digits)}%`
}

// ---------------------------------------------------------------------------
// Following the tape's selection
// ---------------------------------------------------------------------------

/**
 * The hour (ET) at which the tape's as_of_date rolls to the next day.
 *
 * MEASURED, and it is why the selected trade's calendar date is NOT the day to
 * ask for: prints land at ET hours 20-23 of the previous evening under the
 * FOLLOWING as_of_date. Deriving the day from the execution date alone would
 * silently query the wrong session for every evening print and render an empty
 * chart that looks like "nothing traded".
 */
export const TAPE_DAY_ROLL_ET_HOUR = 20

/** The tape day (as_of_date) an execution instant belongs to. */
export function tapeDayFor(iso: string | null | undefined): string | null {
  const t = tsMillis(iso)
  if (t == null) return null
  const etHour = Number(fmtEtClock(t).slice(0, 2))
  if (!Number.isFinite(etHour)) return null
  const day = etDateOf(t)
  if (etHour < TAPE_DAY_ROLL_ET_HOUR) return day
  const next = new Date(`${day}T00:00:00Z`)
  next.setUTCDate(next.getUTCDate() + 1)
  return next.toISOString().slice(0, 10)
}

/** What a tape row's rate index maps to, or null when it is neither. */
export function normaliseRateIndex(raw: string | null | undefined): string | null {
  if (!raw) return null
  const u = String(raw).toUpperCase()
  if (u.includes('SOFR')) return 'SOFR'
  if (u.includes('FED') || u.includes('FF') || u.includes('H.15')) return 'FED_FUNDS'
  return null
}

export type FollowLeg = {
  tenor_display?: string | null
  rate_index_clean?: string | null
}

/**
 * THE TENOR IS ON THE LEGS, NOT ON THE ROW. Measured against the live payload:
 * a tape row exposes `package_tenors`, `legs_count`, `rate_index_clean` and
 * `legs_json`, and has no `tenor_display` of its own — that field lives on each
 * leg. Reading it off the row returns undefined for every trade, which is
 * exactly what the first cut of this did.
 */
export type FollowSource = {
  tenor_display?: string | null
  rate_index_clean?: string | null
  execution_start?: string | null
  dd_venue_class?: string | null
  legs_json?: FollowLeg[] | null
}

/**
 * The one tenor a trade is about, or null when it is not about one.
 *
 * A package genuinely has no single tenor: the first row of the live tape is a
 * 17-leg trade whose legs run 4Y/5Y/7Y. Picking one of them — the biggest, the
 * first, the longest — would put an instrument on screen that the reader did
 * not select. So multi-tenor returns null and the caller says which tenors
 * were there, leaving the choice to the tenor chips.
 */
export function soleTenorOf(row: FollowSource | null | undefined): {
  tenor: string | null
  distinct: string[]
} {
  if (!row) return { tenor: null, distinct: [] }
  const fromLegs = (row.legs_json ?? [])
    .map((l) => l?.tenor_display)
    .filter((t): t is string => !!t)
  const all = row.tenor_display ? [row.tenor_display, ...fromLegs] : fromLegs
  const distinct = [...new Set(all)]
  return { tenor: distinct.length === 1 ? distinct[0]! : null, distinct }
}

export type Followed = {
  tenor: string | null
  rateIndex: string | null
  venueClass: string | null
  date: string | null
  /** Everything the selection could NOT set, and why. Never silent. */
  refusals: string[]
}

/**
 * What the panel can take from the tape's focused trade.
 *
 * NOTHING IS GUESSED. A tenor outside the eight the chart draws does not fall
 * back to 10Y — that would put a completely different instrument on screen
 * under the reader's selection, which is the whole failure mode this panel is
 * built against. It returns null and says which tenor it was.
 */
export function followFocused(row: FollowSource | null | undefined): Followed {
  const refusals: string[] = []
  if (!row) return { tenor: null, rateIndex: null, venueClass: null, date: null, refusals }

  const { tenor: sole, distinct } = soleTenorOf(row)
  let tenor: string | null = null
  if (sole && (PRINT_TENORS as readonly string[]).includes(sole)) {
    tenor = sole
  } else if (distinct.length > 1) {
    refusals.push(
      `this trade has legs at ${distinct.join(', ')} — a package has no single ` +
        'tenor, so the chart kept the one it was on. Pick a tenor above to ' +
        'follow one leg of it',
    )
  } else if (sole) {
    refusals.push(
      `tenor ${sole} is not one of the eight this chart draws ` +
        `(${PRINT_TENORS.join(', ')}), so the tenor was left as it was rather ` +
        'than silently swapped for a different instrument',
    )
  } else {
    refusals.push('the selected trade carries no leg tenor')
  }

  const rateIndex =
    normaliseRateIndex(row.rate_index_clean) ??
    normaliseRateIndex((row.legs_json ?? []).map((l) => l?.rate_index_clean).find((x) => !!x))
  if (rateIndex == null && row.rate_index_clean) {
    refusals.push(
      `rate index ${row.rate_index_clean} is neither SOFR nor Fed Funds; one ` +
        'index per chart, never mixed',
    )
  }

  const date = tapeDayFor(row.execution_start)
  if (date == null && row.execution_start) {
    refusals.push('the selected trade has no readable execution timestamp')
  }

  const vc = row.dd_venue_class ?? null
  const venueClass =
    vc && (VENUE_CLASSES as readonly string[]).includes(vc) ? vc : null

  return { tenor, rateIndex, venueClass, date, refusals }
}
