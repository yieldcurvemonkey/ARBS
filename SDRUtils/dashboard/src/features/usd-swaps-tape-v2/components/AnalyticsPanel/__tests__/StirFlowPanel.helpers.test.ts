// ABOUTME: The encoding rules for the STIR dealer-flow chart.
//
// The load-bearing one is the UNIT rule. In arbs_stir_direction_v1 fixed_rate
// is a FRACTION (99.95% of rows) and curve_mid is already PERCENT (99.88%).
// Subtract them raw and every trade sits 3.66 below its mid, which reads as a
// mass sign inversion on a chart whose whole content is a sign. Converted, the
// classifier identity is exact: spread_to_mid_bps == (fixed*100 - mid)*100,
// median |error| 0.0 over 49,653 of 49,653 rows.

import { describe, expect, it } from '@jest/globals'
import {
  DIRECTION_AMBER,
  DIRECTION_SKY,
} from '../../../utils/dealerDirection'
import {
  buildStirMidSeries,
  instrumentDays,
  instrumentLabel,
  MARK_R_MAX,
  MARK_R_MIN,
  markRadius,
  MEETING_LENGTH_MAX_DAYS,
  midAt,
  midPct,
  rateDomain,
  tradedPct,
  type MidPoint,
  num,
  parseTenorQuery,
  spreadDomain,
  STIR_MID_GAP_MINUTES,
  type StirFlowRow,
  type StirInstrument,
  stirMarkStyle,
} from '../StirFlowPanel.helpers'

const row = (over: Partial<StirFlowRow> = {}): StirFlowRow => ({
  unit_key: 'u', trade_id: 't', package_id: null,
  execution_timestamp: '2026-07-29T14:00:00.000Z',
  curve_timestamp: '2026-07-29T14:00:00.000Z',
  dealer_direction: 'PAID', classification_method: 'RATE_VS_MID',
  direction_confidence: 'HIGH', p_flip: 0.1,
  structure_dv01: 50_000, notional: 1e6, dv01: 50_000,
  // curve_mid PERCENT, fixed_rate FRACTION -- see the note above.
  fixed_rate: 0.0425, curve_mid: 4.26, spread_to_mid_bps: -1,
  dealer_charge_bps: null, rate_index_clean: 'FED_FUNDS', trade_type: null,
  is_off_market: false, curve_suspect_trade: false,
  tenor_query: '2026-07-29->2026-09-16', tenor_bucket: null,
  curve_name: 'USD-OIS', code_vintage: 'abc', ...over,
})

describe('the mark encoding matches the sibling panel', () => {
  it('paints RECEIVED sky/up and PAID amber/down, and says the word', () => {
    // Same hue and same shape as the intraday prints panel. Two direction
    // charts on one screen must not disagree about what sky means.
    const r = stirMarkStyle(row({ dealer_direction: 'RECEIVED' }))
    const p = stirMarkStyle(row({ dealer_direction: 'PAID' }))
    expect(r.color).toBe(DIRECTION_SKY)
    expect(r.shape).toBe('up')
    expect(r.label).toBe('RECEIVED')
    expect(r.title).toMatch(/long duration/)
    expect(p.color).toBe(DIRECTION_AMBER)
    expect(p.shape).toBe('down')
    expect(p.title).toMatch(/short duration/)
  })

  it('draws a TICK_RULE trade HOLLOW, and says its distance means nothing', () => {
    // Measured: tick-rule spread signs do not track direction (PAID 1,331
    // positive / 3,914 negative). The direction is still the classifier's
    // call; what is not claimed is that its position is a measurement.
    const t = stirMarkStyle(row({ classification_method: 'TICK_RULE' }))
    expect(t.filled).toBe(false)
    expect(t.title).toMatch(/not from the mid/)
    expect(stirMarkStyle(row({ classification_method: 'RATE_VS_MID' })).filled).toBe(true)
  })

  it('draws an off-market trade as a diamond whatever its direction', () => {
    for (const d of ['RECEIVED', 'PAID'] as const) {
      expect(stirMarkStyle(row({ dealer_direction: d, is_off_market: true })).shape).toBe('diamond')
    }
  })

  it('sizes by structure DV01, clamped, and never NaN', () => {
    expect(markRadius(0)).toBe(MARK_R_MIN)
    expect(markRadius(null)).toBe(MARK_R_MIN)
    expect(markRadius(1e12)).toBe(MARK_R_MAX)
    expect(markRadius('50000')).toBeGreaterThan(MARK_R_MIN)
    expect(Number.isNaN(markRadius('nonsense'))).toBe(false)
  })
})

describe('the two rate columns are in different units, and that is a trap', () => {
  // MEASURED: fixed_rate is a FRACTION on 75,244 of 75,285 rows (99.95%);
  // curve_mid is already PERCENT on 60,879 of 60,950 (99.88%). Subtracting
  // them raw makes every trade sit 3.66 below its mid, which reads as a mass
  // sign inversion and is really a factor of 100.
  it('scales fixed_rate to percent and leaves curve_mid alone', () => {
    const r = row({ fixed_rate: 0.03728, curve_mid: 3.74843 })
    expect(tradedPct(r)).toBeCloseTo(3.728, 10)
    expect(midPct(r)).toBeCloseTo(3.74843, 10)
  })

  it('reproduces the classifier identity exactly', () => {
    // spread_to_mid_bps == (fixed_rate*100 - curve_mid)*100, median |error|
    // 0.0 across 49,653 of 49,653 rows.
    const r = row({ fixed_rate: 0.03728, curve_mid: 3.74843 })
    const implied = (tradedPct(r)! - midPct(r)!) * 100
    expect(implied).toBeCloseTo(-2.043, 3)
  })

  it('handles pg NUMERIC-as-string on both columns', () => {
    const r = row({ fixed_rate: '0.03728', curve_mid: '3.74843' })
    expect(tradedPct(r)).toBeCloseTo(3.728, 10)
    expect(midPct(r)).toBeCloseTo(3.74843, 10)
  })

  it('admits BOTH the mid and the traded rate to the axis', () => {
    // They are the same quantity once converted, and the gap between them is
    // the whole content of the chart. Excluding either clips the marks.
    const mid: MidPoint[] = [{ t: 1, mid: 3.70 }]
    const d = rateDomain([row({ fixed_rate: 0.0380 }), row({ fixed_rate: 0.0360 })], mid)!
    expect(d[0]).toBeLessThan(3.60)
    expect(d[1]).toBeGreaterThan(3.80)
  })

  it('floors a quiet instrument at half a basis point', () => {
    const d = rateDomain([], [{ t: 1, mid: 4.26 }, { t: 2, mid: 4.2601 }])!
    expect(d[1] - d[0]).toBeGreaterThanOrEqual(0.005)
  })

  it('is null when there is nothing to draw, rather than zero', () => {
    expect(rateDomain([], [])).toBeNull()
    expect(rateDomain([], [{ t: 1, mid: null }])).toBeNull()
  })

  it('keeps the deviation axis symmetric so zero is always the centre', () => {
    const d = spreadDomain([row({ spread_to_mid_bps: -5 }), row({ spread_to_mid_bps: 1 })])
    expect(d[0]).toBeCloseTo(-d[1], 10)
    expect(d[1]).toBeGreaterThanOrEqual(5)
  })
})

describe('the mid line is snapshots, and breaks like one', () => {
  it('breaks a gap wider than 30 minutes and joins one inside it', () => {
    const t0 = Date.parse('2026-07-29T14:00:00.000Z')
    const near = buildStirMidSeries([
      { ts: new Date(t0).toISOString(), mid_pct: 4.26 },
      { ts: new Date(t0 + 25 * 60_000).toISOString(), mid_pct: 4.27 },
    ])
    expect(near.filter((p) => p.mid == null)).toHaveLength(0)
    const far = buildStirMidSeries([
      { ts: new Date(t0).toISOString(), mid_pct: 4.26 },
      { ts: new Date(t0 + 90 * 60_000).toISOString(), mid_pct: 4.27 },
    ])
    expect(far.filter((p) => p.mid == null)).toHaveLength(1)
  })

  it('is MORE generous than the sibling panel, because a gap means something else', () => {
    // There, a gap means the 1-minute curve is missing. Here it only means
    // nobody traded — a weaker claim, so a wider bridge is honest.
    expect(STIR_MID_GAP_MINUTES).toBe(30)
    expect(STIR_MID_GAP_MINUTES).toBeGreaterThan(10)
  })

  it('places a mark at the NEAREST snapshot, and null when there is none', () => {
    const mid: MidPoint[] = [{ t: 1000, mid: 4.26 }, { t: 9000, mid: 4.30 }]
    expect(midAt(1200, mid)).toBe(4.26)
    expect(midAt(8000, mid)).toBe(4.30)
    expect(midAt(5000, [])).toBeNull()
    expect(midAt(5000, [{ t: 1, mid: null }])).toBeNull()
  })
})

describe('the instrument label', () => {
  const inst = (over: Partial<StirInstrument> = {}): StirInstrument => ({
    tenor_query: '2026-07-29->2026-09-16', rate_index_clean: 'FED_FUNDS',
    n: 146, n_received: 5, n_paid: 141, n_off_market: 37, n_with_mid: 105,
    dv01: 4_695_146, first_ts: null, last_ts: null, ...over,
  })

  it('parses the date pair and measures its length', () => {
    expect(parseTenorQuery('2026-07-29->2026-09-16')).toEqual({ eff: '2026-07-29', mat: '2026-09-16' })
    expect(parseTenorQuery('nope')).toBeNull()
    expect(instrumentDays('2026-07-29->2026-09-16')).toBe(49)
  })

  it('calls a short structure meeting-LENGTH, never a meeting NAME', () => {
    // Naming the meeting from a date needs the FOMC calendar, and a wrong name
    // mislabels the instrument. Length is derivable from the dates alone.
    const l = instrumentLabel(inst())
    expect(l).toMatch(/meeting-length/)
    expect(l).not.toMatch(/sep|jul/i)
    expect(l).toMatch(/2026-07-29 → 2026-09-16/)
    expect(l).toMatch(/FED_FUNDS/)
    expect(l).toMatch(/146 trades/)
  })

  it('calls a long date pair by its year length instead', () => {
    const l = instrumentLabel(inst({ tenor_query: '2026-09-16->2028-09-16' }))
    expect(l).toMatch(/2\.0y/)
    expect(l).not.toMatch(/meeting-length/)
    expect(instrumentDays('2026-09-16->2028-09-16')).toBeGreaterThan(MEETING_LENGTH_MAX_DAYS)
  })
})

describe('num survives what pg actually returns', () => {
  it('parses NUMERIC-as-string and refuses junk', () => {
    expect(num('0.0426')).toBeCloseTo(0.0426, 10)
    expect(num(null)).toBeNull()
    expect(num('')).toBeNull()
    expect(num('nonsense')).toBeNull()
  })
})
