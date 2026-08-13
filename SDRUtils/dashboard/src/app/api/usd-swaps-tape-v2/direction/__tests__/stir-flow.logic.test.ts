// ABOUTME: The refusals that keep the STIR flow chart from repeating the one
// bug it has already had.
import { describe, expect, it } from '@jest/globals'
import { BadRequest } from '../route.logic'
import {
  buildPrintTimeMid,
  buildStirDisclosures,
  MAX_INSTRUMENTS,
  MIN_INSTRUMENT_TRADES,
  parseStirFlowParams,
  type ResolvedStirFlowParams,
  type StirFlowRow,
  stirFlowCountsSql,
  stirFlowSql,
  stirInstrumentsSql,
  STIR_RATE_INDEXES,
  TENOR_QUERY_RE,
} from '../stir-flow.logic'

const sp = (q: string) => new URLSearchParams(q)
const OK = 'tenorQuery=2026-07-29->2026-09-16&rateIndex=FED_FUNDS'
const resolved = (q: string = OK, date = '2026-07-29'): ResolvedStirFlowParams => ({
  ...parseStirFlowParams(sp(q)),
  date,
})

describe('the rate index has no default, and that is the whole point', () => {
  it('refuses a request with no rateIndex, and says why', () => {
    // THE HISTORICAL BUG, PINNED. The chart once overlaid SOFR and FED_FUNDS
    // trades on a single Fed-Funds line. SOFR OIS sits ~1.5-2.5bp above the FF
    // line, so correctly classified SOFR receives plotted above an FF mid and
    // looked mislabelled. Giving this a default rebuilds that.
    expect(() => parseStirFlowParams(sp('tenorQuery=2026-07-29->2026-09-16'))).toThrow(BadRequest)
    try {
      parseStirFlowParams(sp('tenorQuery=2026-07-29->2026-09-16'))
    } catch (e) {
      expect((e as Error).message).toMatch(/REQUIRED/)
      expect((e as Error).message).toMatch(/1\.5-2\.5bp/)
      expect((e as Error).message).toMatch(/classifier was right/)
    }
  })

  it('refuses anything that is not exactly one of the two indices', () => {
    for (const bad of ['ALL', 'BOTH', 'sofr', 'BASIS', '']) {
      expect(() => parseStirFlowParams(sp(`tenorQuery=2026-07-29->2026-09-16&rateIndex=${bad}`)))
        .toThrow(BadRequest)
    }
    for (const good of STIR_RATE_INDEXES) {
      expect(parseStirFlowParams(sp(`tenorQuery=2026-07-29->2026-09-16&rateIndex=${good}`)).rateIndex)
        .toBe(good)
    }
  })

  it('binds the index into BOTH the rows and the counts statements', () => {
    // The counts query is what reports how many trades the filter removed. If
    // it did not bind the same index the chip would be meaningless.
    expect(stirFlowSql(resolved()).values).toEqual(
      ['2026-07-29', '2026-07-29->2026-09-16', 'FED_FUNDS'])
    expect(stirFlowCountsSql(resolved()).values).toEqual(
      ['2026-07-29', '2026-07-29->2026-09-16', 'FED_FUNDS'])
    expect(stirFlowCountsSql(resolved()).text).toMatch(/rate_index_clean <> \$3\)::int\s+AS off_index/)
  })
})

describe('the instrument is an exact date pair', () => {
  it('requires effective->maturity and refuses anything else', () => {
    expect(TENOR_QUERY_RE.test('2026-07-29->2026-09-16')).toBe(true)
    for (const bad of ['', '2Y', 'fomc_sep26', '2026-07-29', '2026-07-29->', 'a->b']) {
      expect(() => parseStirFlowParams(sp(`tenorQuery=${bad}&rateIndex=SOFR`))).toThrow(BadRequest)
    }
  })

  it('refuses to offer an all-instrument view', () => {
    try {
      parseStirFlowParams(sp('rateIndex=SOFR'))
    } catch (e) {
      expect((e as Error).message).toMatch(/two different date pairs are two different instruments/i)
    }
  })
})

describe('the SQL', () => {
  it('dedupes to one row per unit and binds every value', () => {
    const { text } = stirFlowSql(resolved())
    expect(text).toMatch(/SELECT DISTINCT ON \(unit_key\)/)
    expect(text).toContain('as_of_date = $1::date')
    expect(text).toContain('tenor_query = $2')
    expect(text).toContain('rate_index_clean = $3')
    expect(text).not.toMatch(/2026-07-29->2026-09-16/) // never interpolated
  })

  it('excludes off-market and keeps tick-rule by default, and both are toggles', () => {
    const def = stirFlowSql(resolved()).text
    expect(def).toMatch(/NOT COALESCE\(is_off_market, false\)/)
    expect(def).not.toMatch(/classification_method <> 'TICK_RULE'/)

    const withOff = stirFlowSql(resolved(`${OK}&includeOffMarket=true`)).text
    expect(withOff).not.toMatch(/NOT COALESCE\(is_off_market, false\)/)

    const noTick = stirFlowSql(resolved(`${OK}&includeTickRule=false`)).text
    expect(noTick).toMatch(/classification_method <> 'TICK_RULE'/)
  })

  it('groups instruments by (instrument, INDEX) together', () => {
    // The same date pair trades on both SOFR and Fed Funds and they are two
    // different instruments with two different mids. Grouping by the date pair
    // alone would offer one picker row that means two things.
    const { text } = stirInstrumentsSql()
    expect(text).toMatch(/GROUP BY tenor_query, rate_index_clean/)
    expect(text).toMatch(/HAVING count\(\*\) >= \$2/)
    expect(text).toMatch(/LIMIT \$3/)
    expect(MIN_INSTRUMENT_TRADES).toBeGreaterThan(1)
    expect(MAX_INSTRUMENTS).toBeGreaterThan(10)
  })
})

describe('the print-time mid', () => {
  const row = (over: Partial<StirFlowRow>): StirFlowRow => ({
    unit_key: 'u', trade_id: 't', package_id: null,
    execution_timestamp: '2026-07-29T14:00:00.000Z',
    curve_timestamp: '2026-07-29T14:00:00.000Z',
    dealer_direction: 'PAID', classification_method: 'RATE_VS_MID',
    direction_confidence: 'HIGH', p_flip: 0.1,
    structure_dv01: 1000, notional: 1e6, dv01: 1000,
    // curve_mid is PERCENT in this table; fixed_rate is a FRACTION.
    fixed_rate: 0.0425, curve_mid: 4.26, spread_to_mid_bps: -1,
    dealer_charge_bps: null, rate_index_clean: 'FED_FUNDS', trade_type: null,
    is_off_market: false, curve_suspect_trade: false,
    tenor_query: '2026-07-29->2026-09-16', tenor_bucket: null,
    curve_name: 'USD-OIS', code_vintage: 'abc', ...over,
  })

  it('does NOT rescale curve_mid, and dedupes to one point per minute', () => {
    const out = buildPrintTimeMid([
      row({ unit_key: 'a', curve_timestamp: '2026-07-29T14:00:10.000Z', curve_mid: 4.26 }),
      row({ unit_key: 'b', curve_timestamp: '2026-07-29T14:00:50.000Z', curve_mid: 4.26 }),
      row({ unit_key: 'c', curve_timestamp: '2026-07-29T14:05:00.000Z', curve_mid: 4.30 }),
    ])
    expect(out).toHaveLength(2)
    expect(out[0]!.mid_pct).toBeCloseTo(4.26, 10)
    expect(out[1]!.mid_pct).toBeCloseTo(4.30, 10)
  })

  it('sorts by time even when the rows arrive by unit_key', () => {
    // DISTINCT ON forces ORDER BY unit_key, so the wire order is NOT time.
    const out = buildPrintTimeMid([
      row({ unit_key: 'z', curve_timestamp: '2026-07-29T15:00:00.000Z', curve_mid: 5 }),
      row({ unit_key: 'a', curve_timestamp: '2026-07-29T13:00:00.000Z', curve_mid: 4 }),
    ])
    expect(out.map((p) => p.mid_pct)).toEqual([4, 5])
  })

  it('drops a row with no mid rather than inventing one', () => {
    expect(buildPrintTimeMid([row({ curve_mid: null })])).toHaveLength(0)
  })

  it('falls back to the execution instant when curve_timestamp is absent', () => {
    const out = buildPrintTimeMid([row({ curve_timestamp: null })])
    expect(out).toHaveLength(1)
  })
})

describe('the disclosures carry their measurements', () => {
  const counts = {
    drawn: 141, onMarketMid: 104, tickRule: 37, offMarket: 37,
    offIndex: 12, noMid: 41, curveSuspect: 2,
  }
  const call = (over: Partial<Parameters<typeof buildStirDisclosures>[0]> = {}) =>
    buildStirDisclosures({
      counts,
      filters: { includeOffMarket: false, includeTickRule: true },
      rateIndex: 'FED_FUNDS',
      tenorQuery: '2026-07-29->2026-09-16',
      curveName: 'USD-OIS',
      midPoints: 104,
      ...over,
    }).join('\n')

  it('states the index pinning as the bug it prevents, with the count removed', () => {
    const d = call()
    expect(d).toMatch(/RATE INDEX IS PINNED TO FED_FUNDS/)
    expect(d).toMatch(/12 trade\(s\) on the other index were removed/)
    expect(d).toMatch(/classifier was right; the chart was wrong/)
  })

  it('refuses to call the line continuous', () => {
    const d = call()
    expect(d).toMatch(/NOT a continuous curve/)
    expect(d).toMatch(/14,367 distinct/)
    expect(d).toMatch(/drawn, not measured/)
  })

  it('names the unit trap rather than the sign it looks like', () => {
    // The raw columns disagree by 100x, which makes every RECEIVED trade look
    // like it printed below its mid. Saying "marks sit at the traded rate"
    // without saying why would leave the reader to rediscover that.
    const d = call()
    expect(d).toMatch(/DIFFERENT UNITS/)
    expect(d).toMatch(/99\.95%/)
    expect(d).toMatch(/99\.88%/)
    expect(d).toMatch(/factor of 100, not a mid/)
    expect(d).toMatch(/RECEIVED above the mid, PAID below/)
  })

  it('says tick-rule spread does not track direction when they are shown', () => {
    expect(call()).toMatch(/1,331 positive \/ 3,914/)
    expect(call({ filters: { includeOffMarket: false, includeTickRule: false } }))
      .toMatch(/TICK_RULE trade\(s\) hidden/)
  })
})
