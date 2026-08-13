// ABOUTME: The sign convention, pinned by known answer at the render seam.
//
// This is the seam where an inversion would be permanent and invisible. Two
// independent sign inversions were caught during the backend work — one in the
// core convention module, one in a notebook that printed a raw decimal with a
// "%" appended — and both produced completely plausible output.
//
// So the tests below are NOT comparative. A global sign flip cancels inside
// every comparative test, which is exactly how a published z-score survived a
// 59-test green suite while being inverted. Each assertion here names a side.
import { describe, expect, it } from '@jest/globals'
import {
  BAND_WIDTH,
  convictionBand,
  DIRECTION_AMBER,
  DIRECTION_SKY,
  DIRECTION_TONES,
  directionView,
  EXCLUSION_PHRASE,
  num,
} from '../dealerDirection'

// ---------------------------------------------------------------------------
// The convention, spelled out once:
//
//   customer pays fixed -> dealer RECEIVED fixed -> dealer long duration
//                       -> delta_dv01 > 0
//   p = p(customer paid fixed);  weight = 2p - 1
// ---------------------------------------------------------------------------

describe('the sign maps to the word, and the word is not reversible', () => {
  it('RECEIVED means the dealer is LONG duration and renders sky', () => {
    const v = directionView({
      dd_dealer_direction: 'RECEIVED',
      dd_dealer_sign: 1,
      dd_p: 0.9,
      dd_signed_weight: 0.8,
      dd_total_delta_dv01: 42_000,
    })
    expect(v.label).toBe('RCVD')
    expect(v.tone).toBe('received')
    expect(DIRECTION_TONES[v.tone]).toContain('sky')
    // The words a reader takes away. Named explicitly so a flip cannot pass.
    expect(v.title).toContain('Dealer RECEIVED fixed')
    expect(v.title).toContain('customer paid fixed')
    expect(v.title).toContain('long duration')
    expect(v.title).not.toContain('short duration')
  })

  it('PAID means the dealer is SHORT duration and renders amber', () => {
    const v = directionView({
      dd_dealer_direction: 'PAID',
      dd_dealer_sign: -1,
      dd_p: 0.1,
      dd_signed_weight: -0.8,
      dd_total_delta_dv01: -42_000,
    })
    expect(v.label).toBe('PAID')
    expect(v.tone).toBe('paid')
    expect(DIRECTION_TONES[v.tone]).toContain('amber')
    expect(v.title).toContain('Dealer PAID fixed')
    expect(v.title).toContain('customer received fixed')
    expect(v.title).toContain('short duration')
    expect(v.title).not.toContain('long duration')
  })

  it('p is p(customer paid fixed), and the tooltip says so verbatim', () => {
    const v = directionView({
      dd_dealer_direction: 'RECEIVED',
      dd_dealer_sign: 1,
      dd_p: 0.875,
      dd_signed_weight: 0.75,
    })
    expect(v.title).toContain('p(customer paid fixed) = 0.875')
    expect(v.title).toContain('weight 2p-1 = 0.750')
  })

  it('the two poles are the CVD-safe pair, not the pass/fail pair', () => {
    // Measured, not chosen: emerald/rose scores deuteranopia dE 4.6 — a
    // red-green viewer cannot separate the two directions at all. sky/amber
    // scores 25.5 protan / 27.5 tritan.
    expect(DIRECTION_SKY).toBe('#38bdf8')
    expect(DIRECTION_AMBER).toBe('#f59e0b')
    expect(DIRECTION_TONES.received).not.toContain('emerald')
    expect(DIRECTION_TONES.paid).not.toContain('rose')
  })
})

describe('conviction is |2p-1|, never p', () => {
  it('a coin flip is worth nothing', () => {
    // At p = 0.5 a p-weighted contribution is HALF A LONG POSITION. The whole
    // reason the ladder aggregates 2p-1 is that this is zero.
    const v = directionView({
      dd_dealer_direction: 'RECEIVED',
      dd_dealer_sign: 1,
      dd_p: 0.5,
      dd_signed_weight: 0.0,
    })
    expect(v.conviction).toBe(0)
    expect(v.band).toBe('none')
    expect(BAND_WIDTH[v.band]).toBe('w-0')
  })

  it('reads the weight, not the probability', () => {
    // If this read `p` instead of `|2p-1|`, p = 0.5 would band as "medium".
    expect(convictionBand(0)).toBe('none')
    expect(convictionBand(0.1)).toBe('low')
    expect(convictionBand(0.25)).toBe('medium')
    expect(convictionBand(0.5)).toBe('medium')
    expect(convictionBand(0.6)).toBe('high')
    expect(convictionBand(1)).toBe('high')
    expect(convictionBand(null)).toBe('none')
  })

  it('is a magnitude, so both sides band the same', () => {
    const long = directionView({
      dd_dealer_direction: 'RECEIVED', dd_dealer_sign: 1,
      dd_p: 0.9, dd_signed_weight: 0.8,
    })
    const short = directionView({
      dd_dealer_direction: 'PAID', dd_dealer_sign: -1,
      dd_p: 0.1, dd_signed_weight: -0.8,
    })
    expect(long.conviction).toBeCloseTo(0.8, 12)
    expect(short.conviction).toBeCloseTo(0.8, 12)
    expect(long.band).toBe(short.band)
  })
})

describe('an abstention says why, and is not a blank', () => {
  it('carries the reason code and a phrase', () => {
    const v = directionView({
      dd_dealer_direction: 'ABSTAINED',
      dd_exclusion_reason: 'UNORIENTABLE_PKG',
    })
    expect(v.label).toBe('n/a')
    expect(v.reason).toBe('UNORIENTABLE_PKG')
    expect(v.reasonPhrase).toContain('no market quote convention orients')
    expect(v.title).toContain('declined call, not an absence of flow')
  })

  it('every reason the backend can emit has a phrase', () => {
    const codes = [
      'UNORIENTABLE_PKG', 'UNSUPPORTED_INDEX', 'NOT_ECONOMIC_FLOW',
      'STANDARD_COUPON', 'EXERCISE_OR_NOVATION', 'NO_CURVE', 'PRICING_ERROR',
      'NO_FIXED_RATE', 'RISK_IMPLAUSIBLE', 'DEAD_ZONE', 'NO_CALIBRATION',
      'NO_UPFRONT', 'CAPPED_UPFRONT', 'PKG_NO_PACKAGE_PRICE', 'PKG_OPA_MISSING',
      'PKG_TIEOUT_FAIL', 'PKG_SIGNS_AMBIGUOUS', 'PKG_LEG_AT_MID',
    ]
    for (const c of codes) {
      expect(EXCLUSION_PHRASE[c]).toBeDefined()
      expect(EXCLUSION_PHRASE[c]!.length).toBeGreaterThan(10)
    }
  })

  it('an unmapped reason still shows the code rather than nothing', () => {
    const v = directionView({
      dd_dealer_direction: 'ABSTAINED',
      dd_exclusion_reason: 'SOMETHING_NEW',
    })
    expect(v.reasonPhrase).toBe('SOMETHING_NEW')
  })

  it('distinguishes "not computed" from "we declined"', () => {
    // A day the batch has not reached is NOT an abstention. Rendering them the
    // same would put "we looked and declined" on a trade nobody has looked at.
    const v = directionView({})
    expect(v.known).toBe(false)
    expect(v.label).toBe('—')
    expect(v.title).toContain('not computed')
    expect(v.reason).toBeNull()
  })
})

describe('flags that change how the number should be read', () => {
  it('says so when the deviation sat inside the mid\'s own error', () => {
    const v = directionView({
      dd_dealer_direction: 'RECEIVED', dd_dealer_sign: 1,
      dd_p: 0.52, dd_signed_weight: 0.04, dd_in_dead_zone: true,
    })
    expect(v.title).toContain('DEAD ZONE')
  })

  it('says the size was not read when the notional is capped', () => {
    const v = directionView({
      dd_dealer_direction: 'PAID', dd_dealer_sign: -1,
      dd_p: 0.2, dd_signed_weight: -0.6, dd_notional_imputed: true,
    })
    expect(v.title).toContain('CAPPED')
    expect(v.title).toContain('low reading')
  })

  it('says an FOMC-dated swap is repriced against a curve with no meeting steps', () => {
    // Measured on 2024-07/08: median |deviation| 1.994 bp on Fed Funds
    // against 0.295 bp for everything else on the same days (6.8x), 0.697 vs
    // 0.174 on SOFR (4.0x), and the per-meeting median flips sign by 1-2 bp
    // on BOTH indices together -- so it is the curve's missing meeting
    // structure, not a rate-index routing fault. They are 28% of the 0-1Y
    // bucket's gross DV01.
    const v = directionView({
      dd_dealer_direction: 'RECEIVED', dd_dealer_sign: 1,
      dd_p: 0.95, dd_signed_weight: 0.9, dd_special_tenor_type: 'FOMC',
    })
    expect(v.title).toContain('FOMC-DATED')
    expect(v.title).toContain('no discrete meeting steps')
    expect(v.title).toContain('unreliable')
    // and an ordinary swap does NOT carry the warning
    const plain = directionView({
      dd_dealer_direction: 'RECEIVED', dd_dealer_sign: 1,
      dd_p: 0.95, dd_signed_weight: 0.9, dd_special_tenor_type: 'STANDARD',
    })
    expect(plain.title).not.toContain('FOMC')
  })

  it('shows the publication lag in minutes', () => {
    const v = directionView({
      dd_dealer_direction: 'RECEIVED', dd_dealer_sign: 1,
      dd_p: 0.9, dd_signed_weight: 0.8,
      dd_visibility_lag_seconds: 3600, dd_visibility_source: 'APPENDIX_C_60MIN',
    })
    expect(v.title).toContain('public 60 min after execution')
  })
})

describe('pg hands NUMERIC back as a string', () => {
  it('coerces, and refuses garbage', () => {
    expect(num('0.875')).toBeCloseTo(0.875, 12)
    expect(num(0.875)).toBeCloseTo(0.875, 12)
    expect(num(null)).toBeNull()
    expect(num('')).toBeNull()
    expect(num('n/a')).toBeNull()
  })

  it('reads a string weight as a number, not as a truthy string', () => {
    const v = directionView({
      dd_dealer_direction: 'RECEIVED', dd_dealer_sign: 1,
      dd_p: '0.9', dd_signed_weight: '0.8',
    })
    expect(v.conviction).toBeCloseTo(0.8, 12)
    expect(v.band).toBe('high')
  })
})

describe('state is the machine value and label is the display text', () => {
  // THE BUG THIS PINS: the grid's data-direction attribute carried `label`,
  // which is abbreviated. 'PAID' is spelled the same both ways and 'RECEIVED'
  // is not, so every consumer of that attribute agreed on paid prints and
  // silently disagreed on received ones. Half-right direction is the exact
  // failure mode this feature exists to prevent.
  it('never lets the abbreviation stand in for the state', () => {
    const rcvd = directionView({ dd_dealer_direction: 'RECEIVED', dd_p: 0.8, dd_signed_weight: 0.6 })
    expect(rcvd.state).toBe('RECEIVED')
    expect(rcvd.label).toBe('RCVD')
    expect(rcvd.state).not.toBe(rcvd.label)
  })

  it('covers all four states, and only those four', () => {
    const paid = directionView({ dd_dealer_direction: 'PAID', dd_p: 0.2, dd_signed_weight: -0.6 })
    const abst = directionView({ dd_dealer_direction: 'ABSTAINED' })
    const excl = directionView({ dd_dealer_direction: 'RECEIVED', dd_exclusion_reason: 'NO_CURVE' })
    const none = directionView({})
    expect(paid.state).toBe('PAID')
    expect(abst.state).toBe('ABSTAINED')
    // an excluded row is a DECLINED call whatever direction the raw field says
    expect(excl.state).toBe('ABSTAINED')
    expect(none.state).toBe('UNKNOWN')
    for (const v of [paid, abst, excl, none]) {
      expect(['RECEIVED', 'PAID', 'ABSTAINED', 'UNKNOWN']).toContain(v.state)
    }
  })
})
