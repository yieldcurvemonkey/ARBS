// ABOUTME: Turns the dd_* fields hung off a tape row into what the grid draws.
// Pure — no React, no I/O — so the sign mapping is testable directly.
//
// ===================================================================
// THE SIGN CONVENTION. IT IS PINNED, AND A TEST HAND-TRACES IT.
// ===================================================================
//
//   customer pays fixed
//     -> dealer RECEIVED fixed
//     -> dealer is long duration
//     -> delta_dv01 > 0
//
//   p            = p(customer paid fixed) = p(dealer received fixed)
//   signed_weight = 2p - 1                (never p)
//   dealer_sign  = +1 RECEIVED, -1 PAID, 0 no call
//
// A sign that renders inverted teaches the reader the wrong thing
// permanently, and it does it while looking completely plausible. Two
// independent inversions were caught during the backend work — one in the core
// convention module, one in a notebook that printed a raw decimal with a "%"
// appended. So the mapping is written once, here, and pinned end to end by
// __tests__/dealerDirection.sign.test.ts against a real trade.
//
// WEIGHT BY 2p-1, NOT p. At p = 0.5 a p-weighted contribution is half a long
// position, not a coin flip. The confidence bands below read |2p-1| for the
// same reason: it is 0 at a coin flip and 1 at certainty.

export const DIRECTION_RECEIVED = 'RECEIVED'
export const DIRECTION_PAID = 'PAID'
export const DIRECTION_ABSTAINED = 'ABSTAINED'

export type DirectionTone = 'received' | 'paid' | 'abstained'
export type ConfidenceBand = 'high' | 'medium' | 'low' | 'none'

/** What each exclusion code means, in words a reader can act on.
 *
 *  An abstention is information, not a blank. A blank cell reads as "no flow"
 *  when it means "we declined", so every excluded unit shows its reason. */
export const EXCLUSION_PHRASE: Record<string, string> = {
  UNORIENTABLE_PKG:
    'no market quote convention orients this package — several mutually ' +
    'inconsistent sign vectors fit the same price',
  UNSUPPORTED_INDEX: 'index has no curve mapping (BASIS / OTHER / Term SOFR)',
  NOT_ECONOMIC_FLOW: 'not economic flow',
  STANDARD_COUPON: 'MAC / IMM standard coupon — off-market by construction, not by negotiation',
  EXERCISE_OR_NOVATION:
    'swaption exercise (prints at the strike) or a novation (dealer-to-dealer)',
  NO_CURVE: 'no curve snapshot inside the session tolerance',
  PRICING_ERROR: 'the unit could not be repriced',
  NO_FIXED_RATE: 'no fixed rate on the print',
  RISK_IMPLAUSIBLE: 'notional or risk carries the spec\'s "value not available" sentinel',
  DEAD_ZONE: 'the deviation sits inside the mid\'s own measurement error',
  NO_CALIBRATION: 'no trailing calibration ends before this day',
  NO_UPFRONT: 'the upfront rule applies but no other-payment amount was reported',
  CAPPED_UPFRONT:
    'capped notional with an upfront — the fee may not have been scaled with the size',
  PKG_NO_PACKAGE_PRICE: 'the package reports no package price to orient against',
  PKG_OPA_MISSING: 'the package reports no per-leg other-payment amounts',
  PKG_TIEOUT_FAIL: 'the leg fees do not reconcile to the reported package price',
  PKG_SIGNS_AMBIGUOUS:
    'several mutually inconsistent leg sign vectors fit the package price inside ' +
    'the same tolerance — the answer would be a solver tie-break, not economics',
  PKG_LEG_AT_MID: 'a leg prints at mid, so its sign is not resolvable',
}

export type DirectionRowFields = {
  dd_dealer_direction?: string | null
  dd_dealer_sign?: number | string | null
  dd_p?: number | string | null
  dd_signed_weight?: number | string | null
  dd_rule?: string | null
  dd_deviation_bps?: number | string | null
  dd_tau_bps?: number | string | null
  dd_in_dead_zone?: boolean | null
  dd_exclusion_reason?: string | null
  dd_exclusion_detail?: string | null
  dd_venue_class?: string | null
  dd_series?: string | null
  dd_special_tenor_type?: string | null
  dd_total_delta_dv01?: number | string | null
  dd_total_dv01_if_received?: number | string | null
  dd_visibility_timestamp?: string | Date | null
  dd_visibility_lag_seconds?: number | string | null
  dd_visibility_source?: string | null
  dd_curve_name?: string | null
  dd_curve_timestamp?: string | Date | null
  dd_snapshot_lag_seconds?: number | string | null
  dd_snapshot_policy?: string | null
  dd_notional_imputed?: boolean | null
  dd_code_vintage?: string | null
  dd_tape_generation?: string | null
}

export type DirectionView = {
  /** Present at all? (false when the batch has not covered this day yet.) */
  known: boolean
  label: string
  tone: DirectionTone
  band: ConfidenceBand
  /** |2p-1| in [0,1], or null when there is no call. */
  conviction: number | null
  p: number | null
  reason: string | null
  reasonPhrase: string | null
  title: string
}

/** pg hands NUMERIC back as a string; every numeric field goes through here. */
export function num(v: number | string | null | undefined): number | null {
  if (v == null || v === '') return null
  const n = Number(v)
  return Number.isFinite(n) ? n : null
}

/** |2p-1|, banded. 0 at a coin flip, 1 at certainty. */
export function convictionBand(conviction: number | null): ConfidenceBand {
  if (conviction == null) return 'none'
  if (conviction >= 0.6) return 'high'
  if (conviction >= 0.25) return 'medium'
  if (conviction > 0) return 'low'
  return 'none'
}

function fmt(n: number | null, digits = 2): string {
  return n == null ? '—' : n.toFixed(digits)
}

export function directionView(row: DirectionRowFields): DirectionView {
  const raw = row.dd_dealer_direction ?? null
  const reason = row.dd_exclusion_reason ?? null
  const p = num(row.dd_p)
  const weight = num(row.dd_signed_weight)
  const conviction = weight == null ? null : Math.abs(weight)

  // No row in the direction table at all — the batch has not reached this
  // tape day. Distinct from an abstention, and it must say so: "not computed"
  // and "we declined" are different facts and only one of them is about the
  // trade.
  if (raw == null) {
    return {
      known: false,
      label: '—',
      tone: 'abstained',
      band: 'none',
      conviction: null,
      p: null,
      reason: null,
      reasonPhrase: null,
      title: 'dealer direction not computed for this day yet',
    }
  }

  if (raw === DIRECTION_ABSTAINED || reason) {
    const phrase = reason ? (EXCLUSION_PHRASE[reason] ?? reason) : 'no call'
    const detail = row.dd_exclusion_detail
    return {
      known: true,
      label: 'n/a',
      tone: 'abstained',
      band: 'none',
      conviction: null,
      p: null,
      reason,
      reasonPhrase: phrase,
      title:
        `No direction inferred.\n${reason ?? 'ABSTAINED'}: ${phrase}` +
        (detail ? `\ndetail: ${detail}` : '') +
        '\n\nThis is a declined call, not an absence of flow.',
    }
  }

  const tone: DirectionTone = raw === DIRECTION_RECEIVED ? 'received' : 'paid'
  const band = convictionBand(conviction)
  const dev = num(row.dd_deviation_bps)
  const tau = num(row.dd_tau_bps)
  const lagMin = (() => {
    const s = num(row.dd_visibility_lag_seconds)
    return s == null ? null : s / 60
  })()

  const title = [
    raw === DIRECTION_RECEIVED
      ? 'Dealer RECEIVED fixed — customer paid fixed, dealer is long duration.'
      : 'Dealer PAID fixed — customer received fixed, dealer is short duration.',
    `p(customer paid fixed) = ${fmt(p, 3)}   weight 2p-1 = ${fmt(weight, 3)}`,
    `rule ${row.dd_rule ?? '—'}   deviation ${fmt(dev, 3)} bp   tau ${fmt(tau, 3)} bp`,
    row.dd_in_dead_zone
      ? 'IN THE DEAD ZONE: the deviation is inside the mid\'s own measurement error.'
      : null,
    // A meeting-to-meeting swap is repriced against a smooth par curve that
    // has no discrete FOMC steps in it, so the model averages across the very
    // step the trade is expressing. Measured on 2024-07/08, median |deviation|
    // against everything else on the same days: Fed Funds 1.994 bp vs 0.295 bp
    // (6.8x), SOFR 0.697 bp vs 0.174 bp (4.0x) -- and the per-meeting median
    // flips sign by 1-2 bp on both indices TOGETHER, which is what rules out a
    // rate-index routing fault and points at the curve's meeting structure.
    row.dd_special_tenor_type === 'FOMC'
      ? 'FOMC-DATED. Repriced against a curve with no discrete meeting steps, '
        + 'so this deviation is dominated by model error rather than by '
        + 'bid-offer. Treat the direction as unreliable.'
      : null,
    row.dd_notional_imputed
      ? 'Notional is CAPPED — the size was not read, so this DV01 is a low reading.'
      : null,
    lagMin == null
      ? null
      : `public ${lagMin.toFixed(0)} min after execution (${row.dd_visibility_source ?? '—'})`,
    row.dd_curve_name
      ? `priced on ${row.dd_curve_name} @ ${row.dd_snapshot_policy ?? '—'}`
      : null,
  ]
    .filter(Boolean)
    .join('\n')

  return {
    known: true,
    label: raw === DIRECTION_RECEIVED ? 'RCVD' : 'PAID',
    tone,
    band,
    conviction,
    p,
    reason: null,
    reasonPhrase: null,
    title,
  }
}

// ===================================================================
// THE DIVERGING PAIR IS SKY / AMBER, AND THAT IS A MEASUREMENT
// ===================================================================
//
// The house pass/fail pair is emerald/rose, and it is the wrong pair for a
// DIRECTION encoding. Run through the palette validator against a dark
// surface:
//
//   emerald #34d399 vs rose #fb7185 -> deuteranopia dE 4.6   FAIL
//   sky     #38bdf8 vs amber #f59e0b -> protan       dE 25.5  PASS
//                                        tritan       dE 27.5  PASS
//
// A red-green viewer cannot tell "dealer received" from "dealer paid" in the
// emerald/rose pair at all. That is not a styling preference; on a chart whose
// entire content is a sign, it is the chart failing to say anything.
//
// So one pair, used everywhere in this feature — the badge here and every mark
// in the ladder panel:
//
//   sky   #38bdf8  dealer RECEIVED fixed, long duration,  delta_dv01 > 0
//   amber #f59e0b  dealer PAID fixed,     short duration, delta_dv01 < 0
//   slate           neutral midpoint / declined
//
// and identity is never colour alone: the badge carries the word.
export const DIRECTION_SKY = '#38bdf8'
export const DIRECTION_AMBER = '#f59e0b'
export const DIRECTION_NEUTRAL = '#334155'

export const DIRECTION_TONES: Record<DirectionTone, string> = {
  received: 'bg-sky-900/40 text-sky-200 ring-1 ring-sky-400/40',
  paid: 'bg-amber-900/40 text-amber-200 ring-1 ring-amber-400/40',
  abstained: 'bg-slate-800/60 text-slate-400 ring-1 ring-slate-600/40',
}

/** Conviction is length, not another colour — the hue is already spent on the
 *  sign, and stacking two meanings on one channel loses both. */
export const BAND_WIDTH: Record<ConfidenceBand, string> = {
  high: 'w-full',
  medium: 'w-2/3',
  low: 'w-1/3',
  none: 'w-0',
}
