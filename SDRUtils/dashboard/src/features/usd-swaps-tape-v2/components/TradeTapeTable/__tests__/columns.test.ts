import { describe, expect, it } from '@jest/globals'
import { rowClassName } from '../columns.helpers'

const base = {
  package_id: 'P1',
  // Intentionally omit package_type/trade_type here so existing lifecycle-only
  // assertions stay isolated from the trade-type border accent added in Task 3.
  package_type: null,
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

describe('rowClassName — trade_type accent', () => {
  it('adds left-border accent for OUTRIGHT trade_type', () => {
    const cls = rowClassName({ ...base, trade_type: 'OUTRIGHT', is_new_risk: true } as any)
    expect(cls).toMatch(/border-l-2/)
    expect(cls).toMatch(/border-slate/)
  })

  it('uses CURVE color for CURVE trade_type', () => {
    const cls = rowClassName({ ...base, trade_type: 'CURVE' } as any)
    expect(cls).toMatch(/border-sky/)
  })

  it('uses FLY color for FLY trade_type', () => {
    const cls = rowClassName({ ...base, trade_type: 'FLY' } as any)
    expect(cls).toMatch(/border-indigo/)
  })

  it('falls back to package_type when trade_type missing', () => {
    const cls = rowClassName({ ...base, package_type: 'CURVE' } as any)
    expect(cls).toMatch(/border-sky/)
  })

  it('composes with lifecycle color (unwind keeps red background AND adds border)', () => {
    const cls = rowClassName({ ...base, trade_type: 'FLY', is_unwind: true } as any)
    expect(cls).toMatch(/bg-red-950\/25/)
    expect(cls).toMatch(/border-indigo/)
  })
})
