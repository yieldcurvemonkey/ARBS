// ABOUTME: Pin the authoritative dealer / custy SEF MIC bucketing.
// The trader-confirmed list (2026-04-25) is what every analytics-dock
// route falls back on when the SDR feed's `venue` column is null /
// non-D2D. Failing this test means a future refactor accidentally
// dropped one of the 6 dealer SEFs and would silently mis-bucket
// Dealerweb / ICAP-Global / Tradition flow as customer.
import { CUSTY_MIC_SET, IDB_MIC_SET, platformCaseSql } from '../analytics'

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
