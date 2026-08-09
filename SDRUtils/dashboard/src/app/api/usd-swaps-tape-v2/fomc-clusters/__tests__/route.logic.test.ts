import { describe, expect, it } from '@jest/globals'
import { TAPE_LEGS } from '@/lib/tape-tables'
import { FOMC_CLUSTERS_SQL } from '../route.logic'

describe('FOMC_CLUSTERS_SQL', () => {
  it('aggregates over FOMC-dated legs per meeting label', () => {
    expect(FOMC_CLUSTERS_SQL).toContain('l.fomc_meeting_label')
    expect(FOMC_CLUSTERS_SQL).toContain('l.is_fomc_dated = TRUE')
    expect(FOMC_CLUSTERS_SQL).toContain('GROUP BY l.fomc_meeting_label')
  })

  it('exposes the has_multi_meeting_flow boolean roll-up', () => {
    expect(FOMC_CLUSTERS_SQL).toContain('BOOL_OR(l.is_multi_meeting_cluster)')
  })

  it('parameterizes the as-of date', () => {
    expect(FOMC_CLUSTERS_SQL).toContain('l.as_of_date = $1::date')
  })

  it('reads the current-generation leg table (not the frozen v1)', () => {
    expect(FOMC_CLUSTERS_SQL).toContain(TAPE_LEGS)
    expect(FOMC_CLUSTERS_SQL).not.toContain('legs_v1')
  })
})
