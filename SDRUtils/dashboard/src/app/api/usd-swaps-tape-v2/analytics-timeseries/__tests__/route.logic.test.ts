import { describe, expect, it } from '@jest/globals'
import {
  buildOutrightTapeLabelCandidates,
  custyNotionalOutlierPredicate,
  isOutrightTapeLabelCandidate,
  parseBooleanParam,
  riskAggregateExpression,
} from '../route.logic'

describe('analytics-timeseries route options', () => {
  it('defaults to net DV01 and clean custy-notional outlier mode', () => {
    const params = new URLSearchParams()

    expect(parseBooleanParam(params, 'useGrossDv01', false)).toBe(false)
    expect(parseBooleanParam(params, 'excludeLargeCusty', true)).toBe(true)
  })

  it('switches the daily risk aggregate between net and gross', () => {
    expect(riskAggregateExpression(false)).toBe('SUM(risk)')
    expect(riskAggregateExpression(true)).toBe('SUM(ABS(risk))')
  })

  it('emits a custy notional median guard only when outlier exclusion is enabled', () => {
    expect(custyNotionalOutlierPredicate('b', 't', false)).toBe('TRUE')

    const predicate = custyNotionalOutlierPredicate('b', 't', true)
    expect(predicate).toContain("b.platform = 'CUSTY'")
    expect(predicate).toContain('t.median_notional * 5')
  })

  it('identifies plain outright tape labels for the package-table fast path', () => {
    expect(
      isOutrightTapeLabelCandidate(
        'USD-SOFR-COMPOUND 1D Constant Spot 10Y Outright PHYS',
      ),
    ).toBe(true)
    expect(
      isOutrightTapeLabelCandidate(
        'USD-SOFR-OIS Compound IMM_M2026 3Y/10Y/30Y FLY PHYS',
      ),
    ).toBe(false)
    expect(
      isOutrightTapeLabelCandidate(
        'USD-SOFR-COMPOUND 2M IMM_H2028 Outright MMS PHYS',
      ),
    ).toBe(false)
  })

  it('builds case-normalized outright candidates including lifecycle-stripped SOFR variants', () => {
    const candidates = buildOutrightTapeLabelCandidates(
      'USD-SOFR-COMPOUND 1D Constant Spot 4Y Outright UNWIND UFRO PHYS',
    )
    expect(candidates).toContain(
      'USD-SOFR-COMPOUND 1D CONSTANT SPOT 4Y OUTRIGHT UNWIND UFRO PHYS',
    )
    expect(candidates).toContain(
      'USD-SOFR-OIS COMPOUND 1D CONSTANT SPOT 4Y OUTRIGHT UFRO PHYS',
    )
    expect(candidates).toContain(
      'USD-SOFR-COMPOUND 1D CONSTANT SPOT 4Y OUTRIGHT UFRO PHYS',
    )
  })
})
