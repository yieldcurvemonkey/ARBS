import { describe, expect, it } from '@jest/globals'
import { EMPTY_VALUE } from '../../../constants'
import {
  displayTapeLabel,
  parseTapeLabelSegments,
} from '../TapeLabelCell.helpers'

describe('displayTapeLabel', () => {
  it('returns the raw package tape label from the row when present (execution tags stripped)', () => {
    // Commit 439bbe09 moved UFRO to tape_tags; displayTapeLabel now calls
    // stripExecutionTags() which removes TAPE_TAG_TONES keys (UFRO) but leaves
    // non-tag tokens like PHYS in place.
    expect(
      displayTapeLabel({
        tape_label: 'USD-SOFR-COMPOUND 1D Constant 5Y11M 1Y Outright UFRO PHYS',
        legs_json: [{ tape_label: 'ignored leg label' }],
      } as any),
    ).toBe('USD-SOFR-COMPOUND 1D Constant 5Y11M 1Y Outright PHYS')
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

  it('does not touch "1D" (reset frequency) because it precedes "Constant"', () => {
    const segs = parseTapeLabelSegments('USD-SOFR-COMPOUND 1D Constant Spot 5Y Outright PHYS')
    // "1D Constant" is the reset spec, not a forward; the negative lookahead
    // in the day-count branch keeps it plain.
    expect(segs.find((s) => s.text === '1D')?.isTenor).toBeFalsy()
  })

  it('bolds the literal forward "Spot"', () => {
    const segs = parseTapeLabelSegments('USD-SOFR-COMPOUND 1D Constant Spot 5Y Outright PHYS')
    const tenors = segs.filter((s) => s.isTenor).map((s) => s.text)
    expect(tenors).toContain('Spot')
    expect(tenors).toContain('5Y')
  })

  it('bolds a day-count forward start like "74D" but keeps the trailing tenor bold too', () => {
    const segs = parseTapeLabelSegments(
      'USD-Federal Funds-OIS Compound 1D Constant 74D 6M Outright PHYS',
    )
    const tenors = segs.filter((s) => s.isTenor).map((s) => s.text)
    expect(tenors).toContain('74D')
    expect(tenors).toContain('6M')
    // And the reset frequency "1D" remains plain.
    expect(segs.find((s) => s.text === '1D')?.isTenor).toBeFalsy()
  })

  it('bolds a 70D forward alongside FOMC-dated anchors in the same label', () => {
    const segs = parseTapeLabelSegments(
      'USD-Federal Funds-OIS Compound 1D Constant 70D 6M FOMC APR26 Outright PHYS',
    )
    const tenors = segs.filter((s) => s.isTenor).map((s) => s.text)
    expect(tenors).toContain('70D')
    expect(tenors).toContain('6M')
    expect(tenors).toContain('FOMC APR26')
  })

  it('bolds an IMM contract anchor like "IMM_M2026" alongside the tenor', () => {
    const segs = parseTapeLabelSegments(
      'USD-SOFR-COMPOUND 1D Constant IMM_M2026 5Y Outright MAC UFRO BLOCK PHYS',
    )
    const tenors = segs.filter((s) => s.isTenor).map((s) => s.text)
    expect(tenors).toContain('IMM_M2026')
    expect(tenors).toContain('5Y')
  })

  it('bolds IMM anchors with different month codes and year', () => {
    const segs = parseTapeLabelSegments(
      'USD-SOFR-COMPOUND 1D Constant IMM_H2027 10Y Outright PHYS',
    )
    const tenors = segs.filter((s) => s.isTenor).map((s) => s.text)
    expect(tenors).toContain('IMM_H2027')
    expect(tenors).toContain('10Y')
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
