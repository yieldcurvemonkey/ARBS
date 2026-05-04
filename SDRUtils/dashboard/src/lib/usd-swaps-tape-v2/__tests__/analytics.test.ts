// ABOUTME: Pin the authoritative dealer / custy SEF MIC bucketing.
// The trader-confirmed list (2026-04-25) is what every analytics-dock
// route falls back on when the SDR feed's `venue` column is null /
// non-D2D. Failing this test means a future refactor accidentally
// dropped one of the 6 dealer SEFs and would silently mis-bucket
// Dealerweb / ICAP-Global / Tradition flow as customer.
import {
  CUSTY_MIC_SET,
  IDB_MIC_SET,
  normalizeAnalyticsTapeLabel,
  packageAnalyticsFilterPredicate,
  packageSummaryFixedRateSql,
  packageSummaryRiskSql,
  platformCaseSql,
} from '../analytics'

describe('IDB / CUSTY MIC bucketing', () => {
  it('pins the dealer (IDB) SEF MIC list to the trader-confirmed 6', () => {
    expect([...IDB_MIC_SET].sort()).toEqual(
      ['BGCD', 'DWSF', 'IGDL', 'ISWV', 'TPSE', 'TSEF'].sort(),
    )
  })

  it('pins the custy SEF MIC list to the trader-confirmed 5', () => {
    expect([...CUSTY_MIC_SET].sort()).toEqual(
      ['BBSF', 'BILT', 'TWSF', 'XOFF', 'XXXX'].sort(),
    )
  })

  it('IDB and CUSTY sets are disjoint — no MIC ever in both', () => {
    const overlap = [...IDB_MIC_SET].filter((m) =>
      (CUSTY_MIC_SET as readonly string[]).includes(m),
    )
    expect(overlap).toEqual([])
  })

  it('platformCaseSql includes every dealer MIC in the fallback OR-chain', () => {
    const sql = platformCaseSql('l')
    for (const mic of IDB_MIC_SET) {
      expect(sql).toContain(`= '${mic}'`)
    }
  })

  it('platformCaseSql does NOT match any custy MIC as IDB', () => {
    const sql = platformCaseSql('l')
    for (const mic of CUSTY_MIC_SET) {
      expect(sql).not.toContain(`= '${mic}'`)
    }
  })
})

describe('package summary analytics SQL', () => {
  it('collapses SOFR-OIS tape label variants into one economic analytics key', () => {
    const compoundLabel = normalizeAnalyticsTapeLabel(
      'USD-SOFR-COMPOUND 1D Constant Spot 5Y/10Y/30Y FLY PHY',
    )
    const oisLabel = normalizeAnalyticsTapeLabel(
      'USD-SOFR-OIS Compound 1D Constant Spot 5Y/10Y/30Y FLY PHYS',
    )

    expect(compoundLabel).toBe(oisLabel)
    expect(compoundLabel).toBe(
      'USD-SOFR-OIS COMPOUND 1D CONSTANT SPOT 5Y/10Y/30Y FLY PHYS',
    )
  })

  it('keeps Term SOFR out of the generic SOFR-OIS normalization', () => {
    expect(
      normalizeAnalyticsTapeLabel('USD-SOFR-CME-TERM 3M Spot 5Y Outright PHYS'),
    ).toBe('USD-SOFR-TERM 3M SPOT 5Y OUTRIGHT PHYS')
  })

  it('uses normalized tape labels for analytics filtering while retaining exact-match fast path', () => {
    const predicate = packageAnalyticsFilterPredicate(
      'tape_label',
      '$1',
      'arbs_usd_swap_tape_legs_v2',
    )

    expect(predicate).toContain('p.tape_label = $1')
    expect(predicate).toContain('REGEXP_REPLACE')
    expect(predicate).toContain('USD-SOFR-OIS COMPOUND')
  })

  it('uses fly package spread and belly DV01 conventions', () => {
    const rateSql = packageSummaryFixedRateSql('r')
    const riskSql = packageSummaryRiskSql('r')

    expect(rateSql).toContain('2 * r.fixed_rates')
    expect(rateSql).toContain("- r.fixed_rates[1] - r.fixed_rates")
    expect(riskSql).toContain('r.risks')
    expect(riskSql).toContain('FLY')
  })

  it('uses curve back-minus-front rate and back-leg DV01 conventions', () => {
    const rateSql = packageSummaryFixedRateSql('r')
    const riskSql = packageSummaryRiskSql('r')

    expect(rateSql).toContain("- r.fixed_rates[1]")
    expect(riskSql).toContain('CURVE')
  })
})
