/** @jest-environment jsdom */
import { describe, expect, it, jest } from '@jest/globals'
import { render, screen, fireEvent } from '@testing-library/react'
import '@testing-library/jest-dom'
import { MobileTradeCards } from '../MobileTradeCards'
import { applyOverrides } from '../../../utils/applyOverrides'
import type { UsdSwapTapeRow } from '../../../types'

// Minimal fixture idiom mirrored from utils/__tests__/applyOverrides.test.ts.
const leg = (trade_id: string, tenor = 5) => ({ trade_id, tenor_years: tenor } as any)

const row = (
  package_id: string,
  legs: Array<{ trade_id: string }>,
  extras: Partial<UsdSwapTapeRow> = {},
): UsdSwapTapeRow =>
  ({
    package_id,
    package_type: 'CURVE',
    legs_json: legs,
    ...extras,
  } as any)

describe('MobileTradeCards', () => {
  it('renders one card per normal row', () => {
    const rows = applyOverrides([row('P1', [leg('T1')]), row('P2', [leg('T2')])])
    render(
      <MobileTradeCards rows={rows} loading={false} metricMode="dv01" />,
    )
    expect(screen.getAllByLabelText('Expand legs')).toHaveLength(2)
  })

  it('keys/expands split rows sharing one package_id independently', () => {
    // A SPLIT override explodes one package into multiple display rows that
    // all still carry the SAME package_id -- applyOverrides disambiguates
    // them via __syntheticKey. Before the fix, MobileTradeCards keyed off
    // `row.package_id` alone, so these two cards would collide on both the
    // React `key` and the expandedRows/onToggleRow identity.
    const rows = applyOverrides([
      row('P1', [leg('T1'), leg('T2')], {
        override_type: 'SPLIT',
        override_map: { T1: 'o1', T2: 'o1' },
      }),
    ])
    expect(rows).toHaveLength(2)
    expect(rows.every((r) => r.package_id === 'P1')).toBe(true)
    expect(rows.map((r) => r.__syntheticKey)).toEqual(['P1::split::T1', 'P1::split::T2'])

    const onToggleRow = jest.fn()
    render(
      <MobileTradeCards
        rows={rows}
        loading={false}
        expandedRows={{ 'P1::split::T1': true }}
        onToggleRow={onToggleRow}
        metricMode="dv01"
      />,
    )

    // Only the row keyed 'P1::split::T1' is expanded -- exactly one card
    // shows "Collapse legs", the other still shows "Expand legs". Keying by
    // package_id alone would expand both cards together (or neither).
    expect(screen.getAllByLabelText('Collapse legs')).toHaveLength(1)
    expect(screen.getAllByLabelText('Expand legs')).toHaveLength(1)

    fireEvent.click(screen.getByLabelText('Expand legs'))
    expect(onToggleRow).toHaveBeenCalledWith('P1::split::T2')
    expect(onToggleRow).not.toHaveBeenCalledWith('P1')
  })
})
