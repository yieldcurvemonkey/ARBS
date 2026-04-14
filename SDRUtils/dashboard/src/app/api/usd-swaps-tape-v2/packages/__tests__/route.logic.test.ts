import { describe, expect, it } from '@jest/globals'
import { buildPackagesSql } from '../route'

describe('buildPackagesSql', () => {
  it('sorts by absolute risk by default', () => {
    const sql = buildPackagesSql('risk', 100)
    expect(sql).toContain('ABS(total_risk) DESC NULLS LAST')
    expect(sql).toContain('LIMIT 100')
  })

  it('excludes outrights', () => {
    const sql = buildPackagesSql('risk', 100)
    expect(sql).toContain("package_type != 'OUTRIGHT'")
  })

  it('supports time / legs / notional sorts', () => {
    expect(buildPackagesSql('time', 50)).toContain('execution_start DESC')
    expect(buildPackagesSql('legs', 50)).toContain('n_package_legs DESC')
    expect(buildPackagesSql('notional', 50)).toContain('ABS(total_notional)')
  })
})
