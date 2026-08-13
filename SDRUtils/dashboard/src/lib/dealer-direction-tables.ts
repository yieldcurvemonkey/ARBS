// ABOUTME: Single source of truth for which dealer-direction generation the
// dashboard reads.
//
// Mirrors the discipline in tape-tables.ts, and for the same reason: a
// deliberately-a-constant rather than an env var, so a missing variable can
// never silently select the wrong generation. The Python writer pins the same
// string in SDRUtils/_swappulse_scripts/_dealer_direction_schema_v1.py as
// DD_GENERATION; a test asserts the literals below.
//
// _v1 is this FEATURE's version, not the tape's. Which tape generation the
// rows were built from travels in arbs_dd_unit_v1.tape_generation on every
// row, so a reader never has to infer it.

export const DD_GENERATION = 'v1'

const d = (base: string) => `arbs_dd_${base}_${DD_GENERATION}`

export const DD_UNIT = d('unit')
export const DD_UNIT_BUCKET = d('unit_bucket')
export const DD_COVERAGE = d('coverage')
export const DD_LADDER = d('ladder')
export const DD_RUNS = d('runs')

/**
 * The intraday mid grid: the model par rate per (rate_index, tenor_label,
 * minute), so prints can be drawn against where the market actually was.
 *
 * Written by SDRUtils/_swappulse_scripts/backfill_curve_mids.py through the
 * SAME pricer that produced every direction annotation, which is what stops
 * the chart and the annotations on it from disagreeing.
 *
 * TWO RULES FOR READING IT, both measured:
 *
 * 1. Look a print up at its dealer-direction `curve_timestamp`, by EQUALITY
 *    on `ts`. That column already holds `snap_instant(pricing_ts)` — floor to
 *    the minute in New York, then step back one — and the grid is built on the
 *    same instants, so the lookup is exact (max error 2.7e-13 bp over 890
 *    prints). Looking up at the print's own execution minute returns the
 *    minute AFTER the one the annotation priced at.
 * 2. Citi publishes nothing from 23:00 to 00:59 ET, so there is no row in
 *    those two hours. CARRY THE LAST POINT FORWARD rather than interpolating
 *    or drawing a gap — it is the closest of the three, not an exact one.
 *    The direction pipeline serves an hour-00 print from that same previous
 *    22:59 snapshot, so the curve matches; the instrument does not, because
 *    at 00:xx ET the curve's reference date is still the previous business
 *    day and the grid's spot point is a business day behind the print's own.
 *    Measured on those prints: LOCF disagrees with the annotation by up to
 *    ~0.42 bp (joining forward to the next 01:00 point instead: up to
 *    ~1.20 bp). So expect a sub-basis-point gap on the ~1% of prints in ET
 *    hour 00, and none at all on the rest — rule 1 is exact, this one is not.
 */
export const DD_CURVE_MID = d('curve_mid')

/** Per (grid_date, rate_index) accounting for the grid: how many minutes the
 * curve store held, how many were served, how many rows resulted. The
 * completion check is `n_rows === n_tenors * minutes_served`. */
export const DD_CURVE_MID_DAY = d('curve_mid_day')

/** The reason code a unit that reached the ladder carries. */
export const DD_IN_LADDER = 'IN_LADDER'
