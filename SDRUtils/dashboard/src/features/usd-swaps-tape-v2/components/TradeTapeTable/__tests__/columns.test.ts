import { describe, expect, it } from '@jest/globals'
import { rowClassName } from '../columns.helpers'

const base = {
  package_id: 'P1',
  // Intentionally omit package_type/trade_type here so existing lifecycle-only
  // assertions stay isolated from the trade-type row tint.
  package_type: null,
  legs_count: 1,
  execution_start: '2026-04-14T14:30:00Z',
  execution_end: '2026-04-14T14:30:00Z',
  package_metrics: {},
  legs_json: [],
}

describe('rowClassName', () => {
  it('applies the default trade-type tint for a vanilla new-risk row with no known type', () => {
    const cls = rowClassName({ ...base, is_new_risk: true } as any)
    // Default fallback tint mirrors swaption tape behavior.
    expect(cls).toContain('!bg-gray-900/30')
  })

  it('highlights clearing termination with a red tone and left-border accent', () => {
    const cls = rowClassName({ ...base, is_clearing_termination_any: true } as any)
    expect(cls).toContain('!bg-red-950')
    expect(cls).toContain('border-l-2')
    expect(cls).toContain('border-red-500')
  })

  it('unwind trumps compression in row class', () => {
    const cls = rowClassName({
      ...base,
      is_unwind: true,
      is_compression_any: true,
    } as any)
    expect(cls).toContain('!bg-red-900/40')
    expect(cls).not.toContain('zinc')
    expect(cls).not.toContain('italic')
  })

  it('termination (non-compression) renders rose', () => {
    expect(
      rowClassName({
        ...base,
        is_termination_any: true,
        is_compression_any: false,
      } as any),
    ).toContain('rose')
  })

  it('compression-only renders zinc italic', () => {
    const cls = rowClassName({ ...base, is_compression_any: true } as any)
    expect(cls).toContain('italic')
    expect(cls).toContain('zinc')
  })

  it('reset-opt renders neutral tint', () => {
    const cls = rowClassName({
      ...base,
      is_reset_optimization_any: true,
    } as any)
    expect(cls).toContain('neutral')
  })

  it('novation adds a purple accent ring on top of the trade-type tint', () => {
    const cls = rowClassName({ ...base, is_novation_any: true } as any)
    expect(cls).toContain('ring-purple')
  })

  it('correction adds a sky accent ring on top of the trade-type tint', () => {
    const cls = rowClassName({ ...base, is_correction_any: true } as any)
    expect(cls).toContain('ring-sky')
  })
})

describe('rowClassName — trade_type tint', () => {
  it('paints the full row with the OUTRIGHT tone and border accent', () => {
    const cls = rowClassName({
      ...base,
      trade_type: 'OUTRIGHT',
      is_new_risk: true,
    } as any)
    expect(cls).toContain('!bg-gray-800/50')
    expect(cls).toMatch(/border-l-2/)
    expect(cls).toMatch(/border-slate/)
  })

  it('uses CURVE tint + border for CURVE trade_type', () => {
    const cls = rowClassName({ ...base, trade_type: 'CURVE' } as any)
    expect(cls).toContain('!bg-sky-900/30')
    expect(cls).toMatch(/border-sky/)
  })

  it('uses FLY tint + border for FLY trade_type', () => {
    const cls = rowClassName({ ...base, trade_type: 'FLY' } as any)
    expect(cls).toContain('!bg-indigo-900/30')
    expect(cls).toMatch(/border-indigo/)
  })

  it('falls back to package_type when trade_type missing', () => {
    const cls = rowClassName({ ...base, package_type: 'CURVE' } as any)
    expect(cls).toContain('!bg-sky-900/30')
    expect(cls).toMatch(/border-sky/)
  })

  it('replaces the trade-type tint with a red inactive tone on unwind, but keeps the type border', () => {
    const cls = rowClassName({
      ...base,
      trade_type: 'FLY',
      is_unwind: true,
    } as any)
    expect(cls).toContain('!bg-red-900/40')
    // Trade-type border should still be visible so traders can tell the
    // structure even on an inactive row.
    expect(cls).toMatch(/border-indigo/)
  })
})
