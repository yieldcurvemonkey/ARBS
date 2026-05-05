// ABOUTME: Single source of truth for the volume-grid forward x tenor
// bucket boundaries, SQL CASE expressions, and parameterised WHERE-clause
// builders. Both /api/usd-swaps-tape-v2/volume-grid and
// /api/usd-swaps-tape-v2/volume-grid/cell import from here so boundaries
// can never drift between the matrix view and its drill-down.

export type ForwardBucketId =
  | 'spot' | '6m_1y' | '1y_2y' | '2y_5y' | '5y_10y' | 'fwd_other'

export type TenorBucketId =
  | '1y' | '2y' | '2_5y' | '5y' | '5_10y' | '10y'
  | '10_20y' | '20y' | '20_30y' | '30y' | '50y'

interface Bucket<Id extends string> {
  readonly id: Id
  readonly lo: number | null
  readonly hi: number | null
  readonly label: string
}

export const FORWARD_BUCKETS: ReadonlyArray<Bucket<Exclude<ForwardBucketId, 'fwd_other'>>> = [
  { id: 'spot',   lo: null,  hi: 0.083, label: 'spot' },
  { id: '6m_1y',  lo: 0.083, hi: 1.0,   label: '6m-1Y' },
  { id: '1y_2y',  lo: 1.0,   hi: 2.0,   label: '1Y-2Y' },
  { id: '2y_5y',  lo: 2.0,   hi: 5.0,   label: '2Y-5Y' },
  { id: '5y_10y', lo: 5.0,   hi: 10.0,  label: '5-10Y' },
] as const

export const TENOR_BUCKETS: ReadonlyArray<Bucket<TenorBucketId>> = [
  { id: '1y',     lo: null, hi: 1.5,  label: '1y' },
  { id: '2y',     lo: 1.5,  hi: 2.5,  label: '2y' },
  { id: '2_5y',   lo: 2.5,  hi: 4.5,  label: '2-5y' },
  { id: '5y',     lo: 4.5,  hi: 5.5,  label: '5y' },
  { id: '5_10y',  lo: 5.5,  hi: 9.5,  label: '5-10y' },
  { id: '10y',    lo: 9.5,  hi: 11.0, label: '10y' },
  { id: '10_20y', lo: 11.0, hi: 19.5, label: '10-20y' },
  { id: '20y',    lo: 19.5, hi: 21.0, label: '20y' },
  { id: '20_30y', lo: 21.0, hi: 29.5, label: '20-30y' },
  { id: '30y',    lo: 29.5, hi: 31.0, label: '30y' },
  { id: '50y',    lo: 31.0, hi: null, label: '50y' },
] as const

export function classifyForwardBucket(years: number | null | undefined): ForwardBucketId {
  if (years == null || years < 0.083) return 'spot'
  if (years < 1.0)  return '6m_1y'
  if (years < 2.0)  return '1y_2y'
  if (years < 5.0)  return '2y_5y'
  if (years < 10.0) return '5y_10y'
  return 'fwd_other'
}

export function classifyTenorBucket(
  years: number | null | undefined,
): TenorBucketId | null {
  if (years == null) return null
  if (years < 1.5)  return '1y'
  if (years < 2.5)  return '2y'
  if (years < 4.5)  return '2_5y'
  if (years < 5.5)  return '5y'
  if (years < 9.5)  return '5_10y'
  if (years < 11.0) return '10y'
  if (years < 19.5) return '10_20y'
  if (years < 21.0) return '20y'
  if (years < 29.5) return '20_30y'
  if (years < 31.0) return '30y'
  return '50y'
}

export function buildBucketSqlCases(legAlias: string): {
  fwdCase: string
  tenorCase: string
} {
  const a = legAlias
  const fwdCase = `
    CASE
      WHEN ${a}.forward_start_years IS NULL OR ${a}.forward_start_years < 0.083 THEN 'spot'
      WHEN ${a}.forward_start_years <  1.0  THEN '6m_1y'
      WHEN ${a}.forward_start_years <  2.0  THEN '1y_2y'
      WHEN ${a}.forward_start_years <  5.0  THEN '2y_5y'
      WHEN ${a}.forward_start_years < 10.0  THEN '5y_10y'
      ELSE 'fwd_other'
    END`
  const tenorCase = `
    CASE
      WHEN ${a}.tenor_years IS NULL THEN NULL
      WHEN ${a}.tenor_years <  1.5  THEN '1y'
      WHEN ${a}.tenor_years <  2.5  THEN '2y'
      WHEN ${a}.tenor_years <  4.5  THEN '2_5y'
      WHEN ${a}.tenor_years <  5.5  THEN '5y'
      WHEN ${a}.tenor_years <  9.5  THEN '5_10y'
      WHEN ${a}.tenor_years < 11.0  THEN '10y'
      WHEN ${a}.tenor_years < 19.5  THEN '10_20y'
      WHEN ${a}.tenor_years < 21.0  THEN '20y'
      WHEN ${a}.tenor_years < 29.5  THEN '20_30y'
      WHEN ${a}.tenor_years < 31.0  THEN '30y'
      ELSE '50y'
    END`
  return { fwdCase, tenorCase }
}

export function buildBucketPredicate(
  legAlias: string,
  fwdId: string,
  tenorId: string,
  startParamIndex: number,
): { sql: string; params: number[] } {
  const fwd = FORWARD_BUCKETS.find((b) => b.id === fwdId)
  if (!fwd) throw new Error(`unknown forward bucket id: ${fwdId}`)
  const tenor = TENOR_BUCKETS.find((b) => b.id === tenorId)
  if (!tenor) throw new Error(`unknown tenor bucket id: ${tenorId}`)
  const params: number[] = []
  const a = legAlias
  const parts: string[] = []
  let pi = startParamIndex
  if (fwd.id === 'spot') {
    parts.push(`(${a}.forward_start_years IS NULL OR ${a}.forward_start_years < $${pi})`)
    params.push(fwd.hi as number)
    pi += 1
  } else {
    parts.push(`${a}.forward_start_years >= $${pi}`)
    params.push(fwd.lo as number)
    pi += 1
    if (fwd.hi != null) {
      parts.push(`${a}.forward_start_years < $${pi}`)
      params.push(fwd.hi)
      pi += 1
    }
  }
  if (tenor.lo != null) {
    parts.push(`${a}.tenor_years >= $${pi}`)
    params.push(tenor.lo)
    pi += 1
  } else {
    parts.push(`${a}.tenor_years IS NOT NULL`)
  }
  if (tenor.hi != null) {
    parts.push(`${a}.tenor_years < $${pi}`)
    params.push(tenor.hi)
    pi += 1
  }
  return { sql: parts.join(' AND '), params }
}
