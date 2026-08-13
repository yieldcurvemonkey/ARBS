// ABOUTME: Param parsing, SQL building and the refusals for the intraday
// traded-prints endpoint. Pure — no React, no I/O — so every predicate below is
// tested with no mocking.
//
// ===================================================================
// WHAT THIS ENDPOINT IS, AND THE FOUR THINGS THAT MAKE IT NOT A LIE
// ===================================================================
//
// One day, one tenor, one rate index, one venue class: every print, on the
// EXECUTION clock, against a mid reconstructed per print.
//
// 1. THERE IS NO INTRADAY PAR-RATE TABLE IN POSTGRES. Every candidate was
//    closed by measurement: OIS_RATES carries exactly 2 obs/day (19:00Z
//    ERIS_SETTLE and 21:00Z BGN, which disagree 4.8bp at 10Y and must never be
//    mixed); arbs_curve_snapshots_v1 holds discount factors, not par rates, and
//    its only genuine 1-min asset (-ERISLIVE) covers 17 days;
//    arbs_curve_intraday_blocks_v1 does hold true 1-min USD SOFR over the whole
//    window but as parquet_zstd BYTEA, unreachable from SQL; market_data is 31
//    rows at one timestamp. So the mid is reconstructed arithmetically:
//
//        mid_pct = fixed_rate * 100 - deviation_bps / 100
//
//    which is EXACT by construction, not an approximation:
//    conventions.quote_weights('OUTRIGHT', 1, RULE_RATE) == (1.0,) and
//    structure_price is percent-in/bp-out, so
//    deviation_bps === (traded_pct - mid_pct) * 100.
//
// 2. THE MID IS ONLY INVERTIBLE FOR A SINGLE-LEG OUTRIGHT UNDER RATE_VS_MID.
//    deviation_bps for a CURVE is a structure spread under weights (-1, 1) and
//    for a FLY under (-1, 2, -1); one structure-level number cannot be inverted
//    into per-leg mids. The CASE in printsSql() is a safety interlock, not a
//    convenience — the API CANNOT emit a per-leg mid for a package leg whatever
//    the client asks for, and assertNoPackageMid() re-checks the payload so the
//    guarantee survives an edit to the SELECT list.
//
// 3. THE TENOR PREDICATE IS tenor_display, NEVER tenor_label. Measured:
//    tenor_label='10Y' spans tenor_years 9.501-10.490 — a +/-6-month band.
//    tenor_display splits it into '10Y' (9.984-10.027, 17,610 legs) and '~10Y'
//    (the fuzzy remainder, 754 legs). It is an equality test on a pre-computed
//    strict label, so no epsilon is chosen or defended.
//
// 4. AN UPFRONT MAKES A FIXED RATE ARBITRARY. rule = 'RATE_VS_MID' is already a
//    complete fee filter, measured with zero leakage (OUTRIGHT unit-legs, June
//    2026: has-fee -> NPV_VS_UPFRONT 7,684 / RATE_VS_MID 0; no-fee ->
//    RATE_VS_MID 24,563), and it is a CORRECTNESS gate rather than hygiene:
//    under NPV_VS_UPFRONT, deviation_bps is edge_bps (NPV-vs-fee over DV01) — a
//    different quantity, mean 793.67 bp, max 1,362,687 bp. Feeding that into
//    mid = traded - dev/100 produces a garbage mid, not a wide one.
import { DD_CURVE_MID, DD_UNIT } from '@/lib/dealer-direction-tables'
import { TAPE_LEGS } from '@/lib/tape-tables'
import { BadRequest, parseCommon, SAMPLE_FLOOR, type VenueClass } from './route.logic'

// ---------------------------------------------------------------------------
// Allow-lists
// ---------------------------------------------------------------------------

/**
 * The eight tenors with enough prints per day to draw. Mean per-day counts on
 * the strict predicate: 81.7 / 82.7 / 51.0 / 133.0 / 35.0 / 135.7 / 21.3 / 79.0.
 *
 * 369 distinct tenor_display values exist and most are single-print junk, so
 * this is an allow-list rather than "whatever the client asks for" — a chart of
 * one print is not a chart, it is a dot with an axis around it.
 */
export const PRINT_TENORS = ['1Y', '2Y', '3Y', '5Y', '7Y', '10Y', '20Y', '30Y'] as const
export type PrintTenor = (typeof PRINT_TENORS)[number]

/** Every special_tenor_type the tape emits. The DEFAULT set is a strict subset. */
export const SPECIAL_TENOR_TYPES = [
  'STANDARD', 'IMM', 'FOMC', 'MATCHED_MATURITY', 'INVOICE_SWAP', 'MAC',
] as const
export type SpecialTenorType = (typeof SPECIAL_TENOR_TYPES)[number]

/**
 * An ALLOW-list, never a deny-list, so a type added to the tape later cannot
 * leak in silently.
 *
 *   STANDARD          in
 *   IMM               in  — IMM-dated swaps starting inside a week are ordinary
 *                           roll trades (348 units on the reference day). They
 *                           carry a 1.7x wider median |deviation| than STANDARD
 *                           (0.217 vs 0.128 bp), which is disclosed, not hidden.
 *   MATCHED_MATURITY  in  — measured 0 forward-starting at 10Y; a spot par swap
 *                           at a broken maturity, comparable once tenor_display
 *                           is strict.
 *   FOMC              OUT — repriced against a curve with NO discrete meeting
 *                           steps, so its deviation is dominated by model error:
 *                           median |deviation| 1.994 vs 0.295 bp on Fed Funds
 *                           (6.8x), 0.697 vs 0.174 bp on SOFR (4.0x).
 *   MAC               OUT — trades on a round standardised coupon with the
 *                           economics in the upfront; the fixed rate is not a
 *                           market level. 760 legs at 10Y, 679 forward-starting.
 *   INVOICE_SWAP      OUT — CTD-dated against a bond hedge; excluded upstream
 *                           from stir-flow for the same reason.
 *
 * NULL fails `= ANY(...)` and is therefore excluded. That direction is
 * deliberate — refuse what you cannot classify — and it costs nothing today:
 * measured special_tenor_type NULL rate on arbs_dd_unit_v1 is 0 of 12,396
 * across 2024/2025/2026 sample days. It is a guard, not a filter, and the count
 * surfaces as dropped.unknownSpecialTenorType so it can never go quiet.
 */
export const DEFAULT_SPECIAL_TENOR_TYPES: SpecialTenorType[] = [
  'STANDARD', 'IMM', 'MATCHED_MATURITY',
]

export const PRINT_KINDS = ['OUTRIGHT', 'CURVE', 'FLY', 'PKG'] as const
export type PrintKind = (typeof PRINT_KINDS)[number]

export const RATE_INDEXES = ['SOFR', 'FED_FUNDS'] as const
export type RateIndex = (typeof RATE_INDEXES)[number]

/**
 * ~7.3 days. A forward start is not the same instrument as a spot swap of the
 * same tenor, and this is the single largest filter on the panel.
 *
 * Measured at tenor_label='10Y': 35.7% of legs are forward-starting, max
 * forward start 30.03 YEARS, and mean rate by band runs spot 4.0043 /
 * fwd 4m-1.2y 4.0676 / fwd >1.2y 4.2650, with IMM_U2036 (a 10y10y) at 4.6689 —
 * 66bp above spot, on a chart whose whole y-axis is 5.9bp wide.
 */
export const FWD_MAX_DEFAULT = 0.02

/**
 * Above this the request is REFUSED rather than served with a warning.
 *
 * fwdMaxYears is a view-DEFINING control, not an overlay: raising it changes
 * which instrument the chart is about, so the title, the y-domain and a warning
 * strip all change with it. Past a quarter of a year there is no honest single
 * y-axis left to put the marks on.
 */
export const FWD_MAX_CEILING = 0.25

export type TenorMatch = 'strict' | 'band'

export type PrintsFilters = {
  kinds: PrintKind[]
  specialTenorTypes: SpecialTenorType[]
  fwdMaxYears: number
  tenorMatch: TenorMatch
  includeOffMarket: boolean
}

export type PrintsParams = {
  /** null means "the latest published as_of_date", resolved by the route. */
  date: string | null
  tenor: PrintTenor
  rateIndex: RateIndex
  venueClass: VenueClass
  /** Pinned. LIFECYCLE is refused — see parsePrintsParams. */
  series: 'FLOW'
} & PrintsFilters

/** date + every filter, with the day already resolved. What the SQL builders take. */
export type ResolvedPrintsParams = PrintsParams & { date: string }

// ---------------------------------------------------------------------------
// Parsing and the refusals
// ---------------------------------------------------------------------------

function parseCsv(raw: string | null, fallback: string[]): string[] {
  if (raw == null || raw === '') return fallback
  return raw.split(',').map((s) => s.trim()).filter((s) => s !== '')
}

export function parsePrintsParams(sp: URLSearchParams): PrintsParams {
  // --- date -----------------------------------------------------------------
  const rawDate = sp.get('date')
  let date: string | null = null
  if (rawDate) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(rawDate)) {
      throw new BadRequest('date must be YYYY-MM-DD')
    }
    if (rawDate < SAMPLE_FLOOR) {
      throw new BadRequest(
        `date is before the sample floor ${SAMPLE_FLOOR}. The exclusion rate ` +
          'steps -3.2pp across the ingest break and the tape carries no ' +
          'termination events before it.',
      )
    }
    date = rawDate
  }

  // --- tenor (required; there is no "all tenors" view) -----------------------
  const rawTenor = sp.get('tenor')
  if (!rawTenor) {
    throw new BadRequest(
      `tenor is required and must be one of ${PRINT_TENORS.join(', ')}. There ` +
        'is no all-tenor view: a 2Y and a 30Y print do not share a rate axis.',
    )
  }
  if (!(PRINT_TENORS as readonly string[]).includes(rawTenor)) {
    throw new BadRequest(
      `tenor must be one of ${PRINT_TENORS.join(', ')}. 369 distinct ` +
        'tenor_display values exist on the tape and most are single-print ' +
        'junk, so this is an allow-list rather than a pass-through.',
    )
  }
  const tenor = rawTenor as PrintTenor

  // --- rate index -----------------------------------------------------------
  const rateIndex = (sp.get('rateIndex') ?? 'SOFR') as RateIndex
  if (!(RATE_INDEXES as readonly string[]).includes(rateIndex)) {
    throw new BadRequest(
      `rateIndex must be one of ${RATE_INDEXES.join(', ')} — one index per ` +
        'chart, never mixed. SOFR OIS sits ~1.5-2.4bp off the Fed Funds curve ' +
        '(the SOFR-FF basis), so overlaying both on one line draws that basis ' +
        'as if it were bid-offer. That is the mislabelling commit 2d185a2a ' +
        'fixed once already.',
    )
  }

  // --- venue class ----------------------------------------------------------
  // Reuse parseCommon's refusal verbatim rather than restating it: three
  // series, never summed. A fresh URLSearchParams is passed so parseCommon's
  // other params (series/from/to) take their defaults and cannot leak in here.
  const rawVenue = sp.get('venueClass')
  const { venueClass } = parseCommon(
    new URLSearchParams(rawVenue ? { venueClass: rawVenue } : {}),
  )

  // --- series: PINNED --------------------------------------------------------
  // A termination or amendment prints a SEASONED coupon from an earlier
  // vintage. On a rate axis that is off-mid for exactly the same structural
  // reason an upfront trade is, so it is refused rather than drawn faintly.
  // Reversible in one line if a lifecycle view is wanted — but as a separate
  // chart, not an overlay.
  const rawSeries = sp.get('series')
  if (rawSeries != null && rawSeries !== 'FLOW') {
    throw new BadRequest(
      'series is pinned to FLOW on this endpoint. A LIFECYCLE print is a ' +
        'termination or an amendment carrying a SEASONED coupon struck at an ' +
        'earlier vintage, so its fixed rate is not a current market level — ' +
        'off-mid by construction, the same reason an upfront trade is. A ' +
        'lifecycle view belongs in its own chart, not on this y-axis.',
    )
  }

  // --- kinds ----------------------------------------------------------------
  const kinds = parseCsv(sp.get('kinds'), ['OUTRIGHT'])
  for (const k of kinds) {
    if (!(PRINT_KINDS as readonly string[]).includes(k)) {
      throw new BadRequest(`kinds must be a comma list of ${PRINT_KINDS.join(', ')}; got ${k}`)
    }
  }

  // --- special tenor types --------------------------------------------------
  const specialTenorTypes = parseCsv(sp.get('specialTenorTypes'), DEFAULT_SPECIAL_TENOR_TYPES)
  for (const s of specialTenorTypes) {
    if (!(SPECIAL_TENOR_TYPES as readonly string[]).includes(s)) {
      throw new BadRequest(
        `specialTenorTypes must be a comma list of ${SPECIAL_TENOR_TYPES.join(', ')}; ` +
          `got ${s}. This is an allow-list, never a deny-list, so a type added ` +
          'to the tape later cannot leak into the chart unnoticed.',
      )
    }
  }

  // --- forward-start ceiling ------------------------------------------------
  const rawFwd = sp.get('fwdMaxYears')
  let fwdMaxYears = FWD_MAX_DEFAULT
  if (rawFwd != null && rawFwd !== '') {
    fwdMaxYears = Number(rawFwd)
    if (!Number.isFinite(fwdMaxYears) || fwdMaxYears < 0 || fwdMaxYears > FWD_MAX_CEILING) {
      throw new BadRequest(
        `fwdMaxYears must be between 0 and ${FWD_MAX_CEILING}. A forward start ` +
          'is not the same instrument as a spot swap of the same tenor: at ' +
          'tenor_label=10Y, mean rate runs 4.0043 spot against 4.2650 for ' +
          'forwards beyond 1.2y, and IMM_U2036 — a 10y10y — prints at 4.6689, ' +
          '66bp above spot on a y-axis 5.9bp wide. Beyond a quarter of a year ' +
          'there is no honest single axis left to draw them on.',
      )
    }
  }

  const tenorMatch = (sp.get('tenorMatch') ?? 'strict') as TenorMatch
  if (tenorMatch !== 'strict' && tenorMatch !== 'band') {
    throw new BadRequest('tenorMatch must be strict or band')
  }

  const includeOffMarket = sp.get('includeOffMarket') === 'true'

  return {
    date,
    tenor,
    rateIndex,
    venueClass,
    series: 'FLOW',
    kinds: kinds as PrintKind[],
    specialTenorTypes: specialTenorTypes as SpecialTenorType[],
    fwdMaxYears,
    tenorMatch,
    includeOffMarket,
  }
}

// ---------------------------------------------------------------------------
// SQL
// ---------------------------------------------------------------------------

export type BoundSql = { text: string; values: unknown[] }

/**
 * The composite off-market test, as ONE expression, used in three places: the
 * default WHERE, the mid interlock, and the counts.
 *
 * THE 0-FILLED TRAP: other_payment_ufro / uwin / pexh are 0-filled and NEVER
 * NULL (0 nulls in 96,814 rows), so `count(col)` is meaningless on them and
 * `IS NULL` finds nothing. Only `<> 0` works, and COALESCE keeps it null-safe
 * against a future column that does allow NULL.
 */
const OFF_MARKET_EXPR = `(
       COALESCE(l.is_off_market, false)
    OR COALESCE(l.other_payment_amount, 0) <> 0
    OR COALESCE(l.other_payment_ufro,   0) <> 0
    OR COALESCE(l.other_payment_uwin,   0) <> 0
    OR COALESCE(l.other_payment_pexh,   0) <> 0
  )`

/** The six clauses that keep a fee-bearing print off a rate axis. */
const OFF_MARKET_PREDICATE = `
  AND COALESCE(l.is_off_market, false)      = false
  AND COALESCE(l.other_payment_amount, 0)   = 0
  AND COALESCE(l.other_payment_ufro,   0)   = 0
  AND COALESCE(l.other_payment_uwin,   0)   = 0
  AND COALESCE(l.other_payment_pexh,   0)   = 0`

/** The latest published day. The panel's date input takes its `max` from this. */
export function latestDateSql(): string {
  return `SELECT max(as_of_date)::text AS as_of_date FROM ${DD_UNIT}`
}

/**
 * One day of prints.
 *
 * DRIVE FROM THE UNIT TABLE, ALWAYS. Never put a bare as_of_date predicate on
 * arbs_usd_swap_tape_legs_v3: that column is NOT indexed there (only
 * package_id, execution_timestamp, original_execution_timestamp and the
 * composite category indexes), so driving from legs would seq-scan 2.08M rows.
 * EXPLAIN (ANALYZE, BUFFERS) of this statement: 36.1 ms, all buffers shared
 * hit, via idx_dd_v1_unit_asof (bitmap) -> nested loop ->
 * idx_tape_v3_legs_package. No new index is required.
 *
 * THE JOIN KEY IS package_id, MEASURED. arbs_dd_unit_v1.package_id matches the
 * tape 100.0000% both directions over five days spanning the whole tape;
 * unit_key matches only 21.7-29.3% and must never be used — a single-leg print
 * that carries a package id is keyed by that id in the display view and by its
 * raw trade_id in unit_key.
 */
export function printsSql(p: ResolvedPrintsParams): BoundSql {
  // band mode is the ONLY path to tenor_label, and the response announces it.
  const tenorPredicate =
    p.tenorMatch === 'band' ? 'l.tenor_label   = $6' : 'l.tenor_display = $6'

  const text = `
    SELECT
      u.package_id, l.trade_id,
      u.execution_timestamp, u.visibility_timestamp, u.visibility_lag_seconds,
      u.dealer_direction, u.dealer_sign, u.p, u.signed_weight,
      u.deviation_bps, u.tau_bps, u.mid_bias_bps, u.in_dead_zone,
      u.kind, u.n_legs, u.rule, u.special_tenor_type, u.rate_index,
      u.venue_class, u.is_block, u.is_capped, u.structure_dv01,
      u.curve_name, u.curve_timestamp, u.snapshot_lag_seconds, u.snapshot_policy,
      u.notional_imputed, u.tape_generation, u.code_vintage,
      l.notional, l.is_notional_capped,
      l.effective_date::text  AS effective_date,
      l.expiration_date::text AS expiration_date,
      -- The fuzzy +/-6-month band column (9.501-10.490 at 10Y) is deliberately
      -- NOT selected: a column on the wire is a column something eventually
      -- filters on. A logic test asserts the default statement never names it.
      l.tenor_years, l.tenor_display,
      l.forward_start_years, l.forward_label,
      -- The EFFECTIVE off-market flag, not the raw column: a print carrying an
      -- upfront in any of the four payment fields is off mid by construction
      -- even when is_off_market was never set. This is the flag the y-domain
      -- and the edge-pinning read.
      ${OFF_MARKET_EXPR} AS is_off_market,
      l.fixed_rate * 100.0 AS traded_pct,
      -- THE SAFETY INTERLOCK. A structure-level deviation cannot be inverted
      -- into a per-leg mid (CURVE weights (-1,1), FLY weights (-1,2,-1)), and
      -- an off-market print's deviation is a fee, not a distance from mid. So
      -- the mid is emitted ONLY where the inversion is exact, whatever the
      -- client asked for. assertNoPackageMid() re-checks the payload.
      CASE WHEN u.kind = 'OUTRIGHT' AND u.rule = 'RATE_VS_MID' AND u.n_legs = 1
                AND NOT ${OFF_MARKET_EXPR}
           THEN l.fixed_rate * 100.0 - u.deviation_bps / 100.0 END AS mid_pct
    FROM ${DD_UNIT} u
    JOIN ${TAPE_LEGS} l
      ON l.package_id = u.package_id AND l.as_of_date = u.as_of_date
    WHERE u.as_of_date = $1::date
      AND u.rate_index = $2
      AND u.venue_class = $3
      AND u.series = 'FLOW'
      AND u.exclusion_reason IS NULL
      -- Measured-redundant (deviation_bps IS NULL AND exclusion_reason IS NULL
      -- = 0 of 16,362) and kept as a guard on the mid arithmetic: a NULL here
      -- would silently produce a NULL mid rather than an error.
      AND u.deviation_bps IS NOT NULL
      AND u.kind = ANY($4::text[])
      AND u.rule = 'RATE_VS_MID'
      AND u.special_tenor_type = ANY($5::text[])
      AND ${tenorPredicate}
      AND COALESCE(l.forward_start_years, 0) <= $7${
        p.includeOffMarket ? '' : OFF_MARKET_PREDICATE
      }
    ORDER BY u.execution_timestamp
  `
  return {
    text,
    values: [
      p.date, p.rateIndex, p.venueClass, p.kinds, p.specialTenorTypes,
      p.tenor, p.fwdMaxYears,
    ],
  }
}

/**
 * Every chip on screen, measured in the same round trip.
 *
 * The counts come from a SECOND query with the same driving predicate and the
 * filters relaxed one at a time, rather than being inferred from what came
 * back. "11 off-market prints were hidden" and "no off-market prints exist
 * today" are different facts and a client that only sees the survivors cannot
 * tell them apart.
 *
 * In band mode the driving predicate is tenor_label and the strict subset is a
 * FILTER inside the SAME scan, so admittedByLoosening is exact rather than an
 * estimate. (tenor_display = 'X' is a strict subset of tenor_label = 'X':
 * measured 0 exceptions over June 2026.)
 */
export function printsCountsSql(p: ResolvedPrintsParams): BoundSql {
  const tenorPredicate =
    p.tenorMatch === 'band' ? 'l.tenor_label   = $6' : 'l.tenor_display = $6'

  const text = `
    WITH base AS (
      SELECT
        u.kind,
        u.special_tenor_type,
        l.tenor_display,
        COALESCE(l.forward_start_years, 0) AS fwd,
        ${OFF_MARKET_EXPR} AS off_market
      FROM ${DD_UNIT} u
      JOIN ${TAPE_LEGS} l
        ON l.package_id = u.package_id AND l.as_of_date = u.as_of_date
      WHERE u.as_of_date = $1::date
        AND u.rate_index = $2
        AND u.venue_class = $3
        AND u.series = 'FLOW'
        AND u.exclusion_reason IS NULL
        AND u.deviation_bps IS NOT NULL
        AND u.rule = 'RATE_VS_MID'
        AND ${tenorPredicate}
    ), tagged AS (
      SELECT *,
             kind = ANY($4::text[])               AS kind_ok,
             special_tenor_type = ANY($5::text[]) AS stt_ok,
             fwd <= $7                            AS fwd_ok
      FROM base
    )
    SELECT
      -- The on-market population, independent of includeOffMarket. It is the
      -- denominator every share on screen is taken over, so the "off-market
      -- hidden: n (x%)" chip reads the same whether they are shown or not.
      count(*) FILTER (WHERE kind_ok AND stt_ok AND fwd_ok AND NOT off_market)
        AS on_market,
      count(*) FILTER (WHERE kind_ok AND stt_ok AND fwd_ok AND off_market)
        AS off_market,
      count(*) FILTER (WHERE kind_ok AND stt_ok AND NOT fwd_ok AND NOT off_market)
        AS forward_start,
      count(*) FILTER (WHERE kind_ok AND NOT stt_ok AND special_tenor_type IS NOT NULL
                             AND fwd_ok AND NOT off_market)
        AS special_tenor_type,
      count(*) FILTER (WHERE kind_ok AND special_tenor_type IS NULL
                             AND fwd_ok AND NOT off_market)
        AS unknown_special_tenor_type,
      count(*) FILTER (WHERE NOT kind_ok AND stt_ok AND fwd_ok AND NOT off_market)
        AS package_legs,
      -- The strict subset of whatever the driving predicate admitted. In band
      -- mode the difference is exactly what loosening bought.
      count(*) FILTER (WHERE kind_ok AND stt_ok AND fwd_ok AND NOT off_market
                             AND tenor_display = $6)
        AS strict_subset
    FROM tagged
  `
  return {
    text,
    values: [
      p.date, p.rateIndex, p.venueClass, p.kinds, p.specialTenorTypes,
      p.tenor, p.fwdMaxYears,
    ],
  }
}

// ---------------------------------------------------------------------------
// The continuous mid
// ---------------------------------------------------------------------------

/**
 * THE LINE IS NOW REAL, AND IT IS A DIFFERENT OBJECT FROM THE MARKS' MID.
 *
 * arbs_dd_curve_mid_v1 holds a 1-minute par grid built by the SAME
 * SessionBranchPricer, against the SAME Citi minute curve, that repriced every
 * print. So the chart no longer has to draw its line through the prints
 * themselves — which was never a mid, only a polyline through wherever somebody
 * happened to trade.
 *
 * Measured, 3,206 OUTRIGHT prints over 7 days spanning the whole window, grid
 * point taken at the minute of the print's OWN curve snapshot:
 *
 *   special_tenor_type   n       median resid    p95 |resid|   max |resid|
 *   SOFR STANDARD        2,850   0.000000 bp     0.132 bp      15.62 bp
 *   SOFR IMM               334   0.000000 bp     0.010 bp       1.49 bp
 *   FED_FUNDS STANDARD      19   4.4e-14 bp      0.276 bp       0.276 bp
 *   FED_FUNDS IMM            3   8.9e-14 bp      8.9e-14 bp     8.9e-14 bp
 *
 * The median is EXACTLY zero because for a spot STANDARD swap the grid point
 * and the print are the same instrument priced by the same code. The tail is
 * the instrument differing, not the mid: of the 9 prints beyond 0.5 bp, the
 * median maturity gap to the grid's canonical swap is 6 days and the median
 * effective-date gap 4 days, and NOT ONE is an exact instrument match, against
 * 62.5% exact in the sub-0.5bp population. A broken maturity inside the strict
 * tenor_display band is a different swap; the line is right and the mark is
 * somewhere else for a nameable reason.
 *
 * This is why the reconstructed per-print mid is KEPT rather than replaced. It
 * is exact for its own print by construction, it is what deviation_bps is
 * measured against, and the residual between the two is a diagnostic the panel
 * puts on screen rather than a discrepancy it hides.
 */

/**
 * Minutes of grid either side of the first and last drawn print.
 *
 * The window is taken from the DRAWN ROWS, not from a calendar day, and that is
 * deliberate: a tape as_of_date is not an ET calendar day (prints land at ET
 * hours 20-23 of the previous evening through 17 of the day), so any
 * date-to-window rule would be a calendar theory that could quietly go wrong.
 * min/max of what is actually on screen cannot.
 */
export const MID_PAD_MINUTES = 15

/**
 * Above this, no segment is drawn between two consecutive grid points.
 *
 * Measured on SOFR 10Y over the same 7 days: WITHIN a grid day the consecutive
 * gap is 1 min 8,293 times, 2 min 170, 3 min 17, 4 min once and 5 min once —
 * and the count of intra-day gaps exceeding 5 minutes is ZERO on every one of
 * the seven days. Every larger gap in the table is a jump BETWEEN days: the
 * overnight hole, which is ~2 hours at minimum.
 *
 * 10 minutes therefore sits two orders of magnitude clear of both sides. It
 * never breaks a live session and it always breaks the hole.
 */
export const MID_GRID_GAP_MINUTES = 10

export type MidGridPoint = {
  /** ISO instant. Always on a whole minute — 0 of 22.7M rows carry a second. */
  ts: string
  mid_pct: number
}

export type MidGrid = {
  /**
   * Whether a grid exists for this (rate_index, tenor) AT ALL, which is a
   * different fact from "the grid is empty over this window".
   *
   * MEASURED COVERAGE: SOFR carries all 8 chart tenors. FED_FUNDS carries 12
   * tenors and is MISSING 7Y, 20Y and 30Y. On those three the panel falls back
   * to the reconstructed polyline and says so — it does not draw a blank and
   * leave the reader to guess whether the market or the pipeline is absent.
   */
  available: boolean
  points: MidGridPoint[]
  curve_name: string | null
  snapshot_policy: string | null
  /** ISO bounds actually queried, so the client can show what it asked for. */
  window: [string, string] | null
}

/** Does the grid carry this (index, tenor) at all? Index-only on the PK prefix. */
export function midGridAvailabilitySql(): string {
  return `SELECT EXISTS (
            SELECT 1 FROM ${DD_CURVE_MID} WHERE rate_index = $1 AND tenor_label = $2
          ) AS ok`
}

/**
 * The grid over one window.
 *
 * TENOR IS ALWAYS p.tenor, NEVER the tenor_label of a band-mode row. The grid
 * is built on canonical tenors only; in band mode the marks may span
 * 9.50-10.49y but there is exactly one 10Y grid, and pretending otherwise would
 * mean picking a different line per mark.
 *
 * WHERE is (equality, equality, range) on the primary key
 * (rate_index, tenor_label, ts), so this is a single ordered index scan.
 */
export function midGridSql(
  rateIndex: RateIndex,
  tenor: PrintTenor,
  t0Iso: string,
  t1Iso: string,
): BoundSql {
  const text = `
    SELECT g.ts, g.mid_pct, g.curve_name, g.snapshot_policy
    FROM ${DD_CURVE_MID} g
    WHERE g.rate_index  = $1
      AND g.tenor_label = $2
      AND g.ts >= $3::timestamptz
      AND g.ts <= $4::timestamptz
    ORDER BY g.ts
  `
  return { text, values: [rateIndex, tenor, t0Iso, t1Iso] }
}

/**
 * The [first print - pad, last print + pad] window, or null when nothing is
 * drawn.
 *
 * Null is the honest answer for an empty day: a line with no marks under it is
 * a chart about a curve, and this panel is a chart about trades.
 */
export function midWindow(
  rows: Pick<PrintRow, 'execution_timestamp'>[],
  padMinutes: number = MID_PAD_MINUTES,
): [string, string] | null {
  let lo = Number.POSITIVE_INFINITY
  let hi = Number.NEGATIVE_INFINITY
  for (const r of rows) {
    const t = new Date(r.execution_timestamp).getTime()
    if (!Number.isFinite(t)) continue
    if (t < lo) lo = t
    if (t > hi) hi = t
  }
  if (!Number.isFinite(lo) || !Number.isFinite(hi)) return null
  const pad = padMinutes * 60_000
  return [new Date(lo - pad).toISOString(), new Date(hi + pad).toISOString()]
}

// ---------------------------------------------------------------------------
// The payload
// ---------------------------------------------------------------------------

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
  rate_index: RateIndex
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
  /** null for every non-OUTRIGHT and every off-market row, by SQL construction. */
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
  /** The on-market population, measured. Toggle-invariant, so shares over
   *  (onMarket + offMarket) do not move when off-market marks are switched on. */
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
  /** There is no clock toggle in v1 — see buildDisclosures. */
  clock: 'execution'
  filters: PrintsFilters
  looseTenor: boolean
  admittedByLoosening: number | null
  observedTenorYears: [number, number] | null
  rows: PrintRow[]
  /** The continuous 1-minute par grid over the drawn window. */
  mid: MidGrid
  counts: PrintsCounts
  disclosures: string[]
  provenance: PrintsProvenance
}

/**
 * The per-leg-mid guard, asserted rather than commented.
 *
 * The CASE in printsSql() makes this impossible today. SELECT lists get
 * edited; this check survives that edit, and it throws rather than rendering —
 * a per-leg mid on a package leg is the inversion you cannot recover from once
 * a reader has seen it.
 */
export function assertNoPackageMid(rows: Pick<PrintRow, 'kind' | 'mid_pct'>[]): void {
  for (const r of rows) {
    if (r.kind !== 'OUTRIGHT' && r.mid_pct != null) {
      throw new Error(
        `a ${r.kind} row carries mid_pct=${r.mid_pct}. deviation_bps for a ` +
          'CURVE is a structure spread under weights (-1, 1) and for a FLY ' +
          'under (-1, 2, -1); one structure-level number cannot be inverted ' +
          'into per-leg mids, so any per-leg mid drawn from it is fiction.',
      )
    }
  }
}

/** Median of a numeric sample, nulls dropped. Returns null on an empty sample. */
export function median(xs: (number | null | undefined)[]): number | null {
  const v = xs.filter((x): x is number => x != null && Number.isFinite(x)).sort((a, b) => a - b)
  if (v.length === 0) return null
  const mid = Math.floor(v.length / 2)
  return v.length % 2 ? v[mid]! : (v[mid - 1]! + v[mid]!) / 2
}

export type DisclosureInput = {
  filters: PrintsFilters
  counts: PrintsCounts
  provenance: PrintsProvenance
  looseTenor: boolean
  admittedByLoosening: number | null
  observedTenorYears: [number, number] | null
  tenor: string
  mid: MidGrid
  rateIndex: string
}

/**
 * The assumptions strip, served by the API so the API and the UI cannot
 * disagree about what the chart is claiming.
 *
 * Every entry carries its measurement. A caveat without a number is a mood.
 */
export function buildDisclosures(d: DisclosureInput): string[] {
  const out: string[] = []
  // The on-market population, not the rows returned: the share must not move
  // when the off-market toggle is flipped.
  const total = d.counts.onMarket + d.counts.dropped.offMarket
  const pct = (n: number, den: number) => (den > 0 ? `${((n / den) * 100).toFixed(1)}%` : '0.0%')

  out.push(
    'Direction is a price-implied INFERENCE, not observed party identity: the ' +
      'model reads which side of the mid the print landed. A model-labelled ' +
      'flow proxy, not a counterparty record.',
  )
  // THE LINE AND THE MARKS' MID ARE TWO OBJECTS. Which one the line came from
  // changes what the chart is claiming, so it is stated first and never
  // inferred from whether the line happens to be there.
  if (d.mid.available && d.mid.points.length > 0) {
    out.push(
      `The LINE is a MODELLED 1-minute par grid — ${d.mid.points.length} points ` +
        `from ${d.mid.curve_name ?? '—'} under ${d.mid.snapshot_policy ?? '—'} — ` +
        'not a quoted mid and not a tradable level. It is built by the same ' +
        'pricer, against the same curve, that repriced every mark. Where the ' +
        'print is the same instrument as the grid point the two agree EXACTLY ' +
        '(median residual 0.000000bp, p95 0.132bp over 3,206 prints); the tail ' +
        'is the instrument differing, not the mid — of 9 prints beyond 0.5bp, ' +
        'the median maturity gap to the grid swap is 6 days and none is an ' +
        'exact instrument match.',
    )
    out.push(
      'The line BREAKS rather than bridging: no segment is drawn across a gap ' +
        'over 10 minutes. Measured, intra-session consecutive gaps are 1-5 ' +
        'minutes and NO intra-day gap exceeds 5 minutes on any sampled day, ' +
        'while the overnight hole is ~2 hours — so a break is always a real ' +
        'absence. The 23:00-00:59 ET hole is Citi’s publication gap and ' +
        'carries no curve at all; prints there were repriced off a stale ' +
        'snapshot under the out-of-session policy, which their tooltip shows.',
    )
  } else {
    out.push(
      `NO CONTINUOUS MID IS AVAILABLE for ${d.rateIndex} ${d.tenor}` +
        (d.mid.available
          ? ' over this window, so the line falls back to the per-print reconstruction.'
          : ': the 1-minute par grid does not carry this tenor on this index. ' +
            'Fed Funds is built on 12 tenors and has no 7Y, 20Y or 30Y; SOFR ' +
            'carries all eight. The line falls back to the per-print ' +
            'reconstruction.') +
        ' That fallback is a polyline through the prints themselves — mid = ' +
        'traded - deviation, exact per print but existing only at print times, ' +
        'with a noise floor of 0.32-0.57bp of adjacent-diff stdev. It is not a ' +
        'picture of the market between trades.',
    )
  }
  out.push(
    `Each MARK’s own mid is reconstructed: mid = traded - deviation, against ` +
      `${d.provenance.curve_name ?? '—'} under ${d.provenance.snapshot_policy ?? '—'}. ` +
      'That is what deviation_bps — and therefore the direction call — is ' +
      'measured against, so it is kept even when the grid draws the line.',
  )
  out.push(
    `EXECUTION clock — where it traded, not what you could have known. Median ` +
      `reporting lag ${d.provenance.median_visibility_lag_seconds ?? '—'}s ` +
      `(max ${d.provenance.max_visibility_lag_seconds ?? '—'}s). The ladder ` +
      'aggregates on the availability clock; this chart deliberately does not, ' +
      'because the reconstructed mid is a function of execution time.',
  )
  if (d.filters.specialTenorTypes.includes('FOMC')) {
    out.push(
      'FOMC-DATED SWAPS ARE INCLUDED. A meeting-to-meeting swap is repriced ' +
        'against a curve with NO discrete meeting steps, so its deviation is ' +
        'dominated by model error rather than bid-offer: median |deviation| ' +
        '1.994bp vs 0.295bp on Fed Funds (6.8x) and 0.697bp vs 0.174bp on ' +
        'SOFR (4.0x), with per-meeting medians flipping sign by 1-2bp on both ' +
        'indices together.',
    )
  } else {
    out.push(
      'FOMC-dated swaps are excluded by default: repriced against a curve with ' +
        'no discrete meeting steps, their deviation runs 6.8x wider on Fed ' +
        'Funds and 4.0x on SOFR than everything else on the same days.',
    )
  }
  out.push(
    `Off-market: ${d.counts.dropped.offMarket} ` +
      `(${pct(d.counts.dropped.offMarket, total)}) ` +
      `${d.filters.includeOffMarket ? 'shown, edge-pinned and outside the y-domain' : 'hidden'}. ` +
      'A print with an upfront is off mid BY CONSTRUCTION — its fixed rate is ' +
      'arbitrary — and including them in the domain stretches the axis 31x ' +
      '(4.000-4.059 becomes 2.3825-4.206) from ~8% of the rows.',
  )
  out.push(
    `Forward-starting: ${d.counts.dropped.forwardStart} hidden at a ceiling of ` +
      `${d.filters.fwdMaxYears}y. A 10y10y is not a 10Y — measured 66bp apart ` +
      '(IMM_U2036 at 4.6689 against 4.0043 spot).',
  )
  if (d.provenance.size_not_read > 0) {
    out.push(
      `${d.provenance.size_not_read} prints where the SIZE was not read ` +
        '(block cap or imputed notional) are drawn with a dashed outline. The ' +
        'level is real; the area is a floor, not a measurement.',
    )
  }
  out.push(
    `${(d.provenance.dead_zone_share * 100).toFixed(0)}% of these calls sit ` +
      'inside the dead zone — a REPORTING-ONLY flag. Nothing in the ' +
      'aggregation depends on it, so the marks are not faded and none are ' +
      'dropped: at 92% of a day, conviction-by-opacity would fade nearly ' +
      'every mark to illegibility while removing no error.',
  )
  if (d.filters.specialTenorTypes.includes('IMM')) {
    out.push(
      'IMM legs are in the default set and carry a 1.7x wider median ' +
        '|deviation| than STANDARD (0.217 vs 0.128 bp).',
    )
  }
  if (d.counts.dropped.unknownSpecialTenorType > 0) {
    out.push(
      `${d.counts.dropped.unknownSpecialTenorType} prints carry a NULL ` +
        'special_tenor_type and were refused: the allow-list excludes what it ' +
        'cannot classify. Measured NULL rate is 0 of 12,396 across 2024-2026, ' +
        'so this is normally a guard rather than a filter.',
    )
  }
  if (d.looseTenor) {
    const obs = d.observedTenorYears
    out.push(
      `LOOSE TENOR: tenor_label ${d.tenor} spans tenor_years 9.50-10.49 at 10Y ` +
        `— a +/-6-month band — against tenor_display's 9.984-10.027. ` +
        `+${d.admittedByLoosening ?? 0} prints admitted` +
        (obs ? `; the returned set runs ${obs[0].toFixed(4)}-${obs[1].toFixed(4)}y.` : '.'),
    )
  }
  out.push(
    'Venue classes are never summed: D2C, D2D and VENUE_UNKNOWN are three ' +
      'separate series, and dealers recycling risk among themselves is not ' +
      'customer flow.',
  )
  out.push(
    `Provenance: tape ${d.provenance.tape_generation}, dd ` +
      `${d.provenance.dd_generation}, code ${d.provenance.code_vintage}.`,
  )
  return out
}
