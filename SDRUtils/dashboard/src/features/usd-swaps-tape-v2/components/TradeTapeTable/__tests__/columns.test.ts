import { describe, expect, it } from '@jest/globals'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { rowClassName } from '../columns.helpers'
import {
  packageIndicatorDisplay,
  packageTypeBadgeClassName,
  packageTypeDisplayLabel,
} from '../columns.helpers'
import { formatOtherLvl } from '../../../utils/format'
import { COLUMN_DEFS } from '../../../constants'

const columnsSource = readFileSync(
  resolve(
    process.cwd(),
    'src/features/usd-swaps-tape-v2/components/TradeTapeTable/columns.tsx',
  ),
  'utf8',
)

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

  // Phase 3 cutover: matrix tags an admin row as inactive even when no
  // legacy is_*_any flag is set (e.g. an SDR port transfer that didn't
  // land in the legacy lifecycle taxonomy).
  it('contributes_to_flow_any=false renders an inactive admin tone', () => {
    const cls = rowClassName({
      ...base,
      contributes_to_flow_any: false,
    } as any)
    expect(cls).toContain('!bg-slate-900/40')
    expect(cls).toContain('italic')
  })

  it('state_machine_violation_any paints yellow regardless of trade type', () => {
    const cls = rowClassName({
      ...base,
      trade_type: 'CURVE',
      state_machine_violation_any: true,
    } as any)
    expect(cls).toContain('!bg-yellow-900/40')
    expect(cls).toContain('border-yellow-400')
  })

  it('state_machine_violation on a live row still surfaces a yellow ring', () => {
    const cls = rowClassName({
      ...base,
      is_new_risk: true,
      state_machine_violation_any: true,
    } as any)
    // Violation routes through the inactive branch (yellow tone wins).
    expect(cls).toContain('yellow')
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

  // Composite package types (SPREADOVER_CURVE, SPREADOVER_FLY,
  // MATCHED_MATURITY_CURVE, MATCHED_MATURITY_FLY) are derivative structures —
  // they're still curves/flies at heart but each leg is itself a spreadover /
  // matched-maturity. Trader feedback: keep the CURVE/FLY family tint +
  // accent-border, but dim the tone slightly so composites read as a related
  // but distinct class when scrolling the tape.
  it('SPREADOVER_CURVE rows get a lighter CURVE tint + sky border', () => {
    const cls = rowClassName({ ...base, package_type: 'SPREADOVER_CURVE' } as any)
    expect(cls).toContain('!bg-blue-900/20')
    expect(cls).toMatch(/border-sky/)
  })

  it('MATCHED_MATURITY_CURVE rows get a lighter CURVE tint + sky border', () => {
    const cls = rowClassName({
      ...base,
      package_type: 'MATCHED_MATURITY_CURVE',
    } as any)
    expect(cls).toContain('!bg-blue-900/20')
    expect(cls).toMatch(/border-sky/)
  })

  it('SPREADOVER_FLY rows get a lighter FLY tint + indigo border', () => {
    const cls = rowClassName({ ...base, package_type: 'SPREADOVER_FLY' } as any)
    expect(cls).toContain('!bg-yellow-900/15')
    expect(cls).toMatch(/border-indigo/)
  })

  it('MATCHED_MATURITY_FLY rows get a lighter FLY tint + indigo border', () => {
    const cls = rowClassName({
      ...base,
      package_type: 'MATCHED_MATURITY_FLY',
    } as any)
    expect(cls).toContain('!bg-yellow-900/15')
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

  it('COLUMN_DEFS includes the Phase 3 economic-class column', () => {
    const col = COLUMN_DEFS.find((d) => d.key === 'class')
    expect(col).toBeTruthy()
    expect(col!.header).toBe('Class')
  })

  it('COLUMN_DEFS includes the Phase 4-5 quality-flag column', () => {
    const col = COLUMN_DEFS.find((d) => d.key === 'quality')
    expect(col).toBeTruthy()
    expect(col!.header).toBe('Q')
  })

  it('formatOtherLvl produces stacked OPA/PTP/PTS lines for a row fixture', () => {
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
      pts: 0.0025,
    })
    expect(result.opaLine).toBe('OPA: 15.6k')
    expect(result.ptpLine).toBe('PTP: -671.9k')
    expect(result.ptsLine).toBe('PTS: 0.0025')
  })

  it('formatOtherLvl em-dashes all three lines when OPA, PTP, and PTS are null', () => {
    const result = formatOtherLvl({
      legOpa: [null],
      opaCurrency: [null],
      ptp: null,
      ptpCurrency: null,
      pts: null,
    })
    expect(result.opaLine).toBe('OPA: \u2014')
    expect(result.ptpLine).toBe('PTP: \u2014')
    expect(result.ptsLine).toBe('PTS: \u2014')
  })
})

describe('column filter menu wiring', () => {
  it('keeps PrimeReact menu filters in multi-rule mode', () => {
    expect(columnsSource).toContain('showFilterOperator: true')
    expect(columnsSource).toContain('showAddButton: true')
    expect(columnsSource).toContain('maxConstraints: 4')
  })
})

// The funnel icon button sits inside the header cell right next to the
// sortable label. Before this change it was 1.1rem x 1.1rem — a 17px hit
// target — so traders frequently clicked the label by accident and flipped
// the sort instead of opening the filter popup. Enlarge the hit area without
// growing the icon itself (add padding; keep the icon small visually).
describe('filter button hit area', () => {
  const tradeTapeSource = readFileSync(
    resolve(
      process.cwd(),
      'src/features/usd-swaps-tape-v2/components/UsdSwapsTradeTape.tsx',
    ),
    'utf8',
  )

  // Helper: extract the block of rules scoped to the filter-menu button so
  // assertions are robust to rule reordering.
  function filterButtonBlock(): string {
    const match = tradeTapeSource.match(
      /\.p-column-filter-menu-button\s*\{[^}]+\}/g,
    )
    return (match ?? []).join('\n')
  }

  it('sizes the funnel button hit area at least 1.6rem x 1.6rem', () => {
    const block = filterButtonBlock()
    expect(block).toMatch(/min-width:\s*1\.[6-9]rem/)
    expect(block).toMatch(/min-height:\s*1\.[6-9]rem/)
  })

  it('adds padding around the funnel icon to widen the click target', () => {
    const block = filterButtonBlock()
    expect(block).toMatch(/padding:\s*0\.(25|3|35|4|45|5)rem/)
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
    // Null/undefined means the DB column isn't populated for this row — show
    // the shared empty marker so traders can't mistake it for a real `false`.
    expect(packageIndicatorDisplay(null)).toBe('—')
    expect(packageIndicatorDisplay(undefined)).toBe('—')
    expect(packageIndicatorDisplay('true')).toBe('true')
    expect(packageIndicatorDisplay('false')).toBe('false')
    expect(packageIndicatorDisplay('')).toBe('—')
  })
})
