// ABOUTME: Params, SQL and refusals for the STRUCTURE prints chart — one CURVE
// or FLY instrument, one day, with every print of it and the dealer's side.
// Pure: no React, no I/O.
//
// ===================================================================
// WHY THIS EXISTS
// ===================================================================
//
// The outright chart draws one tenor. Selecting a 10s30s curve on the tape got
// you "a package has no single tenor, pick a leg" — which is wrong. A 10s30s
// curve IS an instrument: it has a level (a bp spread), a continuous mid (the
// two legs of the 1-minute grid, combined), and a direction the pipeline
// already computes at STRUCTURE grain. Refusing to draw it confused "no single
// tenor" with "no instrument".
//
// ===================================================================
// THE ARITHMETIC, MEASURED EXACTLY
// ===================================================================
//
// `arbs_dd_unit_v1.deviation_bps` is ALREADY structure-grain: the backfill
// computes `structure_price(traded legs) - structure_price(model leg mids)`
// under the pipeline's own quote weights, percent-in / bp-out. So:
//
//     structure_bp = 100 * SUM_i q_i * (fixed_rate_i * 100)
//     mid_bp       = structure_bp - deviation_bps          <- EXACT
//
//     q = (1)  OUTRIGHT     (-1, +1) CURVE     (-1, +2, -1) FLY
//
// Verified on 25,692 grid-clean units across 26 months (2024-07-01..2026-08-07):
// CURVE 17,197 of 17,197 to 1.3e-12 bp, FLY 8,495 of 8,495 to 2.2e-12 bp. Three
// wrong FLY hypotheses were tested as a mutation check on the checker itself and
// all fail loudly — negated weights median |err| 4.76 bp, belly at index 0
// 14.55 bp, belly at index 2 14.73 bp.
//
// Hand-traced against the trade this feature was reported on
// (PTS_4652395859000000101, 2026-08-07): legs 4.2395% / 4.4550%, so
// (4.4550 - 4.2395) * 100 = 21.55 bp — exactly the "RATE 21.55 bps" the tape
// header shows. deviation -0.0455 bp with dealer_direction PAID, i.e. traded
// below mid, the same sign convention outrights use.
//
// ===================================================================
// THE THREE THINGS THAT MAKE THIS NOT A FILTER CHANGE
// ===================================================================
//
// 1. THE GRAIN. The outright endpoint returns one row PER LEG. A structure
//    needs one row PER UNIT carrying every leg, because the level is a function
//    of ALL of them.
//
// 2. ANY PER-LEG PREDICATE LEFT IN THE WHERE CLAUSE SILENTLY DROPS A LEG AND
//    MISPRICES THE STRUCTURE. A 2-leg curve that loses one leg to an
//    off-market filter gets priced off the survivor and looks entirely
//    plausible. Every leg-grained filter is therefore a unit-level aggregate
//    (`bool_or` for off-market, `max` for the forward ceiling), and
//    `HAVING count(*) = u.n_legs` is the linchpin that catches both a partial
//    join and any leg lost anyway.
//
// 3. THE LEG ORDER IS LOAD-BEARING AND IT IS NOT `leg_order`. The weights are
//    defined against the pipeline's total order
//    (expiration_date, effective_date, trade_id, leg_order). `leg_order` alone
//    is emission order and differs from the canonical order on 1,670 of 36,991
//    units (4.51%) — enough to turn a 5s10s into a 10s5s (a sign flip) and to
//    move a fly's belly.
import { DD_CURVE_MID, DD_UNIT } from '@/lib/dealer-direction-tables'
import { TAPE_LEGS } from '@/lib/tape-tables'
import { BadRequest, parseCommon, SAMPLE_FLOOR, type VenueClass } from './route.logic'

export const STRUCTURE_KINDS = ['CURVE', 'FLY'] as const
export type StructureKind = (typeof STRUCTURE_KINDS)[number]

export const STRUCTURE_RATE_INDEXES = ['SOFR', 'FED_FUNDS'] as const
export type StructureRateIndex = (typeof STRUCTURE_RATE_INDEXES)[number]

/** Legs a kind must have. Anything else is a different instrument. */
export const LEGS_FOR: Record<StructureKind, number> = { CURVE: 2, FLY: 3 }

/**
 * The pipeline's quote weights, in canonical leg order.
 *
 * NOT a preference and NOT re-derivable from the chart: these are
 * `conventions.quote_weights`, and the stored deviation_bps is only consistent
 * with THESE. Index 0 is the earliest expiration; for a FLY index 1 is the
 * belly.
 */
export const QUOTE_WEIGHTS: Record<StructureKind, number[]> = {
  CURVE: [-1, 1],
  FLY: [-1, 2, -1],
}

/**
 * The SQL that reproduces the pipeline's canonical leg order.
 *
 * Written once and used by BOTH the level arithmetic and the tenor-tuple
 * identity, so the two can never disagree about which leg is the front.
 */
export const CANONICAL_LEG_ORDER =
  'l.expiration_date, l.effective_date, l.trade_id, l.leg_order'

/** ~7.3 days. A forward-starting curve is not the spot curve. */
export const FWD_MAX_DEFAULT = 0.02
export const FWD_MAX_CEILING = 0.25

/**
 * Below this the chart is a scatter with an axis around it.
 *
 * Structures are FAR thinner than outrights: measured on 2026-08-07 there were
 * 23 SOFR 10Y/30Y CURVE units all day across every rule and venue, against 72
 * D2C 10Y outrights in one tenor. The line still carries the session because it
 * comes from the 1-minute grid, so a low floor is honest here — but two prints
 * is not a picture of flow.
 */
export const MIN_STRUCTURE_PRINTS = 1

export type StructureParams = {
  date: string | null
  kind: StructureKind
  /** Canonical-order leg tenors, e.g. ['10Y','30Y']. */
  tenors: string[]
  rateIndex: StructureRateIndex
  venueClass: VenueClass
  includeOffMarket: boolean
  /** RATE_VS_MID only by default — see the refusal on rules below. */
  ruleStrict: boolean
  fwdMaxYears: number
}

export type ResolvedStructureParams = StructureParams & { date: string }
export type BoundSql = { text: string; values: unknown[] }

const TENOR_RE = /^~?\d+[MY]$/

/** '10Y' -> 10, '18M' -> 1.5, '~10Y' -> 10. Null when unparseable. */
export function tenorYears(t: string): number | null {
  const m = /^~?(\d+)([MY])$/.exec(t)
  if (!m) return null
  const n = Number(m[1])
  return m[2] === 'Y' ? n : n / 12
}

/**
 * Order the requested tenors ONLY for display. Selection is order-insensitive.
 *
 * SORTING BY TENOR-YEARS IS NOT THE CANONICAL ORDER AND MUST NEVER DECIDE THE
 * SIGN. The pipeline orders legs by (expiration_date, effective_date,
 * trade_id, leg_order); a tenor-years sort disagrees on 3,168 of 89,147 CURVE
 * units (3.55%) and 1,709 of 50,179 FLY units (3.41%), and on those it INVERTS
 * the level. Worked example from prod: CURVE_10_1159337735 is 10Y10Y vs
 * 20Y10Y — canonical traded_bp -70.500, tenor-sorted +70.500. Its two legs
 * differ by 0.003 in tenor_years (10.008 vs 10.005), so a tenor sort is
 * decided by day-count float noise and the tie-break is arbitrary.
 *
 * So the SQL matches the requested tenors as a SET (both sides sorted
 * alphabetically purely to compare them) and the response returns the
 * instrument's OWN canonical tuple, which is the only authority on which leg
 * is the front. This function exists only to give the request a stable shape.
 */
export function displayOrderTenors(tenors: string[]): string[] {
  return [...tenors].sort((a, b) => (tenorYears(a) ?? 0) - (tenorYears(b) ?? 0))
}

export function parseStructureParams(sp: URLSearchParams): StructureParams {
  const rawDate = sp.get('date')
  let date: string | null = null
  if (rawDate) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(rawDate)) throw new BadRequest('date must be YYYY-MM-DD')
    if (rawDate < SAMPLE_FLOOR) {
      throw new BadRequest(`date is before the sample floor ${SAMPLE_FLOOR}.`)
    }
    date = rawDate
  }

  const kind = sp.get('kind') as StructureKind | null
  if (kind == null || !(STRUCTURE_KINDS as readonly string[]).includes(kind)) {
    throw new BadRequest(
      `kind is required and must be one of ${STRUCTURE_KINDS.join(', ')}. An ` +
        'OUTRIGHT is served by /direction/prints, which draws a rate rather ' +
        'than a spread and must not share this axis.',
    )
  }

  const raw = displayOrderTenors(
    (sp.get('tenors') ?? '').split(',').map((s) => s.trim()).filter(Boolean),
  )
  if (raw.length !== LEGS_FOR[kind]) {
    throw new BadRequest(
      `a ${kind} needs exactly ${LEGS_FOR[kind]} tenors; got ${raw.length}. ` +
        'The leg count is part of the instrument, not a filter: a 3-leg ' +
        'structure priced under 2-leg weights is a different number entirely.',
    )
  }
  for (const t of raw) {
    if (!TENOR_RE.test(t)) {
      throw new BadRequest(`tenor ${t} is not a tenor label (e.g. 10Y, 30Y, 18M)`)
    }
  }

  const rateIndex = (sp.get('rateIndex') ?? 'SOFR') as StructureRateIndex
  if (!(STRUCTURE_RATE_INDEXES as readonly string[]).includes(rateIndex)) {
    throw new BadRequest(
      `rateIndex must be one of ${STRUCTURE_RATE_INDEXES.join(', ')} — one ` +
        'index per chart. SOFR OIS sits ~1.5-2.4bp off the Fed Funds curve, so ' +
        'overlaying both draws that basis as if it were bid-offer.',
    )
  }

  const { venueClass } = parseCommon(
    new URLSearchParams(sp.get('venueClass') ? { venueClass: sp.get('venueClass')! } : {}),
  )

  const rawFwd = sp.get('fwdMaxYears')
  let fwdMaxYears = FWD_MAX_DEFAULT
  if (rawFwd != null && rawFwd !== '') {
    fwdMaxYears = Number(rawFwd)
    if (!Number.isFinite(fwdMaxYears) || fwdMaxYears < 0 || fwdMaxYears > FWD_MAX_CEILING) {
      throw new BadRequest(`fwdMaxYears must be between 0 and ${FWD_MAX_CEILING}`)
    }
  }

  return {
    date,
    kind,
    tenors: raw,
    rateIndex,
    venueClass,
    includeOffMarket: sp.get('includeOffMarket') === 'true',
    ruleStrict: sp.get('ruleStrict') !== 'false',
    fwdMaxYears,
  }
}

/** The weight CASE, by canonical leg index, for one kind. */
function weightCase(kind: StructureKind): string {
  const w = QUOTE_WEIGHTS[kind]
  const arms = w.map((q, i) => `WHEN ${i + 1} THEN ${q}`).join(' ')
  return `(CASE x.i ${arms} ELSE 0 END)`
}

/**
 * The off-market test, per LEG. Aggregated with bool_or at the unit level —
 * never applied in the WHERE, which would drop a leg and misprice the rest.
 */
const LEG_OFF_MARKET = `(
     COALESCE(l.is_off_market, false)
  OR COALESCE(l.other_payment_amount, 0) <> 0
  OR COALESCE(l.other_payment_ufro,   0) <> 0
  OR COALESCE(l.other_payment_uwin,   0) <> 0
  OR COALESCE(l.other_payment_pexh,   0) <> 0
)`

/** The latest published day. */
export function latestStructureDateSql(): string {
  return `SELECT max(as_of_date)::text AS as_of_date FROM ${DD_UNIT}`
}

/**
 * One structure, one day: every print of it, at unit grain.
 *
 * The tenor tuple is compared in CANONICAL ORDER, so '10Y,30Y' and '30Y,10Y'
 * select the same instrument and neither can select a 30s10s that does not
 * exist.
 */
export function structurePrintsSql(p: ResolvedStructureParams): BoundSql {
  const text = `
    WITH x AS (
      SELECT
        u.package_id, u.as_of_date, u.kind, u.n_legs, u.rule,
        u.deviation_bps, u.dealer_direction, u.p, u.signed_weight,
        u.structure_dv01, u.execution_timestamp, u.curve_timestamp,
        u.visibility_timestamp, u.visibility_lag_seconds, u.in_dead_zone,
        u.tau_bps, u.mid_bias_bps, u.is_block, u.is_capped,
        u.notional_imputed, u.venue_class, u.rate_index, u.special_tenor_type,
        u.curve_name, u.snapshot_policy, u.snapshot_lag_seconds,
        u.tape_generation, u.code_vintage,
        l.tenor_display, l.tenor_label, l.fixed_rate, l.notional,
        l.forward_start_years, l.forward_label,
        ${LEG_OFF_MARKET} AS leg_off_market,
        -- THE CANONICAL ORDER. Not leg_order: that is emission order and
        -- differs on 4.51% of units, which flips a 5s10s into a 10s5s.
        row_number() OVER (
          PARTITION BY u.package_id, u.as_of_date
          ORDER BY ${CANONICAL_LEG_ORDER}
        ) AS i
      FROM ${DD_UNIT} u
      JOIN ${TAPE_LEGS} l
        ON l.package_id = u.package_id AND l.as_of_date = u.as_of_date
      WHERE u.as_of_date  = $1::date
        AND u.kind        = $2
        AND u.rate_index  = $3
        AND u.venue_class = $4
        AND u.series      = 'FLOW'
        AND u.exclusion_reason IS NULL
        AND u.deviation_bps IS NOT NULL
        AND u.n_legs = $5
    ), agg AS (
      SELECT
        x.package_id, x.execution_timestamp, x.curve_timestamp,
        x.visibility_timestamp, x.visibility_lag_seconds, x.in_dead_zone,
        x.kind, x.n_legs, x.rule, x.deviation_bps, x.dealer_direction,
        x.p, x.signed_weight, x.structure_dv01, x.tau_bps, x.mid_bias_bps,
        x.is_block, x.is_capped, x.notional_imputed, x.venue_class,
        x.rate_index, x.special_tenor_type, x.curve_name, x.snapshot_policy,
        x.snapshot_lag_seconds, x.tape_generation, x.code_vintage,
        count(*)                                        AS legs_seen,
        array_agg(x.tenor_display ORDER BY x.i)         AS tenor_tuple,
        array_agg(x.tenor_label   ORDER BY x.i)         AS grid_tenors,
        array_agg(x.fixed_rate * 100 ORDER BY x.i)      AS leg_rates_pct,
        -- percent-in / bp-out, exactly as conventions.structure_price does it
        100 * sum(${weightCase(p.kind)} * x.fixed_rate * 100) AS traded_bp,
        bool_or(x.leg_off_market)                       AS is_off_market,
        max(COALESCE(x.forward_start_years, 0))         AS fwd_max_years,
        sum(abs(COALESCE(x.notional, 0)))               AS notional_total,
        bool_or(x.tenor_display LIKE '~%%')             AS any_fuzzy_tenor
      FROM x
      GROUP BY
        x.package_id, x.execution_timestamp, x.curve_timestamp,
        x.visibility_timestamp, x.visibility_lag_seconds, x.in_dead_zone,
        x.kind, x.n_legs, x.rule, x.deviation_bps, x.dealer_direction,
        x.p, x.signed_weight, x.structure_dv01, x.tau_bps, x.mid_bias_bps,
        x.is_block, x.is_capped, x.notional_imputed, x.venue_class,
        x.rate_index, x.special_tenor_type, x.curve_name, x.snapshot_policy,
        x.snapshot_lag_seconds, x.tape_generation, x.code_vintage
      -- THE LINCHPIN. Catches a partial join AND any leg lost to a filter: a
      -- 2-leg curve priced off 1 surviving leg is plausible and wrong.
      HAVING count(*) = max(x.n_legs)
    )
    SELECT
      agg.*,
      agg.traded_bp - agg.deviation_bps AS mid_bp
    FROM agg
    -- SET equality, not tuple equality: the caller cannot be expected to know
    -- the pipeline's expiration-date leg order, and guessing it from tenor
    -- years inverts the sign on 3.55% of curves. The row's own tenor_tuple
    -- comes back in canonical order and is the authority.
    WHERE ARRAY(SELECT unnest(agg.tenor_tuple) ORDER BY 1)
        = ARRAY(SELECT unnest($6::text[]) ORDER BY 1)
      AND agg.fwd_max_years <= $7${
        p.includeOffMarket ? '' : '\n      AND agg.is_off_market = false'
      }${
        p.ruleStrict ? "\n      AND agg.rule = 'RATE_VS_MID'" : ''
      }
    ORDER BY agg.execution_timestamp
  `
  return {
    text,
    values: [
      p.date, p.kind, p.rateIndex, p.venueClass, LEGS_FOR[p.kind],
      p.tenors, p.fwdMaxYears,
    ],
  }
}

/**
 * The counts, with each filter relaxed one at a time.
 *
 * Measured from the same driving predicate rather than inferred from what came
 * back: "3 off-market prints were hidden" and "there were none" are different
 * facts and a client that only sees survivors cannot tell them apart.
 */
export function structureCountsSql(p: ResolvedStructureParams): BoundSql {
  const text = `
    WITH x AS (
      SELECT u.package_id, u.as_of_date, u.n_legs, u.rule,
             l.tenor_display, l.forward_start_years,
             ${LEG_OFF_MARKET} AS leg_off_market,
             row_number() OVER (
               PARTITION BY u.package_id, u.as_of_date
               ORDER BY ${CANONICAL_LEG_ORDER}
             ) AS i
      FROM ${DD_UNIT} u
      JOIN ${TAPE_LEGS} l
        ON l.package_id = u.package_id AND l.as_of_date = u.as_of_date
      WHERE u.as_of_date = $1::date AND u.kind = $2 AND u.rate_index = $3
        AND u.venue_class = $4 AND u.series = 'FLOW'
        AND u.exclusion_reason IS NULL AND u.deviation_bps IS NOT NULL
        AND u.n_legs = $5
    ), agg AS (
      SELECT x.package_id, x.rule,
             array_agg(x.tenor_display ORDER BY x.i) AS tenor_tuple,
             bool_or(x.leg_off_market) AS off_market,
             max(COALESCE(x.forward_start_years, 0)) AS fwd
      FROM x GROUP BY x.package_id, x.rule, x.n_legs
      HAVING count(*) = max(x.n_legs)
    )
    -- A PARTITION, in priority order, so the four buckets SUM to the total.
    -- The first cut used overlapping FILTERs and 6 of 16 units on the
    -- reference cell fell into no bucket at all: a chip that says "1 hidden"
    -- while 10 are missing is worse than no chip.
    SELECT
      count(*) FILTER (WHERE NOT off_market AND fwd <= $7 AND rule = 'RATE_VS_MID')::int AS on_market,
      count(*) FILTER (WHERE off_market)::int                                            AS off_market,
      count(*) FILTER (WHERE NOT off_market AND fwd > $7)::int                           AS forward_start,
      count(*) FILTER (WHERE NOT off_market AND fwd <= $7 AND rule <> 'RATE_VS_MID')::int AS other_rule,
      count(*)::int                                                                       AS all_of_this_structure
    FROM agg
    WHERE ARRAY(SELECT unnest(tenor_tuple) ORDER BY 1)
        = ARRAY(SELECT unnest($6::text[]) ORDER BY 1)
  `
  return {
    text,
    values: [
      p.date, p.kind, p.rateIndex, p.venueClass, LEGS_FOR[p.kind],
      p.tenors, p.fwdMaxYears,
    ],
  }
}

/**
 * The continuous structure mid, from the 1-minute grid.
 *
 * MEASURED: combining the legs of arbs_dd_curve_mid_v1 under the same quote
 * weights reproduces the per-print structure mid to a median 3.98e-13 bp
 * (p95 0.0115 bp, max 0.744 bp over 3,372 prints). So this line is the same
 * object the classifier priced against, not an approximation of it.
 *
 * THE GRID IS SPOT-ONLY, AND THAT IS A HARD BOUNDARY. Measured: 0 of 4,529
 * forward-start legs match it at all (max residual 35.6 bp), and 0 of 248
 * off-date legs. 37% of CURVE units and 17% of FLY units carry a forward leg.
 * Drawing a spot par spread under forward-starting marks would put the marks
 * tens of bp off a line that is not their instrument — so the caller must not
 * request this for a forward-start population, and the route does not.
 *
 * The HAVING is not optional: a minute where only one leg published would
 * otherwise yield a "spread" that is really a single rate.
 */
export function structureMidSql(
  kind: StructureKind,
  rateIndex: StructureRateIndex,
  gridTenors: string[],
  t0Iso: string,
  t1Iso: string,
): BoundSql {
  const text = `
    WITH spec AS (
      SELECT * FROM unnest($3::text[], $4::numeric[]) AS s(tenor_label, w)
    )
    SELECT g.ts, 100 * sum(spec.w * g.mid_pct) AS mid_bp,
           min(g.curve_name) AS curve_name,
           min(g.snapshot_policy) AS snapshot_policy
    FROM ${DD_CURVE_MID} g
    JOIN spec ON spec.tenor_label = g.tenor_label
    WHERE g.rate_index = $1
      AND g.ts >= $5::timestamptz
      AND g.ts <= $6::timestamptz
    GROUP BY g.ts
    HAVING count(*) = $2
    ORDER BY g.ts
  `
  return {
    text,
    values: [
      rateIndex, gridTenors.length, gridTenors, QUOTE_WEIGHTS[kind],
      t0Iso, t1Iso,
    ],
  }
}

/**
 * The grid labels for a requested tenor tuple.
 *
 * The fuzzy marker is stripped because the GRID has no '~10Y' — a fuzzy print
 * is still priced against the canonical 10Y curve point. The tuple used for
 * INSTRUMENT IDENTITY keeps the tilde; only the grid lookup drops it.
 */
export function gridTenorsFor(tenors: string[]): string[] {
  return tenors.map((t) => t.replace('~', ''))
}

// ---------------------------------------------------------------------------
// Payload
// ---------------------------------------------------------------------------

export type StructureRow = {
  package_id: string
  execution_timestamp: string
  curve_timestamp: string | null
  visibility_lag_seconds: number | null
  in_dead_zone: boolean | null
  kind: string
  n_legs: number
  rule: string
  deviation_bps: number
  dealer_direction: 'RECEIVED' | 'PAID' | 'ABSTAINED'
  p: number | null
  signed_weight: number | null
  structure_dv01: number | null
  tenor_tuple: string[]
  leg_rates_pct: number[]
  traded_bp: number
  mid_bp: number
  is_off_market: boolean
  fwd_max_years: number
  notional_total: number | null
  special_tenor_type: string | null
  venue_class: string
  curve_name: string | null
  snapshot_policy: string | null
  tape_generation: string | null
  code_vintage: string | null
}

export type StructureMidPoint = { ts: string; mid_bp: number }

export type StructureCounts = {
  drawn: number
  onMarket: number
  offMarket: number
  forwardStart: number
  otherRule: number
  allOfThisStructure: number
}

export type StructureResponse = {
  date: string
  kind: StructureKind
  tenors: string[]
  label: string
  rateIndex: string
  venueClass: string
  clock: 'execution'
  levelUnit: 'bp'
  rows: StructureRow[]
  mid: StructureMidPoint[]
  counts: StructureCounts
  disclosures: string[]
  curve_name: string | null
  error?: string
}

/** "10s30s curve", "2s5s10s fly" — the way a trader says it. */
export function structureLabel(kind: StructureKind, tenors: string[]): string {
  const nums = tenors.map((t) => t.replace('~', '').replace(/[MY]$/, ''))
  return kind === 'CURVE'
    ? `${nums[0]}s${nums[1]}s curve`
    : `${nums[0]}s${nums[1]}s${nums[2]}s fly`
}

export type StructureDisclosureInput = {
  kind: StructureKind
  tenors: string[]
  rateIndex: string
  counts: StructureCounts
  midPoints: number
  curveName: string | null
  ruleStrict: boolean
  includeOffMarket: boolean
  forwardDrawn: number
}

export function buildStructureDisclosures(d: StructureDisclosureInput): string[] {
  const out: string[] = []
  const w = QUOTE_WEIGHTS[d.kind].join(', ')

  out.push(
    `The level is the STRUCTURE price in basis points, not a rate: ` +
      `100 x sum(q_i x leg_rate_i) under quote weights (${w}), legs in the ` +
      'pipeline’s canonical order (expiration, effective, trade id, leg order). ' +
      'Positive is an upward-sloping quote — the back leg above the front.',
  )
  out.push(
    'Each print’s mid is EXACT, not reconstructed: deviation_bps is already ' +
      'structure-grain, so mid = traded - deviation. Verified on 25,692 units ' +
      'over 26 months — CURVE 17,197 of 17,197 and FLY 8,495 of 8,495 agree to ' +
      'better than 3e-12 bp.',
  )
  out.push(
    `The LINE is the same combination applied to the 1-minute par grid — ` +
      `${d.midPoints} points from ${d.curveName ?? '—'}. It reproduces the ` +
      'per-print mid to a median 4e-13 bp (p95 0.012 bp), so it is the object ' +
      'the classifier priced against rather than an approximation of it. A ' +
      'minute where any leg did not publish is dropped rather than drawn from ' +
      'the legs that did.',
  )
  out.push(
    'Direction is a price-implied INFERENCE at STRUCTURE level: which side of ' +
      'the structure mid the print landed. In a steepener the dealer receives ' +
      'one leg and pays the other, so this is the direction of the SPREAD, ' +
      'never of a leg.',
  )
  if (d.counts.otherRule > 0) {
    out.push(
      `${d.counts.otherRule} print(s) of this structure are hidden because they ` +
        'are not priced under RATE_VS_MID. Under NPV_VS_UPFRONT the deviation ' +
        'is an edge measured against a fee, a different quantity on the same ' +
        'axis. Switch the rule filter off to see them, knowing that.',
    )
  }
  out.push(
    `Off-market: ${d.counts.offMarket} ` +
      `${d.includeOffMarket ? 'shown' : 'hidden'}. A structure counts as ` +
      'off-market if ANY leg carries an upfront — the fee lands on one leg but ' +
      'prices the whole package.',
  )
  if (d.counts.forwardStart > 0) {
    out.push(
      `${d.counts.forwardStart} forward-starting print(s) hidden. A forward ` +
        'curve is not the spot curve.',
    )
  }
  if (d.forwardDrawn > 0) {
    out.push(
      `${d.forwardDrawn} of the drawn prints are FORWARD-STARTING, so the ` +
        'continuous line is withheld: the 1-minute grid is spot-only and ' +
        'matched 0 of 4,529 forward-start legs when measured (max residual ' +
        '35.6 bp). Each print still carries its own exact mid — that one is ' +
        'the forward structure mid the classifier actually used.',
    )
  }
  out.push(
    'The leg order is the pipeline’s (expiration, effective, trade id, leg ' +
      'order), never tenor size: a tenor sort disagrees on 3.55% of curves and ' +
      'INVERTS them — 10Y10Y vs 20Y10Y reads -70.5bp canonically and +70.5bp ' +
      'sorted, off two tenor_years that differ by 0.003.',
  )
  out.push(
    'Direction is the stored classifier call, never re-derived from the sign ' +
      'of the deviation: the pipeline signs the BIAS-CORRECTED deviation ' +
      '(dev - b0), which matches on 100.000% of units against 96.1% for the ' +
      'raw sign — about 1 print in 20 would be mislabelled, and they cluster ' +
      'where |deviation| is smallest.',
  )
  out.push(
    'EXECUTION clock — where it traded, not what you could have known.',
  )
  return out
}
