import { describe, expect, it } from '@jest/globals'
import { buildRiskConcentrationSql, GROUPABLE } from '../route.logic'

describe('buildRiskConcentrationSql', () => {
  it('emits a grouped aggregate on the requested column', () => {
    const sql = buildRiskConcentrationSql('tape_label', false)
    expect(sql).toContain('l.tape_label AS value')
    expect(sql).toContain('GROUP BY l.tape_label')
    expect(sql).toContain('ABS(SUM(l.risk))')
  })

  it('adds the clean-tape filter when clean=true', () => {
    const sql = buildRiskConcentrationSql('trade_type', true)
    expect(sql).toContain('NOT l.is_unwind')
    expect(sql).toContain('NOT l.is_compression')
    expect(sql).toContain('NOT l.is_ufro')
  })

  it('reads the live v2 leg table (not the frozen v1)', () => {
    const sql = buildRiskConcentrationSql('tape_label', false)
    expect(sql).toContain('arbs_usd_swap_tape_legs_v2')
    expect(sql).not.toContain('legs_v1')
  })

  it('exports every documented groupBy column', () => {
    expect(Object.keys(GROUPABLE)).toEqual(
      expect.arrayContaining([
        'tape_label',
        'trade_type',
        'venue',
        'ccp',
        'session',
        'tenor',
        'rate_index',
        'fomc_meeting',
      ]),
    )
  })
})
