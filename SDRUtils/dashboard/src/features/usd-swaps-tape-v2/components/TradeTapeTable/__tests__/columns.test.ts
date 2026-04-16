import { describe, expect, it } from '@jest/globals'
import { rowClassName } from '../columns.helpers'
import {
  packageIndicatorDisplay,
  packageTypeBadgeClassName,
  packageTypeDisplayLabel,
} from '../columns.helpers'
import { formatOtherLvl } from '../../../utils/format'
import { COLUMN_DEFS } from '../../../constants'

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

describe('rowClassName — trade_type tint (Bloomberg muted palette)', () => {
  it('paints the full row with the OUTRIGHT tone and border accent', () => {
    const cls = rowClassName({
      ...base,
      trade_type: 'OUTRIGHT',
      is_new_risk: true,
    } as any)
    expect(cls).toContain('!bg-slate-800/30')
    expect(cls).toMatch(/border-l-2/)
    expect(cls).toMatch(/border-slate/)
  })

  it('uses CURVE tint + border for CURVE trade_type', () => {
    const cls = rowClassName({ ...base, trade_type: 'CURVE' } as any)
    expect(cls).toContain('!bg-blue-900/30')
    expect(cls).toMatch(/border-sky/)
  })

  it('uses FLY tint + border for FLY trade_type', () => {
    const cls = rowClassName({ ...base, trade_type: 'FLY' } as any)
    expect(cls).toContain('!bg-yellow-900/25')
    expect(cls).toMatch(/border-indigo/)
  })

  it('STRADDLE rows get the teal tint', () => {
    const cls = rowClassName({ ...base, package_type: 'STRADDLE' } as any)
    expect(cls).toContain('!bg-teal-900/30')
  })

  it('STRANGLE rows get the fuchsia tint', () => {
    const cls = rowClassName({ ...base, package_type: 'STRANGLE' } as any)
    expect(cls).toContain('!bg-fuchsia-900/25')
  })

  it('UNWIND overrides the structure tint with red regardless of structure', () => {
    const cls = rowClassName({
      ...base,
      package_type: 'STRADDLE',
      is_unwind: true,
    } as any)
    expect(cls).toContain('!bg-red-900/40')
  })

  it('falls back to package_type when trade_type missing', () => {
    const cls = rowClassName({ ...base, package_type: 'CURVE' } as any)
    expect(cls).toContain('!bg-blue-900/30')
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

describe('other_lvl column wiring', () => {
  // NOTE(feedback-round-1): testing the column body through getColumns would
  // require importing columns.tsx, and the project's ts-jest config uses
  // `jsx: preserve` — which leaves JSX unparsed inside Jest. Tests below
  // exercise the same logic at the formatter + COLUMN_DEFS boundary.

  it('COLUMN_DEFS registers other_lvl with width 110', () => {
    const def = COLUMN_DEFS.find((d) => d.key === 'other_lvl')
    expect(def).toBeTruthy()
    expect(def!.width).toBe(110)
    expect(def!.header).toBe('Other Lvl')
  })

  it('COLUMN_DEFS registers pkg and pkg_ind columns in the tape header set', () => {
    expect(COLUMN_DEFS.find((d) => d.key === 'pkg')?.header).toBe('Pkg')
    expect(COLUMN_DEFS.find((d) => d.key === 'pkg_ind')?.header).toBe('Pkg Ind')
  })

  it('formatOtherLvl produces stacked OPA/PTP lines for a row fixture', () => {
    const legs = [
      { other_payment_amount: 15627.6, other_payment_currency: 'USD' as const },
      { other_payment_amount: null },
    ]
    const result = formatOtherLvl({
      legOpa: legs.map((l) => l.other_payment_amount ?? null),
      opaCurrency: legs.map((l) =>
        'other_payment_currency' in l ? l.other_payment_currency ?? null : null,
      ),
      ptp: -671880,
      ptpCurrency: 'USD',
    })
    expect(result.opaLine).toBe('OPA: 15.6k')
    expect(result.ptpLine).toBe('PTP: -671.9k')
  })

  it('formatOtherLvl em-dashes both lines when OPA and PTP are null', () => {
    const result = formatOtherLvl({
      legOpa: [null],
      opaCurrency: [null],
      ptp: null,
      ptpCurrency: null,
    })
    expect(result.opaLine).toBe('OPA: \u2014')
    expect(result.ptpLine).toBe('PTP: \u2014')
  })
})

describe('package column helpers', () => {
  it('formats supported package types with trader-facing labels', () => {
    expect(packageTypeDisplayLabel('OUTRIGHT')).toBe('Outright')
    expect(packageTypeDisplayLabel('CURVE')).toBe('Curve')
    expect(packageTypeDisplayLabel('FLY')).toBe('Fly')
  })

  it('maps package type badges onto the swaption-style tone palette', () => {
    expect(packageTypeBadgeClassName('OUTRIGHT')).toContain('bg-slate-800')
    expect(packageTypeBadgeClassName('CURVE')).toContain('bg-sky-900')
    expect(packageTypeBadgeClassName('FLY')).toContain('bg-indigo-900')
  })

  it('renders package indicator values as explicit true/false text', () => {
    expect(packageIndicatorDisplay(true)).toBe('true')
    expect(packageIndicatorDisplay(false)).toBe('false')
    expect(packageIndicatorDisplay(null)).toBe('false')
  })
})
