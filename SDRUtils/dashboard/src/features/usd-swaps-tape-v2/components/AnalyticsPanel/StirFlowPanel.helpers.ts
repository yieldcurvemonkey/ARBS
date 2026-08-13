// ABOUTME: Pure helpers for the STIR dealer-flow panel — the mark encoding, the
// instrument label, and the two domains. No React, no fetch.
//
// THE ENCODING IS THE SAME AS THE INTRADAY PRINTS PANEL ON PURPOSE.
// Sky/up = dealer RECEIVED, amber/down = dealer PAID, area = structure DV01.
// The notebook uses green/red; this deliberately does not follow it. Two
// direction charts sit on the same screen, and the one thing worse than an
// unfamiliar palette is the same concept wearing two different colours a
// scroll apart.
import {
  DIRECTION_AMBER,
  DIRECTION_NEUTRAL,
  DIRECTION_SKY,
} from '../../utils/dealerDirection'

// --- wire types (mirror stir-flow.logic.ts) --------------------------------

export type StirFlowRow = {
  unit_key: string
  trade_id: string | null
  package_id: string | null
  execution_timestamp: string
  curve_timestamp: string | null
  dealer_direction: 'RECEIVED' | 'PAID'
  classification_method: string | null
  direction_confidence: string | null
  p_flip: number | string | null
  structure_dv01: number | string | null
  notional: number | string | null
  dv01: number | string | null
  fixed_rate: number | string | null
  curve_mid: number | string | null
  spread_to_mid_bps: number | string | null
  dealer_charge_bps: number | string | null
  rate_index_clean: string
  trade_type: string | null
  is_off_market: boolean | null
  curve_suspect_trade: boolean | null
  tenor_query: string
  tenor_bucket: string | null
  curve_name: string | null
  code_vintage: string | null
}

export type StirInstrument = {
  tenor_query: string
  rate_index_clean: string
  n: number
  n_received: number
  n_paid: number
  n_off_market: number
  n_with_mid: number
  dv01: number | string | null
  first_ts: string | null
  last_ts: string | null
}

export type StirFlowCounts = {
  drawn: number
  onMarketMid: number
  tickRule: number
  offMarket: number
  offIndex: number
  noMid: number
  curveSuspect: number
}

export type MidPointWire = { ts: string; mid_pct: number }

export type StirFlowResponse = {
  date: string
  tenorQuery: string
  rateIndex: string
  clock: 'execution'
  filters: { includeOffMarket: boolean; includeTickRule: boolean }
  rows: StirFlowRow[]
  mid: MidPointWire[]
  counts: StirFlowCounts
  disclosures: string[]
  curve_name: string | null
  code_vintage: string | null
  error?: string
}

export const STIR_RATE_INDEXES = ['SOFR', 'FED_FUNDS'] as const

/** pg hands NUMERIC back as a string. */
export function num(v: number | string | null | undefined): number | null {
  if (v == null || v === '') return null
  const n = Number(v)
  return Number.isFinite(n) ? n : null
}

export function tsMillis(iso: string | null | undefined): number | null {
  if (!iso) return null
  const t = new Date(iso).getTime()
  return Number.isFinite(t) ? t : null
}

// --- the instrument --------------------------------------------------------

/** `2026-07-29->2026-09-16` -> its two dates, or null if malformed. */
export function parseTenorQuery(tq: string): { eff: string; mat: string } | null {
  const m = /^(\d{4}-\d{2}-\d{2})->(\d{4}-\d{2}-\d{2})$/.exec(tq)
  return m ? { eff: m[1]!, mat: m[2]! } : null
}

/** Whole days between the two legs. The instrument's length, not a tenor label. */
export function instrumentDays(tq: string): number | null {
  const p = parseTenorQuery(tq)
  if (!p) return null
  const a = Date.parse(`${p.eff}T00:00:00Z`)
  const b = Date.parse(`${p.mat}T00:00:00Z`)
  if (!Number.isFinite(a) || !Number.isFinite(b)) return null
  return Math.round((b - a) / 86_400_000)
}

/**
 * A meeting-to-meeting structure is short and lands between two FOMC dates; a
 * date pair a year or more apart is an ordinary forward-starting swap that
 * happens to be keyed the same way.
 *
 * 70 days is comfortably above the longest FOMC inter-meeting gap (the
 * July->September gap, 49 days in 2026) and far below a 1y structure, so it
 * separates the two populations without pretending to know the meeting
 * calendar. The label says "meeting-length", never a meeting NAME, because
 * naming a meeting from a date needs the calendar and getting it wrong would
 * mislabel the instrument.
 */
export const MEETING_LENGTH_MAX_DAYS = 70

export function instrumentLabel(inst: StirInstrument): string {
  const d = instrumentDays(inst.tenor_query)
  const p = parseTenorQuery(inst.tenor_query)
  const shape =
    d == null ? '' : d <= MEETING_LENGTH_MAX_DAYS ? ' · meeting-length' : ` · ${(d / 365).toFixed(1)}y`
  const dv01 = num(inst.dv01)
  const size = dv01 == null ? '' : ` · ${(Math.abs(dv01) / 1000).toFixed(0)}k DV01`
  const dates = p ? `${p.eff} → ${p.mat}` : inst.tenor_query
  return `${dates}${shape} · ${inst.rate_index_clean} · ${inst.n} trades${size}`
}

// --- the marks -------------------------------------------------------------

export type StirMarkShape = 'up' | 'down' | 'diamond'
export type StirMarkStyle = {
  color: string
  shape: StirMarkShape
  /** Hollow marks are trades whose position carries no mid information. */
  filled: boolean
  label: string
  title: string
}

/**
 * How a trade is drawn, and why.
 *
 * OFF-MARKET -> diamond, following the notebook: an upfront makes the fixed
 * rate arbitrary, so the trade is off mid by construction.
 *
 * TICK_RULE -> HOLLOW. Measured on the whole table, tick-rule spread signs do
 * NOT track direction (PAID 1,331 positive / 3,914 negative; RECEIVED 1,956 /
 * 3,984) because the tick rule reads trade sequence rather than the mid. The
 * direction is still the classifier's call and is drawn; what is not drawn is
 * any implication that its distance from mid means something.
 */
export function stirMarkStyle(row: StirFlowRow): StirMarkStyle {
  const received = row.dealer_direction === 'RECEIVED'
  const tick = row.classification_method === 'TICK_RULE'
  const off = row.is_off_market === true
  return {
    color: received ? DIRECTION_SKY : DIRECTION_AMBER,
    shape: off ? 'diamond' : received ? 'up' : 'down',
    filled: !tick,
    label: received ? 'RECEIVED' : 'PAID',
    title:
      (received
        ? 'Dealer RECEIVED fixed — customer paid fixed, dealer is long duration.'
        : 'Dealer PAID fixed — customer received fixed, dealer is short duration.') +
      (tick
        ? '\n\nTICK_RULE: classified from trade sequence, not from the mid. Its ' +
          'distance from the mid line is not a measurement of anything.'
        : '') +
      (off ? '\n\nOFF-MARKET: carries an upfront, so the fixed rate is arbitrary.' : ''),
  }
}

export const MARK_R_MIN = 3.5
export const MARK_R_MAX = 14
/** Same reference as the sibling panel so a mark of a given size means the
 *  same amount of risk on both charts. */
export const MARK_DV01_REF = 100_000

export function markRadius(dv01: number | string | null | undefined): number {
  const v = num(dv01)
  if (v == null || v <= 0) return MARK_R_MIN
  const r = MARK_R_MIN + (MARK_R_MAX - MARK_R_MIN) * Math.sqrt(Math.min(Math.abs(v) / MARK_DV01_REF, 1))
  return Math.min(Math.max(r, MARK_R_MIN), MARK_R_MAX)
}

// --- the series ------------------------------------------------------------

export type MidPoint = { t: number; mid: number | null }

/**
 * Above this, the mid line breaks rather than bridging.
 *
 * The line is snapshots at print times, not a grid, so its spacing is the
 * spacing of TRADES. 30 minutes is deliberately more generous than the 10
 * minutes used for the sibling panel's real 1-minute grid: there, a gap means
 * the curve is missing; here it only means nobody traded, which is not the
 * same claim. Beyond half an hour the segment stops being a plausible
 * interpolation of a level nobody observed.
 */
export const STIR_MID_GAP_MINUTES = 30

export function buildStirMidSeries(
  points: MidPointWire[],
  gapMinutes: number = STIR_MID_GAP_MINUTES,
): MidPoint[] {
  const pts: MidPoint[] = []
  for (const p of points) {
    const t = tsMillis(p.ts)
    const mid = num(p.mid_pct)
    if (t == null || mid == null) continue
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

/** 0.5bp floor so a quiet instrument is quiet rather than magnified into noise. */
export const MIN_Y_SPAN_PCT = 0.005
const Y_PAD = 0.1

/**
 * The traded rate of a row, in PERCENT.
 *
 * fixed_rate is a FRACTION (measured 99.95% of rows) and curve_mid is ALREADY
 * PERCENT (99.88%). Getting this backwards is a silent 100x, because both raw
 * numbers look like plausible rates.
 */
export function tradedPct(row: StirFlowRow): number | null {
  const v = num(row.fixed_rate)
  return v == null ? null : v * 100
}

/** The mid the classifier used, in PERCENT. Already percent -- never scaled. */
export function midPct(row: StirFlowRow): number | null {
  return num(row.curve_mid)
}

/**
 * The rate domain, over the mid AND the traded rates.
 *
 * Both belong: once the units are reconciled they are the same quantity, and
 * the gap between a mark and the line IS the dealer spread -- measured,
 * spread_to_mid_bps == (fixed_rate*100 - curve_mid)*100 exactly, median |error|
 * 0.0 across 49,653 of 49,653 rows. Excluding the traded rate would clip the
 * very marks the chart is about.
 */
export function rateDomain(rows: StirFlowRow[], mid: MidPoint[]): [number, number] | null {
  const vals: number[] = []
  for (const m of mid) if (m.mid != null) vals.push(m.mid)
  for (const r of rows) {
    const t = tradedPct(r)
    if (t != null && Number.isFinite(t)) vals.push(t)
  }
  if (vals.length === 0) return null
  let lo = Math.min(...vals)
  let hi = Math.max(...vals)
  if (hi - lo < MIN_Y_SPAN_PCT) {
    const c = (hi + lo) / 2
    lo = c - MIN_Y_SPAN_PCT / 2
    hi = c + MIN_Y_SPAN_PCT / 2
  }
  const pad = (hi - lo) * Y_PAD
  return [lo - pad, hi + pad]
}

/** Symmetric bp domain for the deviation panel, so zero is always the centre. */
export function spreadDomain(rows: StirFlowRow[]): [number, number] {
  let m = 0.5
  for (const r of rows) {
    const s = num(r.spread_to_mid_bps)
    if (s != null) m = Math.max(m, Math.abs(s))
  }
  return [-m * 1.1, m * 1.1]
}

export function tDomain(rows: StirFlowRow[], mid: MidPoint[]): [number, number] | null {
  const ts: number[] = []
  for (const r of rows) {
    const t = tsMillis(r.execution_timestamp)
    if (t != null) ts.push(t)
  }
  for (const m of mid) ts.push(m.t)
  if (ts.length === 0) return null
  return [Math.min(...ts), Math.max(...ts)]
}

/**
 * The mid at a mark's own instant, for placing it ON the line.
 *
 * Nearest snapshot, matching the notebook's `get_indexer(method="nearest")`.
 * Returns null when there is no mid at all, and the mark is then dropped from
 * the rate chart rather than pinned to an edge — it still appears in the
 * deviation panel, where it has a real value.
 */
export function midAt(t: number, mid: MidPoint[]): number | null {
  let best: number | null = null
  let bestD = Infinity
  for (const m of mid) {
    if (m.mid == null) continue
    const d = Math.abs(m.t - t)
    if (d < bestD) {
      bestD = d
      best = m.mid
    }
  }
  return best
}

export const NEUTRAL = DIRECTION_NEUTRAL
