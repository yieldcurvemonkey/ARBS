import { describe, expect, it } from '@jest/globals'
import { TAPE_LEGS } from '@/lib/tape-tables'
import { CLUSTERS_SQL } from '../route.logic'

describe('CLUSTERS_SQL', () => {
  it('groups per cluster_id with min/max coalesced-anchor timestamps', () => {
    expect(CLUSTERS_SQL).toContain('MIN(COALESCE(original_execution_timestamp, execution_timestamp))')
    expect(CLUSTERS_SQL).toContain('MAX(COALESCE(original_execution_timestamp, execution_timestamp))')
    expect(CLUSTERS_SQL).toContain('GROUP BY cluster_id')
  })

  it('reads the current-generation leg table (not the frozen v1)', () => {
    expect(CLUSTERS_SQL).toContain(TAPE_LEGS)
    expect(CLUSTERS_SQL).not.toContain('legs_v1')
  })

  it('truncates tape_labels to top 5', () => {
    expect(CLUSTERS_SQL).toContain('(ARRAY_AGG(DISTINCT tape_label ORDER BY tape_label))[1:5]')
  })

  it('excludes rows with no cluster_id', () => {
    expect(CLUSTERS_SQL).toContain('cluster_id IS NOT NULL')
  })
})
