// ABOUTME: The predicates that decide what a print chart is ABOUT, asserted
// rather than commented.
//
// Two of these are tripwires rather than tests: one fires the moment the tenor
// predicate is relaxed from a strict label to a ±6-month band, the other the
// moment a fee-bearing print can reach a rate axis. Both loosenings produce a
// chart that renders perfectly and means something else.
import { describe, expect, it } from '@jest/globals'
import { BadRequest } from '../route.logic'
import {
  assertNoPackageMid,
  buildDisclosures,
  DEFAULT_SPECIAL_TENOR_TYPES,
  FWD_MAX_DEFAULT,
  latestDateSql,
  median,
  MID_PAD_MINUTES,
  midGridAvailabilitySql,
  midGridSql,
  midWindow,
  type MidGrid,
  parsePrintsParams,
  type PrintsFilters,
  PRINT_TENORS,
  printsCountsSql,
  printsSql,
  type ResolvedPrintsParams,
} from '../prints.logic'

const sp = (q: string) => new URLSearchParams(q)

/**
 * The EXECUTABLE statement — `--` comments stripped.
 *
 * The interpolation check must not be defeatable by prose: the SQL carries
 * comments naming FLY weights and the ±6-month band column, and a substring
 * scan over the raw text would flag those as interpolated user values. Verified
 * against a known input below before it is trusted.
 */
const sqlOnly = (text: string) => text.replace(/--[^\n]*/g, '')

describe('the test helper itself', () => {
  it('strips comments and keeps clauses', () => {
    expect(sqlOnly("SELECT a -- FLY weights (-1,2,-1)\nFROM t WHERE b = $1")).toBe(
      'SELECT a \nFROM t WHERE b = $1',
    )
    // and it does not eat a negative literal that is not a comment
    expect(sqlOnly('SELECT -1')).toBe('SELECT -1')
  })
})
const parse = (q: string) => parsePrintsParams(sp(q))
const resolved = (q: string, date = '2026-06-18'): ResolvedPrintsParams => ({
  ...parse(q),
  date,
})

describe('the tenor predicate is tenor_display, and nothing else', () => {
  it('binds tenor_display and never mentions tenor_label', () => {
    // THE TENOR-WIDENING TRIPWIRE. tenor_label='10Y' spans tenor_years
    // 9.501-10.490 — a ±6-month band — while tenor_display splits it into
    // '10Y' (9.984-10.027) and '~10Y'. Relaxing this predicate silently
    // changes the instrument the chart is about, and the chart still draws.
    const { text, values } = printsSql(resolved('tenor=10Y'))
    expect(text).toContain('l.tenor_display = $')
    expect(text).not.toContain('tenor_label')
    expect(text).toContain('COALESCE(l.forward_start_years, 0) <=')
    expect(values).toContain(0.02)
    expect(FWD_MAX_DEFAULT).toBe(0.02)
  })

  it('band mode is the only path to tenor_label, and it announces itself', () => {
    const p = parse('tenor=10Y&tenorMatch=band')
    expect(p.tenorMatch).toBe('band')
    const { text } = printsSql({ ...p, date: '2026-06-18' })
    expect(text).toContain('l.tenor_label   = $')
    expect(text).not.toContain('l.tenor_display = $')

    // and the counts query still computes the strict subset inside the SAME
    // scan, so admittedByLoosening is exact rather than estimated.
    const counts = printsCountsSql({ ...p, date: '2026-06-18' })
    expect(counts.text).toContain('l.tenor_label   = $')
    expect(counts.text).toMatch(/AS strict_subset/)
    expect(counts.text).toMatch(/tenor_display = \$/)
  })

  it('refuses a tenor outside the eight, and lists them', () => {
    expect(() => parse('tenor=13Y')).toThrow(BadRequest)
    try {
      parse('tenor=13Y')
    } catch (e) {
      for (const t of PRINT_TENORS) expect((e as Error).message).toContain(t)
    }
  })

  it('requires a tenor rather than defaulting to every tenor', () => {
    // Defaulting would be the friendly thing and it would put a 2Y and a 30Y
    // on one rate axis.
    expect(() => parse('')).toThrow(BadRequest)
  })
})

describe('a fee-bearing print never reaches a rate axis', () => {
  it('the default SQL carries every off-market predicate', () => {
    // THE OFF-MARKET TRIPWIRE. rule='RATE_VS_MID' is already a complete fee
    // filter (measured zero leakage), and under NPV_VS_UPFRONT deviation_bps
    // is a DIFFERENT quantity — mean 793.67bp, max 1,362,687bp — so
    // mid = traded - dev/100 would be garbage, not merely wide.
    const { text } = printsSql(resolved('tenor=10Y'))
    expect(text).toContain("u.rule = 'RATE_VS_MID'")
    expect(text).toContain('COALESCE(l.is_off_market, false)      = false')
    expect(text).toContain('COALESCE(l.other_payment_amount, 0)   = 0')
    expect(text).toContain('COALESCE(l.other_payment_ufro,   0)   = 0')
    expect(text).toContain('COALESCE(l.other_payment_uwin,   0)   = 0')
    expect(text).toContain('COALESCE(l.other_payment_pexh,   0)   = 0')
  })

  it('tests the payment columns with = 0, never IS NULL', () => {
    // THE 0-FILLED TRAP: other_payment_ufro/uwin/pexh are 0-filled and never
    // NULL (0 nulls in 96,814), so IS NULL finds nothing at all.
    const { text } = printsSql(resolved('tenor=10Y'))
    expect(text).not.toMatch(/other_payment_\w+\s+IS NULL/)
    expect(text).not.toMatch(/other_payment_\w+\s+IS NOT NULL/)
  })

  it('still refuses a mid to an off-market row when they are shown', () => {
    // includeOffMarket relaxes the WHERE. It must NOT relax the mid: an
    // off-market print's deviation is a fee, not a distance from mid.
    const { text } = printsSql(resolved('tenor=10Y&includeOffMarket=true'))
    expect(text).not.toContain('COALESCE(l.is_off_market, false)      = false')
    expect(text).toMatch(/CASE WHEN u\.kind = 'OUTRIGHT'[\s\S]*?AND NOT \(/)
  })
})

describe('the refusals', () => {
  it('refuses fwdMaxYears past the ceiling, with the 66bp measurement', () => {
    expect(() => parse('tenor=10Y&fwdMaxYears=0.5')).toThrow(BadRequest)
    try {
      parse('tenor=10Y&fwdMaxYears=0.5')
    } catch (e) {
      expect((e as Error).message).toContain('66bp')
      expect((e as Error).message).toContain('4.6689')
    }
    expect(() => parse('tenor=10Y&fwdMaxYears=-1')).toThrow(BadRequest)
    expect(parse('tenor=10Y&fwdMaxYears=0.25').fwdMaxYears).toBe(0.25)
  })

  it('refuses rateIndex=ALL and names the SOFR-FF basis', () => {
    expect(() => parse('tenor=10Y&rateIndex=ALL')).toThrow(BadRequest)
    try {
      parse('tenor=10Y&rateIndex=ALL')
    } catch (e) {
      expect((e as Error).message).toMatch(/SOFR-FF basis/)
      expect((e as Error).message).toMatch(/1\.5-2\.4bp/)
    }
  })

  it('refuses series=LIFECYCLE, because a seasoned coupon is not a market level', () => {
    expect(() => parse('tenor=10Y&series=LIFECYCLE')).toThrow(BadRequest)
    try {
      parse('tenor=10Y&series=LIFECYCLE')
    } catch (e) {
      expect((e as Error).message).toMatch(/SEASONED/)
    }
    expect(parse('tenor=10Y&series=FLOW').series).toBe('FLOW')
    expect(parse('tenor=10Y').series).toBe('FLOW')
  })

  it('reuses the venue-class refusal verbatim — three series, never summed', () => {
    expect(() => parse('tenor=10Y&venueClass=ALL')).toThrow(BadRequest)
    try {
      parse('tenor=10Y&venueClass=ALL')
    } catch (e) {
      expect((e as Error).message).toMatch(/never summed/)
    }
    expect(parse('tenor=10Y').venueClass).toBe('D2C')
    expect(parse('tenor=10Y&venueClass=D2D').venueClass).toBe('D2D')
  })

  it('refuses a date below the sample floor and a malformed one', () => {
    expect(() => parse('tenor=10Y&date=2024-01-01')).toThrow(BadRequest)
    expect(() => parse('tenor=10Y&date=last-tuesday')).toThrow(BadRequest)
    expect(parse('tenor=10Y').date).toBeNull()
  })

  it('refuses an unknown kind', () => {
    expect(() => parse('tenor=10Y&kinds=OUTRIGHT,SPREADOVER')).toThrow(BadRequest)
    expect(parse('tenor=10Y').kinds).toEqual(['OUTRIGHT'])
  })
})

describe('special tenor types are an ALLOW-list, never a deny-list', () => {
  it('leaves FOMC, MAC and INVOICE_SWAP out of the default set', () => {
    expect(DEFAULT_SPECIAL_TENOR_TYPES).toEqual(['STANDARD', 'IMM', 'MATCHED_MATURITY'])
    expect(DEFAULT_SPECIAL_TENOR_TYPES).not.toContain('FOMC')
    expect(DEFAULT_SPECIAL_TENOR_TYPES).not.toContain('MAC')
    expect(DEFAULT_SPECIAL_TENOR_TYPES).not.toContain('INVOICE_SWAP')
    expect(parse('tenor=10Y').specialTenorTypes).toEqual(DEFAULT_SPECIAL_TENOR_TYPES)
  })

  it('400s on a value it does not know', () => {
    // A deny-list refactor — "everything except FOMC/MAC/INVOICE_SWAP" — fails
    // here, which is the point: a type added to the tape later must not leak
    // into the chart unnoticed.
    expect(() => parse('tenor=10Y&specialTenorTypes=STANDARD,SOMETHING_NEW')).toThrow(BadRequest)
  })

  it('binds it with = ANY, so a NULL is excluded rather than admitted', () => {
    const { text } = printsSql(resolved('tenor=10Y'))
    expect(text).toContain('u.special_tenor_type = ANY($')
    // and the exclusion is counted rather than silent
    expect(printsCountsSql(resolved('tenor=10Y')).text).toMatch(
      /special_tenor_type IS NULL[\s\S]*?AS unknown_special_tenor_type/,
    )
  })

  it('admits FOMC when explicitly asked, and the disclosure changes', () => {
    const p = parse('tenor=10Y&specialTenorTypes=STANDARD,FOMC')
    expect(p.specialTenorTypes).toEqual(['STANDARD', 'FOMC'])
  })
})

describe('every user value is bound, never interpolated', () => {
  it('keeps distinctive inputs out of the SQL text and in the params', () => {
    const p = resolved(
      'tenor=20Y&rateIndex=FED_FUNDS&venueClass=D2D&kinds=FLY' +
        '&specialTenorTypes=MATCHED_MATURITY&fwdMaxYears=0.17',
      '2025-03-04',
    )
    for (const q of [printsSql(p), printsCountsSql(p)]) {
      // Distinctive on purpose: 'OUTRIGHT' and 'RATE_VS_MID' DO appear in the
      // text as structural interlocks, and they are not user values.
      for (const v of ['20Y', 'FED_FUNDS', 'D2D', 'FLY', 'MATCHED_MATURITY', '0.17', '2025-03-04']) {
        expect(sqlOnly(q.text)).not.toContain(v)
      }
      expect(q.values).toContain('20Y')
      expect(q.values).toContain('FED_FUNDS')
      expect(q.values).toContain('D2D')
      expect(q.values).toContain('2025-03-04')
      expect(q.values).toContain(0.17)
      expect(q.values).toContainEqual(['FLY'])
      expect(q.values).toContainEqual(['MATCHED_MATURITY'])
    }
  })

  it('drives from the unit table and filters the venue class it claims to serve', () => {
    // Never a bare as_of_date predicate on the legs table: that column is not
    // indexed there, so driving from legs would seq-scan 2.08M rows.
    const { text } = printsSql(resolved('tenor=10Y'))
    expect(text).toMatch(/FROM arbs_dd_unit_v1 u/)
    expect(text).toMatch(/JOIN arbs_usd_swap_tape_legs_v3 l\s+ON l\.package_id = u\.package_id/)
    expect(text).toContain('u.as_of_date = $1::date')
    // A venueClass chip that does not filter is worse than no chip: the panel
    // would sum D2C, D2D and VENUE_UNKNOWN while labelled D2C.
    expect(text).toContain('u.venue_class = $')
    expect(printsCountsSql(resolved('tenor=10Y')).text).toContain('u.venue_class = $')
  })

  it('latestDateSql reads the unit table and returns a text date', () => {
    expect(latestDateSql()).toMatch(/max\(as_of_date\)::text/)
    expect(latestDateSql()).toMatch(/arbs_dd_unit_v1/)
  })
})

describe('a package leg can never carry a mid', () => {
  it('gates the mid CASE on OUTRIGHT, RATE_VS_MID and n_legs = 1', () => {
    const { text } = printsSql(resolved('tenor=10Y&kinds=OUTRIGHT,CURVE,FLY,PKG'))
    expect(text).toMatch(
      /CASE WHEN u\.kind = 'OUTRIGHT' AND u\.rule = 'RATE_VS_MID' AND u\.n_legs = 1/,
    )
  })

  it('assertNoPackageMid throws rather than rendering the fiction', () => {
    expect(() => assertNoPackageMid([{ kind: 'OUTRIGHT', mid_pct: 4.01 }])).not.toThrow()
    expect(() => assertNoPackageMid([{ kind: 'CURVE', mid_pct: null }])).not.toThrow()
    expect(() => assertNoPackageMid([{ kind: 'CURVE', mid_pct: 4.01 }])).toThrow(
      /cannot be inverted into per-leg mids/,
    )
    expect(() => assertNoPackageMid([{ kind: 'FLY', mid_pct: 0 }])).toThrow(/-1, 2, -1/)
  })
})

describe('the disclosures carry their measurements', () => {
  const provenance = {
    curve_name: 'USD-SOFR-1D',
    snapshot_policy: 'STRICT_1MIN_IN_SESSION',
    median_snapshot_lag_seconds: 0,
    median_visibility_lag_seconds: 60,
    max_visibility_lag_seconds: 3600,
    dead_zone_share: 0.925,
    size_not_read: 0,
    tape_generation: 'v3',
    code_vintage: 'abc123',
    dd_generation: 'v1',
  }
  const counts = {
    drawn: 119,
    onMarket: 119,
    withMid: 119,
    dropped: {
      offMarket: 10,
      forwardStart: 57,
      specialTenorType: 0,
      unknownSpecialTenorType: 0,
      packageLegs: 120,
    },
  }
  /** No grid: the fallback branch, which is what Fed Funds 7Y/20Y/30Y gets. */
  const noGrid = {
    available: false,
    points: [],
    curve_name: null,
    snapshot_policy: null,
    window: null,
  }
  const withGrid = {
    available: true,
    points: [
      { ts: '2026-08-07T13:00:00.000Z', mid_pct: 4.27 },
      { ts: '2026-08-07T13:01:00.000Z', mid_pct: 4.271 },
    ],
    curve_name: 'USD-SOFR-1D',
    snapshot_policy: 'STRICT_1MIN_IN_SESSION',
    window: ['2026-08-07T12:45:00.000Z', '2026-08-07T21:15:00.000Z'] as [string, string],
  }
  const base = {
    counts,
    provenance,
    looseTenor: false,
    admittedByLoosening: null,
    observedTenorYears: [9.989, 10.0082] as [number, number],
    tenor: '10Y',
    mid: noGrid,
    rateIndex: 'SOFR',
  }

  it('states the FOMC multiples when FOMC is included', () => {
    const d = buildDisclosures({
      ...base,
      filters: {
        kinds: ['OUTRIGHT'],
        specialTenorTypes: ['STANDARD', 'FOMC'],
        fwdMaxYears: 0.02,
        tenorMatch: 'strict',
        includeOffMarket: false,
      },
    }).join('\n')
    expect(d).toContain('6.8x')
    expect(d).toContain('4.0x')
    expect(d).toContain('FOMC-DATED SWAPS ARE INCLUDED')
  })

  it('always states the reconstruction, the clock and the dead-zone share', () => {
    const d = buildDisclosures({
      ...base,
      filters: {
        kinds: ['OUTRIGHT'],
        specialTenorTypes: ['STANDARD', 'IMM', 'MATCHED_MATURITY'],
        fwdMaxYears: 0.02,
        tenorMatch: 'strict',
        includeOffMarket: false,
      },
    }).join('\n')
    expect(d).toMatch(/Each MARK’s own mid is reconstructed/)
    expect(d).toMatch(/0\.32-0\.57bp/)
    expect(d).toMatch(/EXECUTION clock/)
    expect(d).toMatch(/9[23]% of these calls sit inside the dead zone/)
    expect(d).toMatch(/31x/)
    expect(d).toMatch(/66bp apart/)
    expect(d).toMatch(/1\.7x wider median/)
    expect(d).toMatch(/never summed/)
    expect(d).toMatch(/tape v3, dd v1, code abc123/)
  })
})

describe('median', () => {
  it('drops nulls and averages the middle pair', () => {
    expect(median([])).toBeNull()
    expect(median([null, undefined])).toBeNull()
    expect(median([3, 1, 2])).toBe(2)
    expect(median([4, 1, 3, 2])).toBe(2.5)
    expect(median([null, 5, 1])).toBe(3)
  })
})

// ===========================================================================
// THE CONTINUOUS MID
// ===========================================================================

describe('the grid window comes from the marks, never from a calendar', () => {
  const row = (iso: string) => ({ execution_timestamp: iso })

  it('pads the observed span by MID_PAD_MINUTES on both sides', () => {
    const w = midWindow([
      row('2026-08-07T14:00:00.000Z'),
      row('2026-08-07T13:00:00.000Z'),
      row('2026-08-07T20:30:00.000Z'),
    ])
    expect(w).not.toBeNull()
    expect(w![0]).toBe('2026-08-07T12:45:00.000Z')
    expect(w![1]).toBe('2026-08-07T20:45:00.000Z')
    expect(MID_PAD_MINUTES).toBe(15)
  })

  it('is order-independent — min/max, not first/last', () => {
    const asc = midWindow([row('2026-08-07T13:00:00.000Z'), row('2026-08-07T20:00:00.000Z')])
    const desc = midWindow([row('2026-08-07T20:00:00.000Z'), row('2026-08-07T13:00:00.000Z')])
    expect(asc).toEqual(desc)
  })

  it('is null on an empty day rather than inventing a span', () => {
    // A line with no marks under it is a chart about a curve. This panel is a
    // chart about trades, so it draws nothing rather than something.
    expect(midWindow([])).toBeNull()
    expect(midWindow([row('not-a-date')])).toBeNull()
  })
})

describe('the grid statement', () => {
  it('is (equality, equality, range) on the primary key, in PK order', () => {
    // The PK is (rate_index, tenor_label, ts). Anything else here turns a
    // single ordered index scan over 22.7M rows into something much worse.
    const { text, values } = midGridSql('SOFR', '10Y', '2026-08-07T12:45:00Z', '2026-08-07T21:15:00Z')
    const q = sqlOnly(text)
    expect(q).toContain('g.rate_index  = $1')
    expect(q).toContain('g.tenor_label = $2')
    expect(q).toContain('g.ts >= $3::timestamptz')
    expect(q).toContain('g.ts <= $4::timestamptz')
    expect(q).toContain('ORDER BY g.ts')
    expect(values).toEqual(['SOFR', '10Y', '2026-08-07T12:45:00Z', '2026-08-07T21:15:00Z'])
    // Every value is bound. A window pasted into the text is an injection seam
    // AND defeats the plan cache.
    expect(q).not.toMatch(/2026-08-07/)
  })

  it('never selects the fuzzy band column', () => {
    // THE SAME TRIPWIRE AS THE MARKS. The grid is built on canonical tenors
    // only; in band mode the marks may span 9.50-10.49y but there is exactly
    // one 10Y grid. Looking it up by a row's own tenor_label would mean a
    // different line per mark.
    const { text } = midGridSql('FED_FUNDS', '5Y', '2026-01-01T00:00:00Z', '2026-01-02T00:00:00Z')
    expect(sqlOnly(text)).not.toMatch(/tenor_display/)
  })

  it('asks availability by the PK prefix only', () => {
    const q = sqlOnly(midGridAvailabilitySql())
    expect(q).toMatch(/EXISTS/)
    expect(q).toContain('rate_index = $1')
    expect(q).toContain('tenor_label = $2')
    // No ts predicate: "this tenor has no grid at all" must be answerable
    // independently of whichever window happens to be on screen.
    expect(q).not.toMatch(/\bts\b/)
  })
})

describe('the disclosures say WHICH mid drew the line', () => {
  const provenance = {
    curve_name: 'USD-SOFR-1D',
    snapshot_policy: 'STRICT_1MIN_IN_SESSION',
    median_snapshot_lag_seconds: 0,
    median_visibility_lag_seconds: 60,
    max_visibility_lag_seconds: 3600,
    dead_zone_share: 0.9,
    size_not_read: 0,
    tape_generation: 'v3',
    code_vintage: 'abc123',
    dd_generation: 'v1',
  }
  const counts = {
    drawn: 100, onMarket: 100, withMid: 100,
    dropped: { offMarket: 0, forwardStart: 0, specialTenorType: 0, unknownSpecialTenorType: 0, packageLegs: 0 },
  }
  const filters: PrintsFilters = {
    kinds: ['OUTRIGHT'],
    specialTenorTypes: ['STANDARD'],
    fwdMaxYears: 0.02,
    tenorMatch: 'strict',
    includeOffMarket: false,
  }
  const call = (mid: MidGrid, rateIndex = 'SOFR', tenor = '10Y') =>
    buildDisclosures({
      filters,
      counts,
      provenance,
      looseTenor: false,
      admittedByLoosening: null,
      observedTenorYears: null,
      tenor,
      mid,
      rateIndex,
    }).join('\n')

  const grid: MidGrid = {
    available: true,
    points: [{ ts: '2026-08-07T13:00:00.000Z', mid_pct: 4.27 }],
    curve_name: 'USD-SOFR-1D',
    snapshot_policy: 'STRICT_1MIN_IN_SESSION',
    window: ['2026-08-07T12:45:00.000Z', '2026-08-07T21:15:00.000Z'],
  }

  it('calls the grid line MODELLED and refuses to call it quoted or tradable', () => {
    // The whole reason this line is allowed to exist. A modelled curve that
    // reads as a quote is a worse chart than no curve at all.
    const d = call(grid)
    expect(d).toMatch(/MODELLED 1-minute par grid/)
    expect(d).toMatch(/not a quoted mid and not a tradable level/)
    expect(d).toMatch(/median residual 0\.000000bp/)
    expect(d).toMatch(/p95 0\.132bp/)
    expect(d).toMatch(/BREAKS rather than bridging/)
    expect(d).toMatch(/23:00-00:59 ET/)
  })

  it('names the missing-tenor case explicitly for Fed Funds', () => {
    // Silence here is the failure mode: a reader takes a polyline through
    // eight prints for a picture of the market.
    const d = call({ ...grid, available: false, points: [] }, 'FED_FUNDS', '30Y')
    expect(d).toMatch(/NO CONTINUOUS MID IS AVAILABLE for FED_FUNDS 30Y/)
    expect(d).toMatch(/no 7Y, 20Y or 30Y/)
    expect(d).toMatch(/not a picture of the market between trades/)
    expect(d).not.toMatch(/MODELLED 1-minute par grid/)
  })

  it('distinguishes an absent tenor from an empty window', () => {
    const absent = call({ ...grid, available: false, points: [] })
    const empty = call({ ...grid, available: true, points: [] })
    expect(absent).toMatch(/does not carry this tenor on this index/)
    expect(empty).toMatch(/over this window/)
    expect(empty).not.toMatch(/does not carry this tenor/)
  })

  it('keeps the per-mark reconstruction disclosed under BOTH branches', () => {
    // deviation_bps — and therefore the direction call — is measured against
    // the reconstruction, not against the line. That never stops being true.
    for (const m of [grid, { ...grid, available: false, points: [] }]) {
      expect(call(m)).toMatch(/Each MARK’s own mid is reconstructed/)
    }
  })
})
