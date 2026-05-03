import { describe, expect, it } from '@jest/globals'
import {
  custyNotionalOutlierPredicate,
  parseBooleanParam,
  riskAggregateExpression,
} from '../route'

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
})
