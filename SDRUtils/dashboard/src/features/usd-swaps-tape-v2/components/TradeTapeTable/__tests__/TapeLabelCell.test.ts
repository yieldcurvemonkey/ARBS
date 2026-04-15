import { describe, expect, it } from '@jest/globals'
import { EMPTY_VALUE } from '../../../constants'
import { displayTapeLabel } from '../TapeLabelCell.helpers'

describe('displayTapeLabel', () => {
  it('returns the raw package tape label from the row when present', () => {
    expect(
      displayTapeLabel({
        tape_label: 'USD-SOFR-COMPOUND 1D Constant 5Y11M 1Y Outright UFRO PHYS',
        legs_json: [{ tape_label: 'ignored leg label' }],
      } as any),
    ).toBe('USD-SOFR-COMPOUND 1D Constant 5Y11M 1Y Outright UFRO PHYS')
  })

  it('falls back to the first leg tape label when the row-level label is empty', () => {
    expect(
      displayTapeLabel({
        tape_label: '   ',
        legs_json: [{ tape_label: 'USD-SOFR 5Y Outright' }],
      } as any),
    ).toBe('USD-SOFR 5Y Outright')
  })

  it('returns the empty marker when no tape label is available', () => {
    expect(displayTapeLabel({ legs_json: [] } as any)).toBe(EMPTY_VALUE)
  })
})
