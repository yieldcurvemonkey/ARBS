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

/** The reason code a unit that reached the ladder carries. */
export const DD_IN_LADDER = 'IN_LADDER'
