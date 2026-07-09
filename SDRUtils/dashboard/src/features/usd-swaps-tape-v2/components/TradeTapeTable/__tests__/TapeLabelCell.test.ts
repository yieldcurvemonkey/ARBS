import { describe, expect, it } from '@jest/globals'
import { EMPTY_VALUE } from '../../../constants'
import {
  collapseTenors,
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

describe('collapseTenors', () => {
  it('collapses 5+ repeated tenors into PKG-N', () => {
    const tenors = Array(78).fill('20Y').join('/')
    const label = `USD-SOFR-COMPOUND 1D Constant Spot ${tenors} Package PHYS`
    expect(collapseTenors(label, 78)).toBe(
      'USD-SOFR-COMPOUND 1D Constant Spot PKG-78 PHYS',
    )
  })

  it('collapses approximate tenors (~17Y)', () => {
    const tenors = Array(34).fill('~17Y').join('/')
    const label = `USD-SOFR-OIS Compound 1D Constant BSD ${tenors} Package PHYS`
    expect(collapseTenors(label, 34)).toBe(
      'USD-SOFR-OIS Compound 1D Constant BSD PKG-34 PHYS',
    )
  })

  it('leaves short tenor sequences untouched', () => {
    const label = 'USD-SOFR-COMPOUND 1D Constant Spot 5Y/10Y CURVE PHYS'
    expect(collapseTenors(label, 2)).toBe(label)
  })

  it('leaves fly tenor sequences untouched', () => {
    const label = 'USD-SOFR-COMPOUND 1D Constant Spot 2Y/5Y/30Y FLY PHYS'
    expect(collapseTenors(label, 3)).toBe(label)
  })

  it('collapses 3-tenor PKG followed by Package', () => {
    const label = 'USD-SOFR-COMPOUND 1D Constant Spot 21M/2Y/2Y Package PHYS'
    expect(collapseTenors(label, 3)).toBe(
      'USD-SOFR-COMPOUND 1D Constant Spot PKG-3 PHYS',
    )
  })

  it('collapses 2-tenor PKG followed by Package', () => {
    const label = 'USD-SOFR-OIS Compound 1D Constant Spot 3Y/3Y Package PHYS'
    expect(collapseTenors(label, 2)).toBe(
      'USD-SOFR-OIS Compound 1D Constant Spot PKG-2 PHYS',
    )
  })

  it('does not collapse 2-tenor CURVE (no Package suffix)', () => {
    const label = 'USD-SOFR-OIS Compound 1D Constant Spot 3Y/5Y CURVE PHYS'
    expect(collapseTenors(label, 2)).toBe(label)
  })

  it('falls back to counting slashes when nLegs is null', () => {
    const tenors = Array(10).fill('5Y').join('/')
    const label = `USD-SOFR 1D Constant Spot ${tenors} Package PHYS`
    expect(collapseTenors(label, null)).toBe(
      'USD-SOFR 1D Constant Spot PKG-10 PHYS',
    )
  })

  it('handles mixed tenors in a large package', () => {
    const tenors = '5Y/5Y/7Y/7Y/10Y/10Y/20Y/20Y/30Y/30Y'
    const label = `USD-SOFR-COMPOUND 1D Constant Spot ${tenors} Package PHYS`
    expect(collapseTenors(label, 10)).toBe(
      'USD-SOFR-COMPOUND 1D Constant Spot PKG-10 PHYS',
    )
  })
})

describe('displayTapeLabel', () => {
  it('collapses large package tenor repetitions', () => {
    const tenors = Array(78).fill('20Y').join('/')
    expect(
      displayTapeLabel({
        tape_label: `USD-SOFR-COMPOUND 1D Constant Spot ${tenors} Package PHYS`,
        n_package_legs: 78,
        legs_json: [],
      } as any),
    ).toBe('USD-SOFR-COMPOUND 1D Constant Spot PKG-78 PHYS')
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

  it('bolds the collapsed PKG-N token', () => {
    const segs = parseTapeLabelSegments('USD-SOFR-COMPOUND 1D Constant Spot PKG-78 PHYS')
    const tenors = segs.filter((s) => s.isTenor).map((s) => s.text)
    expect(tenors).toContain('PKG-78')
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

describe('pkgLegsLines gate', () => {
  // pkgLegsLines is not exported — test via the component or export it.
  // For now, test via displayTapeLabel + collapseAlias which are exported.
})

describe('collapseAlias', () => {
  it('leaves short aliases unchanged', () => {
    const label = displayTapeLabel({
      tape_label_ust_alias: 'USD-SOFR Spot 0536/0546 CURVE MMS PHYS',
      tape_label: 'USD-SOFR Spot 10Y/20Y CURVE MMS PHYS',
      n_package_legs: 2,
    } as any)
    expect(label).toContain('0536/0546')
  })

  it('collapses aliases with >4 segments', () => {
    const longAlias = '0330/0530/0730/0930/1130/0131/0331'
    const label = displayTapeLabel({
      tape_label_ust_alias: `USD-SOFR Spot ${longAlias} PKG-7 MMS PHYS`,
      tape_label: 'USD-SOFR Spot 3Y/5Y/7Y/9Y/11Y/13Y/15Y PKG-7 MMS PHYS',
      n_package_legs: 7,
    } as any)
    expect(label).toContain('0330/0530/0730')
    expect(label).toContain('…+4')
    expect(label).not.toContain('1130')
  })

  it('does not collapse exactly 4 segments', () => {
    const label = displayTapeLabel({
      tape_label_ust_alias: 'USD-SOFR Spot 0236/0536/0746/1046 PKG-4 MMS PHYS',
      tape_label: 'fallback',
      n_package_legs: 4,
    } as any)
    expect(label).toContain('0236/0536/0746/1046')
  })
})
