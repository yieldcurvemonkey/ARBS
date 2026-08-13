// ABOUTME: Params, SQL and refusals for the STIR dealer-flow chart — the
// notebook `notebooks/exploratory/dealer_flow_chart.ipynb`, served from the web.
// Pure: no React, no I/O, so every rule below is tested without mocking.
//
// ===================================================================
// THIS IS A DIFFERENT PIPELINE FROM THE INTRADAY PRINTS PANEL
// ===================================================================
//
// The sibling panel reads arbs_dd_unit_v1 (the USD-swaps SDR tape direction) and
// draws vanilla SOFR/FF at 1Y..30Y. THIS one reads arbs_stir_direction_v1 (the
// STIR classifier) and draws ONE meeting-dated structure — an instrument keyed
// by its exact (effective -> maturity) date pair, e.g. 2026-07-29->2026-09-16,
// which is FOMC-July to FOMC-September. Different table, different classifier,
// different instrument space. They are never mixed.
//
// Measured: 84,586 rows over 138 days (2026-01-12 .. 2026-07-29), 99.7%
// directional, SOFR 73,153 / FED_FUNDS 11,191, across 14,367 distinct
// instruments.
//
// ===================================================================
// THREE MEASURED FACTS THAT DECIDE HOW THIS MAY BE DRAWN
// ===================================================================
//
// 1. THE RATE INDEX MUST BE FILTERED, AND IT IS NOT OPTIONAL.
//    This chart has been wrong once already, in exactly one way: it overlaid
//    SOFR and FED_FUNDS trades on a single Fed-Funds reference line. SOFR OIS
//    sits ~1.5-2.5bp above the FF line (the SOFR-FF basis), so correctly
//    classified SOFR receives plotted above an FF mid and looked mislabelled.
//    The classifier was right and the chart was wrong. So rateIndex is a
//    REQUIRED parameter here rather than a filter with a default, and the
//    response reports how many trades the filter removed.
//
// 2. THE TWO RATE COLUMNS ARE IN DIFFERENT UNITS. This is the trap in this
//    table and it is silent, because both are plausible numbers.
//
//      fixed_rate  is a FRACTION   0.0364      75,244 of 75,285 rows (99.95%)
//      curve_mid   is a PERCENT    3.6511      60,879 of 60,950 rows (99.88%)
//
//    Subtracting them directly gives 0.036 - 3.7 = -3.66 for EVERY trade,
//    which is why a naive read of the data says "every RECEIVED print sits
//    below its mid" (measured 16,664 of 16,741 before the fix). That is not a
//    mid bias and not an inverted classifier -- it is a factor of 100.
//
//    Converted, the classifier identity is EXACT:
//
//      spread_to_mid_bps == (fixed_rate * 100 - curve_mid) * 100
//      median |error| 0.0,  49,653 of 49,653 agree to within 0.01 bp
//
//    So the traded rate and the mid DO share an axis, and a mark belongs at
//    its own traded rate: the vertical offset from the line is then exactly
//    the dealer spread, which is what the chart is for. RECEIVED lands above
//    the mid, PAID below. Everything on the rate axis here is PERCENT --
//    fixed_rate is multiplied, curve_mid is not.
//
// 3. TICK_RULE TRADES ARE NOT MID-BASED, and their spread sign does not track
//    direction: measured PAID 1,331 positive / 3,914 negative, RECEIVED 1,956 /
//    3,984. That is not a defect — the tick rule classifies from trade sequence
//    rather than from the mid — but it means a tick-rule marker's position in
//    the deviation panel says nothing about its direction. They are labelled,
//    and can be switched off.
import { STIR_DIRECTION } from '@/lib/dealer-direction-tables'
import { BadRequest } from './route.logic'

/** The two canonical indices. There is no "both": see fact 1. */
export const STIR_RATE_INDEXES = ['SOFR', 'FED_FUNDS'] as const
export type StirRateIndex = (typeof STIR_RATE_INDEXES)[number]

/**
 * Methods the classifier stamps. Mid-based ones satisfy
 * sign(spread_to_mid_bps) == direction exactly; TICK_RULE does not.
 */
export const MID_BASED_METHODS = ['RATE_VS_MID', 'SPREAD_VS_MID', 'FLY_VS_MID'] as const

/**
 * Fewest trades an instrument needs before it is offered in the picker.
 *
 * 14,367 instruments exist and the long tail is one-print date pairs. A chart
 * of one trade is a dot with an axis around it.
 */
export const MIN_INSTRUMENT_TRADES = 8

/** Most instruments the picker returns for a day, busiest first by DV01. */
export const MAX_INSTRUMENTS = 60

export type StirFlowParams = {
  /** null means "the latest day with classified STIR flow". */
  date: string | null
  /** The exact `effective->maturity` pair, e.g. 2026-07-29->2026-09-16. */
  tenorQuery: string
  rateIndex: StirRateIndex
  includeOffMarket: boolean
  includeTickRule: boolean
}

export type ResolvedStirFlowParams = StirFlowParams & { date: string }

export type BoundSql = { text: string; values: unknown[] }

/**
 * `effective->maturity`, and nothing else.
 *
 * Validated as a shape rather than passed through, because it is the whole
 * instrument identity: a malformed value would silently select nothing and the
 * chart would render an empty day rather than an error.
 */
export const TENOR_QUERY_RE = /^\d{4}-\d{2}-\d{2}->\d{4}-\d{2}-\d{2}$/

export function parseStirFlowParams(sp: URLSearchParams): StirFlowParams {
  const rawDate = sp.get('date')
  let date: string | null = null
  if (rawDate) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(rawDate)) {
      throw new BadRequest('date must be YYYY-MM-DD')
    }
    date = rawDate
  }

  const tenorQuery = sp.get('tenorQuery') ?? ''
  if (!TENOR_QUERY_RE.test(tenorQuery)) {
    throw new BadRequest(
      'tenorQuery is required and must be an exact effective->maturity pair, ' +
        'e.g. 2026-07-29->2026-09-16. This chart is about ONE meeting-dated ' +
        'structure; there is no all-instrument view, because two different ' +
        'date pairs are two different instruments and do not share a rate axis.',
    )
  }

  const rateIndex = sp.get('rateIndex') as StirRateIndex | null
  if (rateIndex == null || !(STIR_RATE_INDEXES as readonly string[]).includes(rateIndex)) {
    throw new BadRequest(
      `rateIndex is REQUIRED and must be one of ${STIR_RATE_INDEXES.join(', ')}. ` +
        'It has no default on purpose. This chart has been wrong once, in ' +
        'exactly one way: SOFR and FED_FUNDS trades overlaid on a single ' +
        'Fed-Funds reference line. SOFR OIS sits ~1.5-2.5bp above the FF line, ' +
        'so correctly classified SOFR receives plotted above an FF mid and ' +
        'looked mislabelled — the classifier was right and the chart was ' +
        'wrong. Defaulting this would rebuild that bug.',
    )
  }

  return {
    date,
    tenorQuery,
    rateIndex,
    includeOffMarket: sp.get('includeOffMarket') === 'true',
    includeTickRule: sp.get('includeTickRule') !== 'false',
  }
}

/** The most recent day carrying classified STIR flow. */
export function latestStirDateSql(): string {
  return `SELECT max(as_of_date)::text AS as_of_date FROM ${STIR_DIRECTION}
          WHERE dealer_direction IN ('PAID','RECEIVED')`
}

/**
 * What instruments traded on a day, busiest first.
 *
 * Grouped by (instrument, index) TOGETHER, never by instrument alone: the same
 * date pair trades on both SOFR and Fed Funds and they are two different
 * instruments with two different mids.
 */
export function stirInstrumentsSql(): BoundSql {
  const text = `
    SELECT tenor_query, rate_index_clean,
           count(*)::int AS n,
           count(*) FILTER (WHERE dealer_direction = 'RECEIVED')::int AS n_received,
           count(*) FILTER (WHERE dealer_direction = 'PAID')::int     AS n_paid,
           count(*) FILTER (WHERE COALESCE(is_off_market, false))::int AS n_off_market,
           count(curve_mid)::int AS n_with_mid,
           sum(structure_dv01) AS dv01,
           min(execution_timestamp) AS first_ts,
           max(execution_timestamp) AS last_ts
    FROM ${STIR_DIRECTION}
    WHERE as_of_date = $1::date
      AND dealer_direction IN ('PAID','RECEIVED')
    GROUP BY tenor_query, rate_index_clean
    HAVING count(*) >= $2
    ORDER BY sum(structure_dv01) DESC NULLS LAST, count(*) DESC
    LIMIT $3
  `
  return { text, values: [] }
}

/**
 * One instrument, one day, one index.
 *
 * DISTINCT ON (unit_key) because a package prints once per leg and the unit is
 * the trade. The notebook does the same.
 */
export function stirFlowSql(p: ResolvedStirFlowParams): BoundSql {
  const text = `
    SELECT DISTINCT ON (unit_key)
      unit_key, trade_id, package_id,
      execution_timestamp, curve_timestamp,
      dealer_direction, classification_method, direction_confidence, p_flip,
      structure_dv01, notional, dv01,
      fixed_rate, curve_mid, spread_to_mid_bps, dealer_charge_bps,
      rate_index_clean, trade_type, is_off_market, curve_suspect_trade,
      tenor_query, tenor_bucket, curve_name, code_vintage
    FROM ${STIR_DIRECTION}
    WHERE as_of_date = $1::date
      AND tenor_query = $2
      AND rate_index_clean = $3
      AND dealer_direction IN ('PAID','RECEIVED')${
        p.includeOffMarket ? '' : '\n      AND NOT COALESCE(is_off_market, false)'
      }${
        p.includeTickRule ? '' : "\n      AND classification_method <> 'TICK_RULE'"
      }
    ORDER BY unit_key, execution_timestamp
  `
  return { text, values: [p.date, p.tenorQuery, p.rateIndex] }
}

/**
 * Every chip on screen, measured in the same round trip and with the filters
 * relaxed one at a time — never inferred from what came back.
 *
 * `off_index` is the one that matters: it is the count the rate-index filter
 * removed, i.e. exactly the trades that produced the historical bug when they
 * were left on the chart. "0 trades were on the other index" and "we dropped
 * 41" are different facts.
 */
export function stirFlowCountsSql(p: ResolvedStirFlowParams): BoundSql {
  const text = `
    SELECT
      count(*) FILTER (WHERE rate_index_clean = $3
                         AND NOT COALESCE(is_off_market, false)
                         AND classification_method <> 'TICK_RULE')::int AS on_market_mid,
      count(*) FILTER (WHERE rate_index_clean = $3
                         AND NOT COALESCE(is_off_market, false)
                         AND classification_method = 'TICK_RULE')::int  AS tick_rule,
      count(*) FILTER (WHERE rate_index_clean = $3
                         AND COALESCE(is_off_market, false))::int       AS off_market,
      count(*) FILTER (WHERE rate_index_clean <> $3)::int               AS off_index,
      count(*) FILTER (WHERE rate_index_clean = $3
                         AND curve_mid IS NULL)::int                    AS no_mid,
      count(*) FILTER (WHERE rate_index_clean = $3
                         AND COALESCE(curve_suspect_trade, false))::int AS curve_suspect
    FROM ${STIR_DIRECTION}
    WHERE as_of_date = $1::date
      AND tenor_query = $2
      AND dealer_direction IN ('PAID','RECEIVED')
  `
  return { text, values: [p.date, p.tenorQuery, p.rateIndex] }
}

// ---------------------------------------------------------------------------
// Payload
// ---------------------------------------------------------------------------

export type StirFlowRow = {
  unit_key: string
  trade_id: string | null
  package_id: string | null
  execution_timestamp: string
  curve_timestamp: string | null
  dealer_direction: 'RECEIVED' | 'PAID'
  classification_method: string | null
  direction_confidence: string | null
  p_flip: number | null
  structure_dv01: number | null
  notional: number | null
  dv01: number | null
  fixed_rate: number | null
  curve_mid: number | null
  spread_to_mid_bps: number | null
  dealer_charge_bps: number | null
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
  dv01: number | null
  first_ts: string | null
  last_ts: string | null
}

export type StirFlowCounts = {
  drawn: number
  onMarketMid: number
  tickRule: number
  offMarket: number
  /** Removed by the rate-index filter — the historical bug, counted. */
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
  /** The mid at PRINT TIMES only. See buildPrintTimeMid. */
  mid: MidPointWire[]
  counts: StirFlowCounts
  disclosures: string[]
  curve_name: string | null
  code_vintage: string | null
  error?: string
}

/**
 * The reference line: the mid the classifier ACTUALLY USED, at the instants it
 * used it.
 *
 * This is not a continuous curve and the panel says so. There is no intraday
 * mid grid for these instruments and there cannot cheaply be one: 14,367
 * distinct (effective, maturity) pairs exist, and the notebook builds its line
 * by running IRSwapsTB over a 1-minute grid — rateslib and the Barchart STIR
 * curve store, neither of which the web tier can reach. So rather than invent a
 * curve, the panel draws the stored `curve_mid` at each `curve_timestamp`.
 *
 * Deduped to one point per minute and sorted, so repeated prints against the
 * same snapshot do not stack.
 */
export function buildPrintTimeMid(rows: StirFlowRow[]): MidPointWire[] {
  const byMinute = new Map<number, { t: number; mid: number }>()
  for (const r of rows) {
    if (r.curve_mid == null) continue
    const iso = r.curve_timestamp ?? r.execution_timestamp
    const t = new Date(iso).getTime()
    if (!Number.isFinite(t)) continue
    // NOT scaled: curve_mid is ALREADY percent (measured 99.88% of rows).
    // fixed_rate is the fraction and takes the x100 -- see fact 2.
    const mid = Number(r.curve_mid)
    if (!Number.isFinite(mid)) continue
    byMinute.set(Math.floor(t / 60_000), { t, mid })
  }
  return [...byMinute.values()]
    .sort((a, b) => a.t - b.t)
    .map((x) => ({ ts: new Date(x.t).toISOString(), mid_pct: x.mid }))
}

export type StirDisclosureInput = {
  counts: StirFlowCounts
  filters: { includeOffMarket: boolean; includeTickRule: boolean }
  rateIndex: string
  tenorQuery: string
  curveName: string | null
  midPoints: number
}

/** The assumptions strip, served by the API so it cannot drift from the UI. */
export function buildStirDisclosures(d: StirDisclosureInput): string[] {
  const out: string[] = []

  out.push(
    'Direction is a price-implied INFERENCE from the STIR classifier, not ' +
      'observed party identity. A model-labelled flow proxy, not a ' +
      'counterparty record.',
  )

  out.push(
    `RATE INDEX IS PINNED TO ${d.rateIndex} and ${d.counts.offIndex} trade(s) on ` +
      'the other index were removed. This is not hygiene: overlaying SOFR and ' +
      'Fed Funds on one reference line is the bug this chart has already had ' +
      'once. SOFR OIS sits ~1.5-2.5bp above the FF line, so correctly ' +
      'classified SOFR receives plot above an FF mid and look inverted. The ' +
      'classifier was right; the chart was wrong.',
  )

  out.push(
    `The line is the mid the classifier USED, at the instants it used it — ` +
      `${d.midPoints} snapshot(s) from ${d.curveName ?? '—'}. It is NOT a ` +
      'continuous curve and there is no intraday grid behind it: 14,367 ' +
      'distinct meeting-dated instruments exist and their mids come from ' +
      'rateslib over the Barchart STIR curve store, which the web tier cannot ' +
      'reach. Segments between snapshots are drawn, not measured.',
  )

  out.push(
    'Marks sit at their OWN TRADED RATE, so the gap to the line is the ' +
      'dealer spread: RECEIVED above the mid, PAID below. The two columns ' +
      'arrive in DIFFERENT UNITS -- fixed_rate is a fraction (99.95% of rows), ' +
      'curve_mid is already percent (99.88%) -- and subtracting them raw says ' +
      'every receive is below its mid, which is a factor of 100, not a mid ' +
      'bias. Converted, the classifier identity is exact: spread_to_mid_bps ' +
      '== (fixed_rate*100 - curve_mid)*100, median |error| 0.0 over 49,653 of ' +
      '49,653 rows.',
  )

  if (d.filters.includeTickRule) {
    out.push(
      `${d.counts.tickRule} trade(s) are classified by TICK_RULE, which does ` +
        'not use the mid at all — it reads trade sequence. Measured, their ' +
        'spread sign does NOT track direction (PAID 1,331 positive / 3,914 ' +
        'negative; RECEIVED 1,956 / 3,984), so a tick-rule mark’s position in ' +
        'the deviation panel says nothing about its direction. They are drawn ' +
        'hollow.',
    )
  } else {
    out.push(
      `${d.counts.tickRule} TICK_RULE trade(s) hidden. They are classified ` +
        'from trade sequence rather than from the mid, so their deviation is ' +
        'not a distance from anything.',
    )
  }

  out.push(
    `Off-market: ${d.counts.offMarket} ` +
      `${d.filters.includeOffMarket ? 'shown as diamonds' : 'hidden'}. An ` +
      'upfront makes the fixed rate arbitrary, so the trade is off mid by ' +
      'construction rather than by choice.',
  )

  if (d.counts.noMid > 0) {
    out.push(
      `${d.counts.noMid} trade(s) carry NO curve_mid at all and contribute a ` +
        'mark but no line point. Measured coverage across the table is 60,950 ' +
        'of 84,344 (72.3%).',
    )
  }
  if (d.counts.curveSuspect > 0) {
    out.push(
      `${d.counts.curveSuspect} trade(s) are flagged curve_suspect_trade — the ` +
        'classifier itself doubts the snapshot they were priced against.',
    )
  }

  out.push(
    'EXECUTION clock — where it traded, not what you could have known.',
  )

  return out
}
