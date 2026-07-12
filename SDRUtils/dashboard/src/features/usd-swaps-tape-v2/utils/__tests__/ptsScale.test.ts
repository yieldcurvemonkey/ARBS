import {
  fixedRateSpreadToBp,
  ptsInBp,
  derivedSpreadBp,
  formatBp,
  findScaleMatch,
} from '../ptsScale'

describe('fixedRateSpreadToBp', () => {
  it('scales decimal rates by 10000', () => {
    expect(fixedRateSpreadToBp(0.00333, [0.04029, 0.04362])).toBeCloseTo(33.3, 2)
  })
  it('scales percent rates by 100', () => {
    expect(fixedRateSpreadToBp(0.333, [4.029, 4.362])).toBeCloseTo(33.3, 2)
  })
  it('defaults to x100 with no rates', () => {
    expect(fixedRateSpreadToBp(0.333, [])).toBeCloseTo(33.3, 2)
  })
})

describe('ptsInBp — tie-out to derived spread (curve/fly)', () => {
  it('curve 3Y/20Y: PTS 0.333 ties 33.3bp derived at 100x', () => {
    expect(ptsInBp(0.333, 33.3)).toBeCloseTo(33.3, 1)
  })
  it('curve 4Y/10Y: PTS 0.0012755 ties 12.8bp derived at 10000x', () => {
    expect(ptsInBp(0.0012755, 12.8)).toBeCloseTo(12.755, 2)
  })
  it('fly 5Y/8Y/15Y: PTS -0.143 ties -14.2bp derived at 100x', () => {
    expect(ptsInBp(-0.143, -14.2)).toBeCloseTo(-14.3, 1)
  })
})

describe('ptsInBp — magnitude band (spreadover, no derived spread)', () => {
  it('decimal spreadover -0.0029 -> -29bp', () => {
    expect(ptsInBp(-0.0029, null)).toBeCloseTo(-29, 1)
  })
  it('percent-scaled spreadover -0.422 -> -42.2bp', () => {
    expect(ptsInBp(-0.422, null)).toBeCloseTo(-42.2, 1)
  })
  it('null pts -> null', () => {
    expect(ptsInBp(null, null)).toBeNull()
  })
})

describe('derivedSpreadBp', () => {
  it('curve row -> spread in bp', () => {
    const row = {
      package_type: 'CURVE',
      legs_json: [{ fixed_rate: 0.04029 }, { fixed_rate: 0.04362 }],
    } as any
    expect(derivedSpreadBp(row, 0.00333)).toBeCloseTo(33.3, 1)
  })
  it('outright row -> null', () => {
    const row = { package_type: 'OUTRIGHT', legs_json: [{ fixed_rate: 0.04 }] } as any
    expect(derivedSpreadBp(row, 0.04)).toBeNull()
  })
})

describe('findScaleMatch', () => {
  it('finds a clean 100x factor', () => {
    const m = findScaleMatch(33.3, 0.333)
    expect(m?.factor).toBe(100)
  })
})

describe('formatBp', () => {
  it('formats to 1dp with bps suffix', () => {
    expect(formatBp(33.3)).toBe('33.3bps')
  })
  it('keeps sub-bp precision', () => {
    expect(formatBp(0.2)).toBe('0.2bps')
  })
  it('null -> empty marker', () => {
    expect(formatBp(null)).toBe('—')
  })
})
