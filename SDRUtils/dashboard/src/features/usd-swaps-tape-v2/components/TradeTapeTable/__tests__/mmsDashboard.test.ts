import {
  packageTypeDisplayLabel,
  packageTypeBadgeClassName,
} from '../columns.helpers'
import {
  displayTapeLabel,
  parseTapeLabelSegments,
} from '../TapeLabelCell.helpers'

describe('MMS package badge', () => {
  it('labels matched-maturity package types', () => {
    expect(packageTypeDisplayLabel('MATCHED_MATURITY')).toBe('MMS')
    expect(packageTypeDisplayLabel('MATCHED_MATURITY_CURVE')).toBe('MMS Curve')
    expect(packageTypeDisplayLabel('MATCHED_MATURITY_FLY')).toBe('MMS Fly')
  })

  it('gives matched-maturity a tone distinct from the OUTRIGHT fallback', () => {
    const outright = packageTypeBadgeClassName('OUTRIGHT')
    expect(packageTypeBadgeClassName('MATCHED_MATURITY')).not.toBe(outright)
    expect(packageTypeBadgeClassName('MATCHED_MATURITY_CURVE')).not.toBe(outright)
    expect(packageTypeBadgeClassName('MATCHED_MATURITY_FLY')).not.toBe(outright)
  })
})

describe('MMS tape label rendering', () => {
  it('prefers the UST-alias label when present', () => {
    const row: any = {
      tape_label:
        'USD-SOFR-OIS Compound 1D Constant Spot 10Y/20Y CURVE MMS PHYS',
      tape_label_ust_alias:
        'USD-SOFR-OIS Compound 1D Constant Spot 0536/0546 CURVE MMS PHYS',
      n_package_legs: 2,
    }
    const out = displayTapeLabel(row)
    expect(out).toContain('0536/0546')
    expect(out).toContain('MMS')
  })

  it('falls back to tape_label when no alias is present', () => {
    const row: any = {
      tape_label: 'USD-SOFR-OIS Compound 1D Constant Spot 5Y/10Y CURVE PHYS',
      n_package_legs: 2,
    }
    expect(displayTapeLabel(row)).toContain('5Y/10Y')
  })

  it('bolds the numeric MMYY alias token (single and joined)', () => {
    for (const label of ['Spot 0236 MMS PHYS', 'Spot 0536/0546 CURVE MMS PHYS']) {
      const segs = parseTapeLabelSegments(label)
      expect(segs.some((s) => s.isTenor && /\d{4}/.test(s.text))).toBe(true)
    }
  })

  it('does not bold the MMS / PHYS descriptor words', () => {
    const segs = parseTapeLabelSegments('Spot 0236 MMS PHYS')
    for (const word of ['MMS', 'PHYS']) {
      const seg = segs.find((s) => s.text.trim() === word)
      expect(seg?.isTenor ?? false).toBe(false)
    }
  })
})
