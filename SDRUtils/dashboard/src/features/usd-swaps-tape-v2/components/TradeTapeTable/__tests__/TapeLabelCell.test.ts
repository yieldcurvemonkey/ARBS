import { describe, expect, it } from '@jest/globals'
import { EMPTY_VALUE } from '../../../constants'
import {
  displayTapeLabel,
  parseTapeLabelSegments,
} from '../TapeLabelCell.helpers'

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

describe('parseTapeLabelSegments', () => {
  it('marks the outright tenor as isTenor', () => {
    const segs = parseTapeLabelSegments('USD-SOFR-COMPOUND 1D Constant Spot 5Y Outright PHYS')
    const tenors = segs.filter((s) => s.isTenor).map((s) => s.text)
    expect(tenors).toContain('5Y')
  })

  it('bolds the full curve tenor pair for a CURVE package', () => {
    const segs = parseTapeLabelSegments('USD-SOFR-COMPOUND 1D Constant Spot 5Y/10Y CURVE PHYS')
    const tenors = segs.filter((s) => s.isTenor).map((s) => s.text)
    expect(tenors).toContain('5Y/10Y')
  })

  it('bolds a three-tenor FLY', () => {
    const segs = parseTapeLabelSegments('USD-SOFR-COMPOUND 1D Constant Spot 2Y/5Y/30Y FLY PHYS')
    const tenors = segs.filter((s) => s.isTenor).map((s) => s.text)
    expect(tenors).toContain('2Y/5Y/30Y')
  })

  it('bolds the FOMC anchor when present', () => {
    const segs = parseTapeLabelSegments('USD-SOFR-COMPOUND 1D Constant FOMC APR26 Outright PHYS')
    const tenors = segs.filter((s) => s.isTenor).map((s) => s.text)
    expect(tenors).toContain('FOMC APR26')
  })

  it('handles compound tenors like 5Y11M', () => {
    const segs = parseTapeLabelSegments('USD-SOFR-COMPOUND 1D Constant Spot 5Y11M Outright PHYS')
    const tenors = segs.filter((s) => s.isTenor).map((s) => s.text)
    expect(tenors).toContain('5Y11M')
  })

  it('returns a single non-tenor segment when no tenor present', () => {
    const segs = parseTapeLabelSegments('USD-SOFR Package')
    expect(segs.every((s) => !s.isTenor)).toBe(true)
  })

  it('does not touch 1D (reset frequency) which is not a tenor suffix', () => {
    const segs = parseTapeLabelSegments('USD-SOFR-COMPOUND 1D Constant Spot 5Y Outright PHYS')
    // "1D" should NOT be bolded because the tenor regex requires [YMW] not D.
    expect(segs.find((s) => s.text === '1D')?.isTenor).toBeFalsy()
  })

  it('returns the empty marker untouched', () => {
    const segs = parseTapeLabelSegments(EMPTY_VALUE)
    expect(segs).toEqual([{ text: EMPTY_VALUE, isTenor: false }])
  })

  it('preserves total text across all segments', () => {
    const label = 'USD-SOFR-COMPOUND 1D Constant Spot 5Y/10Y CURVE PHYS'
    const segs = parseTapeLabelSegments(label)
    expect(segs.map((s) => s.text).join('')).toBe(label)
  })
})
