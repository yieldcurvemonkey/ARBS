import { describe, expect, it } from '@jest/globals'
import { rowClassName } from '../columns.helpers'

const base = {
  package_id: 'P1',
  package_type: 'OUTRIGHT',
  legs_count: 1,
  execution_start: '2026-04-14T14:30:00Z',
  execution_end: '2026-04-14T14:30:00Z',
  package_metrics: {},
  legs_json: [],
}

describe('rowClassName', () => {
  it('returns default classes for a vanilla new-risk row', () => {
    expect(rowClassName({ ...base, is_new_risk: true } as any)).toBe('')
  })

  it('highlights clearing termination with a left-border accent', () => {
    const cls = rowClassName({ ...base, is_clearing_termination_any: true } as any)
    expect(cls).toContain('bg-red-950/40')
    expect(cls).toContain('border-l-2')
  })

  it('unwind trumps compression in row class', () => {
    const cls = rowClassName({
      ...base,
      is_unwind: true,
      is_compression_any: true,
    } as any)
    expect(cls).toContain('bg-red-950/25')
    expect(cls).not.toContain('zinc')
  })

  it('termination (non-compression) renders rose', () => {
    expect(
      rowClassName({ ...base, is_termination_any: true, is_compression_any: false } as any),
    ).toContain('rose-950')
  })

  it('compression-only renders zinc italic', () => {
    expect(rowClassName({ ...base, is_compression_any: true } as any)).toContain('italic')
  })

  it('novation renders purple', () => {
    expect(rowClassName({ ...base, is_novation_any: true } as any)).toContain('purple')
  })

  it('reset-opt renders neutral + smaller text', () => {
    const cls = rowClassName({ ...base, is_reset_optimization_any: true } as any)
    expect(cls).toContain('neutral')
    expect(cls).toContain('text-xs')
  })

  it('correction renders sky', () => {
    expect(rowClassName({ ...base, is_correction_any: true } as any)).toContain('sky')
  })
})
