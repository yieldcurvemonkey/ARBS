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
  parsePrintsParams,
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
  const base = {
    counts,
    provenance,
    looseTenor: false,
    admittedByLoosening: null,
    observedTenorYears: [9.989, 10.0082] as [number, number],
    tenor: '10Y',
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
    expect(d).toMatch(/RECONSTRUCTED, not quoted/)
    expect(d).toMatch(/0\.32-0\.57 bp/)
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
