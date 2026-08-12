// ABOUTME: The rules that decide what the intraday-prints chart SHOWS, pinned
// where they are pure.
//
// Three of these are inversion guards rather than unit tests. A rendered sign
// inversion teaches the reader the wrong thing permanently and it does it while
// looking completely plausible — two were caught during the backend work — so
// the convention is asserted end to end here rather than trusted to a comment.
import { describe, expect, it } from '@jest/globals'
import {
  DIRECTION_AMBER,
  DIRECTION_NEUTRAL,
  DIRECTION_SKY,
} from '../../../utils/dealerDirection'
import {
  buildMidSeries,
  clampToDomain,
  directionOf,
  etDateOf,
  etMidnightFor,
  fmtEtClock,
  GAP_MINUTES,
  hourlyTicks,
  LEGEND_DV01,
  legendSizeRefs,
  MARKER_OPACITY,
  MARKER_R_MAX,
  MARKER_R_MIN,
  markerOpacity,
  markerRadius,
  midPct,
  MIN_MID_POINTS,
  MIN_Y_SPAN_PCT,
  plotsAboveMid,
  type PrintRow,
  sizeNotRead,
  stemColor,
  tDomain,
  yDomain,
} from '../IntradayPrintsPanel.helpers'

let seq = 0
function mk(over: Partial<PrintRow> = {}): PrintRow {
  seq += 1
  const traded = over.traded_pct ?? 4.03536
  const dev = over.deviation_bps ?? -1.04
  return {
    package_id: `pkg-${seq}`,
    trade_id: `tr-${seq}`,
    execution_timestamp: '2026-06-18T14:03:00.000Z',
    visibility_timestamp: '2026-06-18T14:04:00.000Z',
    visibility_lag_seconds: 60,
    dealer_direction: 'RECEIVED',
    dealer_sign: 1,
    p: 0.62,
    signed_weight: 0.24,
    deviation_bps: dev,
    tau_bps: 0.35,
    mid_bias_bps: 0.004,
    in_dead_zone: true,
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
    effective_date: '2026-06-22',
    expiration_date: '2036-06-22',
    tenor_years: 10.0027,
    tenor_display: '10Y',
    forward_start_years: 0,
    forward_label: null,
    is_off_market: false,
    traded_pct: traded,
    mid_pct: midPct(traded, dev),
    curve_name: 'USD-SOFR-1D',
    curve_timestamp: '2026-06-18T14:03:00.000Z',
    snapshot_lag_seconds: 0,
    snapshot_policy: 'STRICT_1MIN_IN_SESSION',
    tape_generation: 'v3',
    code_vintage: 'abc123',
    ...over,
  }
}

const at = (iso: string, over: Partial<PrintRow> = {}) =>
  mk({ execution_timestamp: iso, ...over })

// ---------------------------------------------------------------------------

describe('the mid is the exact inverse of the deviation', () => {
  it('reproduces the measured triples to 1e-9', () => {
    // quote_weights('OUTRIGHT', 1, RULE_RATE) == (1.0,) and structure_price is
    // percent-in / bp-out, so this is an identity, not an approximation.
    const triples: [number, number, number][] = [
      [4.03536, -1.04, 4.04576],
      [4.0288, -0.142, 4.03022],
      [4.0527, 0.225, 4.05045],
    ]
    for (const [traded, dev, mid] of triples) {
      expect(midPct(traded, dev)).toBeCloseTo(mid, 9)
      expect(traded - midPct(traded, dev)).toBeCloseTo(dev / 100, 9)
    }
  })
})

describe('the direction invariant', () => {
  it('is the server call, NOT sign(deviation)', () => {
    // The classifier's call is sign(deviation - mid_bias). Measured rows exist
    // with dealer_direction='PAID' at deviation +0.0100 while b0 = +0.013, so a
    // naive `dev > 0 => sky` implementation inverts exactly these — and looks
    // completely plausible doing it.
    const near = mk({
      dealer_direction: 'PAID',
      deviation_bps: 0.01,
      mid_bias_bps: 0.013,
    })
    const style = directionOf(near)
    expect(style.color).toBe(DIRECTION_AMBER)
    expect(style.tone).toBe('paid')
    expect(style.shape).toBe('down')
    expect(style.label).toMatch(/dealer PAID fixed/)

    // and because |b0| <= 0.015bp, that same print still sits a hair ABOVE its
    // own mid. That is the convention working, not an inversion bug.
    expect(plotsAboveMid(near)).toBe(true)
  })

  it('paints RECEIVED sky/▲ and PAID amber/▼, and says the word', () => {
    const rcvd = directionOf(mk({ dealer_direction: 'RECEIVED' }))
    expect(rcvd.color).toBe(DIRECTION_SKY)
    expect(rcvd.shape).toBe('up')
    expect(rcvd.label).toMatch(/long duration/)
    const paid = directionOf(mk({ dealer_direction: 'PAID' }))
    expect(paid.color).toBe(DIRECTION_AMBER)
    expect(paid.shape).toBe('down')
    expect(paid.label).toMatch(/short duration/)
    // never colour alone: hue and shape and word all differ
    expect(rcvd.color).not.toBe(paid.color)
    expect(rcvd.shape).not.toBe(paid.shape)
    expect(rcvd.label).not.toBe(paid.label)
  })

  it('gives a package leg NO direction, whatever the unit says', () => {
    // In a steepener the dealer receives one leg and pays the other, so
    // painting a leg with the unit's direction is a guaranteed inversion.
    for (const kind of ['CURVE', 'FLY', 'PKG'] as const) {
      const s = directionOf(mk({ kind, dealer_direction: 'RECEIVED' }))
      expect(s.color).toBe(DIRECTION_NEUTRAL)
      expect(s.shape).toBe('ring')
      expect(s.label).toMatch(/direction not resolvable per leg/)
    }
  })

  it('a RECEIVED print plots above its own mid and a PAID print below', () => {
    // THE RENDERED-INVERSION GUARD: customer pays fixed ABOVE mid => dealer
    // received fixed => dealer long duration.
    const rcvd = mk({ dealer_direction: 'RECEIVED', traded_pct: 4.05, deviation_bps: 1.2 })
    const paid = mk({ dealer_direction: 'PAID', traded_pct: 4.05, deviation_bps: -1.2 })
    expect(plotsAboveMid(rcvd)).toBe(true)
    expect(plotsAboveMid(paid)).toBe(false)
    expect(plotsAboveMid(mk({ mid_pct: null }))).toBeNull()
  })

  it('colours a deviation STEM by the same call as the mark above it', () => {
    // THE STACKED-INVERSION GUARD. The deviation strip sits directly under the
    // price chart, so a stem coloured by sign(deviation) paints the SAME print
    // the opposite colour from its own mark whenever the print falls between 0
    // and b0 — and the producer puts prints there on purpose:
    //
    //   backfill_dealer_direction.py:961
    //     # `dealer_side` on the BIAS-CORRECTED deviation: p is a function of
    //     # (dev - b0), so the raw deviation disagrees with the weight on any
    //     # print between 0 and b0 and the ladder refuses that pair.
    //     side = conv.dealer_side(dev - fit.b0)
    //
    // `dev >= 0 ? SKY : AMBER` fails on the first case below and on the third.
    const nearMidPaid = mk({
      dealer_direction: 'PAID',
      deviation_bps: 0.01, // positive...
      mid_bias_bps: 0.013, // ...but under b0, so the call is PAID
    })
    expect(stemColor(nearMidPaid)).toBe(DIRECTION_AMBER)

    const nearMidReceived = mk({
      dealer_direction: 'RECEIVED',
      deviation_bps: -0.008, // negative...
      mid_bias_bps: -0.015, // ...but over b0, so the call is RECEIVED
    })
    expect(stemColor(nearMidReceived)).toBe(DIRECTION_SKY)

    // and a print with NO call never gets a direction hue, whatever its
    // deviation happens to be.
    expect(stemColor(mk({ dealer_direction: 'ABSTAINED', deviation_bps: 1.2 }))).toBe(
      DIRECTION_NEUTRAL,
    )
    expect(stemColor(mk({ dealer_direction: 'ABSTAINED', deviation_bps: -1.2 }))).toBe(
      DIRECTION_NEUTRAL,
    )

    // the ordinary cases still read the ordinary way
    expect(stemColor(mk({ dealer_direction: 'RECEIVED', deviation_bps: 1.2 }))).toBe(DIRECTION_SKY)
    expect(stemColor(mk({ dealer_direction: 'PAID', deviation_bps: -1.2 }))).toBe(DIRECTION_AMBER)
  })

  it('renders an abstention neutral rather than blank', () => {
    const s = directionOf(mk({ dealer_direction: 'ABSTAINED' }))
    expect(s.color).toBe(DIRECTION_NEUTRAL)
    expect(s.shape).toBe('circle')
    expect(s.label).toBe('no call')
  })
})

describe('the mid line breaks where the data does', () => {
  it('joins a 5-min gap and breaks a 23-min one', () => {
    // Measured gaps on the reference day/tenor: p50 5.0 min, p90 23.0 min,
    // max 177.8 min. GAP_MINUTES = 20 keeps the session joined and always
    // breaks the overnight hole.
    expect(GAP_MINUTES).toBe(20)
    const joined = buildMidSeries([
      at('2026-06-18T14:00:00Z'),
      at('2026-06-18T14:05:00Z'),
    ])
    expect(joined).toHaveLength(2)
    expect(joined.every((p) => p.mid != null)).toBe(true)

    const broken = buildMidSeries([
      at('2026-06-18T14:00:00Z'),
      at('2026-06-18T14:23:00Z'),
    ])
    expect(broken).toHaveLength(3)
    expect(broken[1]!.mid).toBeNull()
    expect(broken[1]!.t).toBeGreaterThan(broken[0]!.t)
    expect(broken[1]!.t).toBeLessThan(broken[2]!.t)
  })

  it('always breaks the 177.8-minute overnight hole', () => {
    const s = buildMidSeries([
      at('2026-06-18T00:10:00Z'),
      at('2026-06-18T03:07:48Z'), // +177.8 min
      at('2026-06-18T03:12:48Z'), // +5 min
    ])
    expect(s.map((p) => p.mid == null)).toEqual([false, true, false, false])
  })

  it('sorts into execution order before measuring the gaps', () => {
    const s = buildMidSeries([at('2026-06-18T14:30:00Z'), at('2026-06-18T14:00:00Z')])
    expect(s).toHaveLength(3) // 30 min apart -> one spacer
    expect(s[0]!.t).toBeLessThan(s[2]!.t)
  })

  it('never emits a mid for a row that has none', () => {
    // Package legs and off-market prints arrive with mid_pct null by SQL
    // construction; this must not paper over that.
    const s = buildMidSeries([
      mk({ kind: 'CURVE', mid_pct: null }),
      mk({ is_off_market: true, mid_pct: null }),
      mk({ is_off_market: true, mid_pct: 4.04 }),
    ])
    expect(s).toHaveLength(0)
  })

  it('has a floor below which no line is drawn at all', () => {
    expect(MIN_MID_POINTS).toBe(12)
  })
})

describe('the y-domain', () => {
  it('ignores off-market rows entirely', () => {
    // Measured: 11 off-market prints (8.4% of rows) stretch the traded band
    // from 5.9bp to 182bp — a 31x stretch. A muted-but-plotted mark still owns
    // the domain, which is why muting is not the fix.
    const clean = [
      mk({ traded_pct: 4.0, deviation_bps: 0 }),
      mk({ traded_pct: 4.059, deviation_bps: 0 }),
    ]
    const dirty = [
      ...clean,
      mk({ traded_pct: 2.3825, deviation_bps: 0, mid_pct: null, is_off_market: true }),
      mk({ traded_pct: 4.206, deviation_bps: 0, mid_pct: null, is_off_market: true }),
    ]
    const a = yDomain(clean)!
    const b = yDomain(dirty)!
    expect(b).toEqual(a)
    // ~5.9bp wide plus 8% padding, not 182bp
    expect((a[1] - a[0]) * 100).toBeLessThan(8)
    expect((a[1] - a[0]) * 100).toBeGreaterThan(6)
  })

  it('ignores forward-starting rows beyond the active ceiling', () => {
    const rows = [
      mk({ traded_pct: 4.0, deviation_bps: 0 }),
      mk({ traded_pct: 4.059, deviation_bps: 0 }),
      // a 10y10y at 4.6689 — 66bp away
      mk({ traded_pct: 4.6689, deviation_bps: 0, forward_start_years: 10 }),
    ]
    const tight = yDomain(rows)!
    expect(tight[1]).toBeLessThan(4.07)
    // ...until the ceiling is deliberately raised, when they ARE the view
    const wide = yDomain(rows, 12)!
    expect(wide[1]).toBeGreaterThan(4.6)
  })

  it('floors the span at 1bp so a quiet tenor is not magnified into noise', () => {
    const flat = [mk({ traded_pct: 4.0, deviation_bps: 0 }), mk({ traded_pct: 4.0, deviation_bps: 0 })]
    const d = yDomain(flat)!
    expect(d[1] - d[0]).toBeGreaterThanOrEqual(MIN_Y_SPAN_PCT)
    expect(yDomain([])).toBeNull()
  })

  it('pins an off-domain value to the edge and says which one', () => {
    const d: [number, number] = [4.0, 4.06]
    expect(clampToDomain(4.03, d)).toEqual({ value: 4.03, pinned: null })
    expect(clampToDomain(2.38, d)).toEqual({ value: 4.0, pinned: 'bottom' })
    expect(clampToDomain(4.21, d)).toEqual({ value: 4.06, pinned: 'top' })
    expect(clampToDomain(4.03, null)).toEqual({ value: 4.03, pinned: null })
  })

  it('takes the time domain across EVERY series, not just the marks', () => {
    // recharts computes its domain from chart-level data only, so a per-series
    // domain would silently crop.
    const rows = [at('2026-06-18T14:00:00Z')]
    const mid = [{ t: Date.parse('2026-06-18T20:00:00Z'), mid: 4.0 }]
    expect(tDomain(rows, mid)).toEqual([
      Date.parse('2026-06-18T14:00:00Z'),
      Date.parse('2026-06-18T20:00:00Z'),
    ])
    expect(tDomain([], [])).toBeNull()
  })
})

describe('the ET clock', () => {
  it('finds ET midnight by bisection, not by a hardcoded offset', () => {
    // as_of_date is the UTC execution date, so the ET calendar date changes
    // mid-chart. The boundary moves with DST (19:00 EST / 20:00 EDT), which is
    // why nothing here is a constant.
    const summer = etMidnightFor([
      at('2026-06-18T02:00:00Z'), // 22:00 ET Jun 17 (EDT, UTC-4)
      at('2026-06-18T14:00:00Z'), // 10:00 ET Jun 18
    ])
    expect(summer).toBe(Date.parse('2026-06-18T04:00:00Z'))

    const winter = etMidnightFor([
      at('2026-01-15T02:00:00Z'), // 21:00 ET Jan 14 (EST, UTC-5)
      at('2026-01-15T14:00:00Z'),
    ])
    expect(winter).toBe(Date.parse('2026-01-15T05:00:00Z'))
  })

  it('returns null when the window does not cross a boundary', () => {
    expect(etMidnightFor([at('2026-06-18T14:00:00Z'), at('2026-06-18T15:00:00Z')])).toBeNull()
    expect(etMidnightFor([at('2026-06-18T14:00:00Z')])).toBeNull()
  })

  it('formats on the New York clock, 24-hour', () => {
    expect(fmtEtClock(Date.parse('2026-06-18T14:03:00Z'))).toBe('10:03')
    expect(fmtEtClock(Date.parse('2026-06-18T04:00:00Z'))).toBe('00:00')
    expect(etDateOf(Date.parse('2026-06-18T02:00:00Z'))).toBe('2026-06-17')
  })

  it('puts ticks on the hour and stops before running away', () => {
    const t0 = Date.parse('2026-06-18T14:00:00Z')
    const ticks = hourlyTicks([t0, t0 + 3 * 3_600_000])
    expect(ticks).toEqual([t0, t0 + 3_600_000, t0 + 2 * 3_600_000, t0 + 3 * 3_600_000])
    expect(hourlyTicks(null)).toEqual([])
  })
})

describe('the size encoding', () => {
  it('is monotone, clamped to [3.5, 13], and never NaN', () => {
    expect(markerRadius(0)).toBe(MARKER_R_MIN)
    expect(markerRadius(null)).toBe(MARKER_R_MIN)
    expect(markerRadius(undefined)).toBe(MARKER_R_MIN)
    expect(markerRadius(Number.NaN)).toBe(MARKER_R_MIN)
    expect(markerRadius(1e12)).toBe(MARKER_R_MAX)
    const xs = [0, 1_000, 5_000, 25_000, 100_000, 500_000]
    const rs = xs.map(markerRadius)
    for (let i = 1; i < rs.length; i += 1) expect(rs[i]!).toBeGreaterThanOrEqual(rs[i - 1]!)
    for (const r of rs) {
      expect(Number.isFinite(r)).toBe(true)
      expect(r).toBeGreaterThanOrEqual(MARKER_R_MIN)
      expect(r).toBeLessThanOrEqual(MARKER_R_MAX)
    }
    // sqrt-AREA, so equal DV01 is equal ink: 4x the risk is 2x the radius.
    expect(markerRadius(100_000)).toBeCloseTo(2 * markerRadius(25_000), 9)
  })

  it('the legend renders its key from markerRadius itself', () => {
    // So the key cannot drift from the marks it is a key for.
    const refs = legendSizeRefs()
    expect(refs.map((r) => r.dv01)).toEqual([...LEGEND_DV01])
    for (const r of refs) expect(r.r).toBe(markerRadius(r.dv01))
  })

  it('marks a print whose size was not read, by any of the three routes', () => {
    expect(sizeNotRead(mk())).toBe(false)
    expect(sizeNotRead(mk({ is_capped: true }))).toBe(true)
    expect(sizeNotRead(mk({ is_notional_capped: true }))).toBe(true)
    expect(sizeNotRead(mk({ notional_imputed: true }))).toBe(true)
  })
})

describe('conviction is not drawn as opacity, and nothing is dropped for it', () => {
  it('renders 92% dead-zone rows at a constant opacity', () => {
    // Measured 111 of 120 = 92.5% on the reference day. in_dead_zone is
    // REPORTING-ONLY — nothing in the aggregation depends on it — so fading by
    // conviction would fade nearly every mark to illegibility while removing no
    // error.
    const rows = Array.from({ length: 100 }, (_, i) => mk({ in_dead_zone: i < 92 }))
    const opacities = new Set(rows.map((r) => markerOpacity(r)))
    expect(opacities.size).toBe(1)
    expect([...opacities][0]).toBe(MARKER_OPACITY)
  })

  it('renders a null p / signed_weight neutral at full opacity, with no NaN', () => {
    // The schema forbids reading a NULL p as 0.5 or a NULL weight as 0. A PKG
    // overlay row can carry both as NULL.
    const row = mk({ kind: 'PKG', p: null, signed_weight: null, dealer_sign: null })
    const s = directionOf(row)
    expect(s.color).toBe(DIRECTION_NEUTRAL)
    expect(markerOpacity(row)).toBe(MARKER_OPACITY)
    expect(Number.isNaN(markerOpacity(row))).toBe(false)
    expect(Number.isNaN(markerRadius(row.structure_dv01))).toBe(false)
    expect(Number.isNaN(markerRadius(null))).toBe(false)
  })
})
