// ABOUTME: The continuous mid — which object draws the line, where it breaks,
// and how far each mark sits from it.
//
// THE FAILURE THIS FILE EXISTS TO PREVENT: a modelled curve and a polyline
// through eight prints are different claims about the market, and they render
// as the same shape unless something forces them apart. The chart now has a
// real 1-minute par grid for most of its cells and no grid at all for Fed Funds
// 7Y/20Y/30Y, so BOTH shapes are live at once and the difference has to be
// carried in the data, not in a comment.
import { describe, expect, it } from '@jest/globals'
import {
  buildGridMidSeries,
  followFocused,
  soleTenorOf,
  tapeDayFor,
  chooseMidSeries,
  FWD_MAX_DEFAULT,
  type MidGrid,
  type MidGridPoint,
  MID_GRID_GAP_MINUTES,
  midGridResidual,
  midPct,
  MIN_MID_POINTS,
  type PrintRow,
  yDomain,
} from '../IntradayPrintsPanel.helpers'

let seq = 0
function mk(over: Partial<PrintRow> = {}): PrintRow {
  seq += 1
  const traded = over.traded_pct ?? 4.28
  const dev = over.deviation_bps ?? 0
  return {
    package_id: `pkg-${seq}`,
    trade_id: `tr-${seq}`,
    execution_timestamp: '2026-08-07T13:00:00.000Z',
    visibility_timestamp: '2026-08-07T13:01:00.000Z',
    visibility_lag_seconds: 60,
    dealer_direction: 'RECEIVED',
    dealer_sign: 1,
    p: 0.62,
    signed_weight: 0.24,
    deviation_bps: dev,
    tau_bps: 0.35,
    mid_bias_bps: 0.004,
    in_dead_zone: false,
    kind: 'OUTRIGHT',
    n_legs: 1,
    rule: 'RATE_VS_MID',
    special_tenor_type: 'STANDARD',
    rate_index: 'SOFR',
    venue_class: 'D2C',
    is_block: false,
    is_capped: false,
    notional_imputed: false,
    structure_dv01: 42_000,
    notional: 50_000_000,
    is_notional_capped: false,
    effective_date: '2026-08-11',
    expiration_date: '2036-08-11',
    tenor_years: 10.0027,
    tenor_display: '10Y',
    forward_start_years: 0,
    forward_label: null,
    is_off_market: false,
    traded_pct: traded,
    mid_pct: midPct(traded, dev),
    curve_name: 'USD-SOFR-1D',
    curve_timestamp: '2026-08-07T13:00:00.000Z',
    snapshot_lag_seconds: 0,
    snapshot_policy: 'STRICT_1MIN_IN_SESSION',
    tape_generation: 'v3',
    code_vintage: 'abc123',
    ...over,
  }
}

const gp = (ts: string, mid: number): MidGridPoint => ({ ts, mid_pct: mid })

/** n consecutive 1-minute grid points from a base instant. */
function gridRun(baseIso: string, n: number): MidGridPoint[] {
  const t0 = new Date(baseIso).getTime()
  return Array.from({ length: n }, (_, i) =>
    gp(new Date(t0 + i * 60_000).toISOString(), 4.27 + i * 0.0001),
  )
}

const gridOf = (points: MidGridPoint[], over: Partial<MidGrid> = {}): MidGrid => ({
  available: true,
  points,
  curve_name: 'USD-SOFR-1D',
  snapshot_policy: 'STRICT_1MIN_IN_SESSION',
  window: ['2026-08-07T12:45:00.000Z', '2026-08-07T21:15:00.000Z'],
  ...over,
})

// ---------------------------------------------------------------------------

describe('buildGridMidSeries breaks the line only at a real absence', () => {
  it('never breaks across the measured intra-session gaps (1-5 min)', () => {
    // MEASURED, SOFR 10Y over 7 days spanning the window: intra-day
    // consecutive gaps are 1 min 8,293x, 2 min 170x, 3 min 17x, 4 min once,
    // 5 min once — and the count of intra-day gaps over 5 minutes is ZERO on
    // every one of the seven days. A break inside a live session would be the
    // chart inventing a hole.
    const t0 = new Date('2026-08-07T13:00:00.000Z').getTime()
    for (const gapMin of [1, 2, 3, 4, 5]) {
      const out = buildGridMidSeries([
        gp(new Date(t0).toISOString(), 4.27),
        gp(new Date(t0 + gapMin * 60_000).toISOString(), 4.271),
      ])
      expect(out.filter((p) => p.mid == null)).toHaveLength(0)
    }
  })

  it('always breaks the overnight hole', () => {
    // 23:00-00:59 ET carries no curve at all — Citi's publication gap — so the
    // narrowest genuine hole is ~2 hours.
    const t0 = new Date('2026-08-07T03:00:00.000Z').getTime()
    const out = buildGridMidSeries([
      gp(new Date(t0).toISOString(), 4.27),
      gp(new Date(t0 + 120 * 60_000).toISOString(), 4.28),
    ])
    const nulls = out.filter((p) => p.mid == null)
    expect(nulls).toHaveLength(1)
    // and the spacer sits IN the silence, not attached to either side
    expect(nulls[0]!.t).toBeGreaterThan(t0)
    expect(nulls[0]!.t).toBeLessThan(t0 + 120 * 60_000)
  })

  it('puts the threshold two orders of magnitude clear of both sides', () => {
    expect(MID_GRID_GAP_MINUTES).toBe(10)
    expect(MID_GRID_GAP_MINUTES).toBeGreaterThan(5) // widest measured intra-day gap
    expect(MID_GRID_GAP_MINUTES).toBeLessThan(120) // narrowest overnight hole
  })

  it('sorts by time and drops a non-finite mid rather than plotting it', () => {
    const out = buildGridMidSeries([
      gp('2026-08-07T13:02:00.000Z', 4.272),
      gp('2026-08-07T13:00:00.000Z', 4.27),
      gp('2026-08-07T13:01:00.000Z', Number.NaN),
    ])
    expect(out.map((p) => p.mid)).toEqual([4.27, 4.272])
  })
})

describe('chooseMidSeries says which object the line is', () => {
  const rows = Array.from({ length: 30 }, (_, i) =>
    mk({ execution_timestamp: new Date(Date.UTC(2026, 7, 7, 13, i)).toISOString() }),
  )

  it('prefers the grid — a curve beats a join-the-dots', () => {
    const { source, points } = chooseMidSeries(rows, gridOf(gridRun('2026-08-07T13:00:00.000Z', 600)))
    expect(source).toBe('grid')
    expect(points).toHaveLength(600)
  })

  it('falls back to the reconstruction when the tenor has no grid at all', () => {
    // Fed Funds 7Y/20Y/30Y. MEASURED: the grid carries 12 FF tenors against
    // SOFR's 21. Falling back is correct; falling back SILENTLY is not, which
    // is why the source is RETURNED rather than inferred from a point count.
    const { source, points } = chooseMidSeries(
      rows,
      gridOf([], { available: false }),
    )
    expect(source).toBe('reconstructed')
    expect(points.filter((p) => p.mid != null).length).toBeGreaterThanOrEqual(MIN_MID_POINTS)
  })

  it('falls back when the grid exists but this window is empty', () => {
    expect(chooseMidSeries(rows, gridOf([])).source).toBe('reconstructed')
  })

  it('a thin grid does not beat a usable reconstruction', () => {
    expect(chooseMidSeries(rows, gridOf(gridRun('2026-08-07T13:00:00.000Z', 5))).source).toBe(
      'reconstructed',
    )
  })

  it('refuses BOTH below the floor rather than drawing a level through noise', () => {
    const few = rows.slice(0, 4)
    expect(chooseMidSeries(few, gridOf(gridRun('2026-08-07T13:00:00.000Z', 3))).source).toBe('none')
    expect(chooseMidSeries(few, null).source).toBe('none')
    expect(chooseMidSeries([], undefined).source).toBe('none')
  })
})

describe('midGridResidual measures mark-against-line, matched on the minute', () => {
  it('is zero when the print IS the grid point', () => {
    // A spot STANDARD swap and the grid point are the same instrument priced
    // by the same pricer against the same curve. MEASURED median residual over
    // 3,206 prints: exactly 0.000000 bp.
    const r = mk({ traded_pct: 4.28, deviation_bps: 1.0, curve_timestamp: '2026-08-07T13:00:37.000Z' })
    const out = midGridResidual([r], [gp('2026-08-07T13:00:00.000Z', r.mid_pct!)])
    expect(out).not.toBeNull()
    expect(out!.n).toBe(1)
    expect(out!.medianBps).toBeCloseTo(0, 10)
  })

  it('matches on the CURVE snapshot minute, not the execution minute', () => {
    // The print was repriced against the snapshot at curve_timestamp. Matching
    // on execution_timestamp would compare the mark to a different minute's
    // mid and manufacture a residual that is purely a join error — the chart
    // would then report a disagreement it created itself.
    const r = mk({
      execution_timestamp: '2026-08-07T13:40:00.000Z',
      curve_timestamp: '2026-08-07T13:00:00.000Z',
      traded_pct: 4.28,
      deviation_bps: 1.0,
    })
    const pts = [gp('2026-08-07T13:00:00.000Z', r.mid_pct!), gp('2026-08-07T13:40:00.000Z', 9.99)]
    expect(midGridResidual([r], pts)!.medianBps).toBeCloseTo(0, 10)
  })

  it('is signed, in bp, mark minus line', () => {
    const r = mk({ traded_pct: 4.28, deviation_bps: 0, curve_timestamp: '2026-08-07T13:00:00.000Z' })
    // mid_pct is 4.28 exactly; the grid sits 1bp BELOW, so the mark is +1bp up
    expect(midGridResidual([r], [gp('2026-08-07T13:00:00.000Z', 4.27)])!.medianBps).toBeCloseTo(1, 6)
  })

  it('never lets an off-market print into the diagnostic', () => {
    // Its deviation is a fee, so its "mid" is not a distance from anything.
    const bad = mk({ is_off_market: true, curve_timestamp: '2026-08-07T13:00:00.000Z' })
    expect(midGridResidual([bad], [gp('2026-08-07T13:00:00.000Z', 4.27)])).toBeNull()
  })

  it('is null rather than 0 when nothing matched', () => {
    // "the marks agree with the line" and "no mark could be compared" are
    // different facts, and 0 would state the first while meaning the second.
    const r = mk({ curve_timestamp: '2026-08-07T19:00:00.000Z' })
    expect(midGridResidual([r], [gp('2026-08-07T13:00:00.000Z', 4.27)])).toBeNull()
    expect(midGridResidual([r], [])).toBeNull()
  })

  it('takes p95 and max on the ABSOLUTE residual, median on the signed one', () => {
    // A -5bp mark is a 5bp miss. Reporting max over the signed values would
    // print 0.000 for a day whose worst mark is 5bp off the line.
    const pts: MidGridPoint[] = []
    const rows = [0, 0, 0, 0, 0, 0, 0, 0, 0, -5].map((offBps, i) => {
      const iso = new Date(Date.UTC(2026, 7, 7, 13, i)).toISOString()
      pts.push(gp(iso, 4.28 - offBps / 100))
      return mk({ traded_pct: 4.28, deviation_bps: 0, curve_timestamp: iso })
    })
    const out = midGridResidual(rows, pts)!
    expect(out.n).toBe(10)
    expect(out.medianBps).toBeCloseTo(0, 6)
    expect(out.maxBps).toBeCloseTo(5, 6)
  })
})

describe('the grid is admitted to the y-domain', () => {
  it('extends the domain so the line is not silently clipped', () => {
    // The grid runs 15 minutes past the last mark and the mid can move inside
    // that pad. Clipped, the line goes flat at the frame edge — which reads as
    // the market going quiet rather than as the axis ending.
    const rows = [mk({ traded_pct: 4.28, deviation_bps: 0 })]
    const without = yDomain(rows, FWD_MAX_DEFAULT)
    const withGrid = yDomain(rows, FWD_MAX_DEFAULT, [
      { t: 1, mid: 4.28 },
      { t: 2, mid: 4.36 },
    ])
    expect(withGrid![1]).toBeGreaterThan(without![1])
  })

  it('ignores the null spacers', () => {
    const rows = [mk({ traded_pct: 4.28, deviation_bps: 0 })]
    expect(yDomain(rows, FWD_MAX_DEFAULT, [{ t: 1, mid: null }])).toEqual(
      yDomain(rows, FWD_MAX_DEFAULT, []),
    )
  })

  it('still refuses an off-market print, grid or no grid', () => {
    // The grid changes what draws the LINE. It does not change which marks may
    // own the axis: 11 off-market prints stretch the traded band 31x.
    const rows = [
      mk({ traded_pct: 4.28, deviation_bps: 0 }),
      mk({ traded_pct: 2.38, is_off_market: true }),
    ]
    expect(yDomain(rows, FWD_MAX_DEFAULT, [{ t: 1, mid: 4.28 }])![0]).toBeGreaterThan(4.0)
  })
})

// ===========================================================================
// FOLLOWING THE TAPE'S SELECTION
// ===========================================================================

describe('the tenor comes from the LEGS, because the row has none', () => {
  // MEASURED against the live payload: a tape row exposes package_tenors,
  // legs_count, rate_index_clean and legs_json — and NO tenor_display. Reading
  // it off the row returns undefined for every trade, which is exactly what
  // the first cut did, and the panel then refused to follow anything.
  it('takes the tenor off a single-tenor trade', () => {
    const f = followFocused({
      legs_json: [{ tenor_display: '5Y' }, { tenor_display: '5Y' }],
      rate_index_clean: 'SOFR',
      execution_start: '2026-08-07T14:00:00.000Z',
    })
    expect(f.tenor).toBe('5Y')
    expect(f.rateIndex).toBe('SOFR')
    expect(f.refusals).toHaveLength(0)
  })

  it('refuses a PACKAGE rather than picking one of its legs', () => {
    // The live tape's first row is a 17-leg trade running 4Y/5Y/7Y. Picking
    // the biggest, the first or the longest would put an instrument on screen
    // that the reader did not select.
    const f = followFocused({
      legs_json: [{ tenor_display: '4Y' }, { tenor_display: '7Y' }, { tenor_display: '5Y' }],
      rate_index_clean: 'SOFR',
    })
    expect(f.tenor).toBeNull()
    expect(f.refusals.join(' ')).toMatch(/legs at 4Y, 7Y, 5Y/)
    expect(f.refusals.join(' ')).toMatch(/no single tenor/)
  })

  it('refuses a tenor outside the eight, and names it', () => {
    const f = followFocused({ legs_json: [{ tenor_display: '~10Y' }] })
    expect(f.tenor).toBeNull()
    expect(f.refusals.join(' ')).toMatch(/~10Y is not one of the eight/)
  })

  it('falls back to a leg rate index when the row has none', () => {
    const f = followFocused({ legs_json: [{ tenor_display: '2Y', rate_index_clean: 'FED_FUNDS' }] })
    expect(f.rateIndex).toBe('FED_FUNDS')
  })

  it('soleTenorOf reports every distinct tenor it saw', () => {
    expect(soleTenorOf({ legs_json: [{ tenor_display: '10Y' }, { tenor_display: '10Y' }] }))
      .toEqual({ tenor: '10Y', distinct: ['10Y'] })
    expect(soleTenorOf(null)).toEqual({ tenor: null, distinct: [] })
  })
})

describe('the tape day is not the execution date', () => {
  it('rolls to the NEXT day at 20:00 ET', () => {
    // MEASURED: the tape's as_of_date starts at 20:00 ET the previous evening,
    // so an evening print belongs to the following session. Deriving the day
    // from the calendar date alone would query the wrong session for every
    // evening trade and render an empty chart that reads as "nothing traded".
    // 2026-08-07 23:30 ET = 2026-08-08T03:30Z
    expect(tapeDayFor('2026-08-08T03:30:00.000Z')).toBe('2026-08-08')
    // 2026-08-07 15:00 ET = 2026-08-07T19:00Z -> same day
    expect(tapeDayFor('2026-08-07T19:00:00.000Z')).toBe('2026-08-07')
  })

  it('is null on junk rather than guessing a day', () => {
    expect(tapeDayFor(null)).toBeNull()
    expect(tapeDayFor('not-a-date')).toBeNull()
  })
})
