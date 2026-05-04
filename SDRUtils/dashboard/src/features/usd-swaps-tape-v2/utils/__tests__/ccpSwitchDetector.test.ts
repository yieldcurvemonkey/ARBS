import { describe, expect, it } from '@jest/globals'
import {
  detectCcpSwitch,
  summarizeCcpSwitchActivity,
} from '../ccpSwitchDetector'
import type { UsdSwapTapeRow } from '../../types'

const leg = (
  ccp: string | null,
  risk: number,
  tenor: number = 5,
  currency: string = 'USD',
) =>
  ({
    ccp,
    risk,
    tenor_years: tenor,
  } as any)

const rowWith = (
  legs: Array<ReturnType<typeof leg>>,
  extras: Partial<UsdSwapTapeRow> = {},
): UsdSwapTapeRow =>
  ({
    package_id: 'P1',
    package_type: 'CURVE',
    legs_count: legs.length,
    ccp: extras.ccp ?? null,
    legs_json: legs as any,
    execution_start: extras.execution_start ?? '2026-05-04T15:00:00Z',
    ...extras,
  } as any)

describe('detectCcpSwitch', () => {
  it('detects an LCH ↔ CME switch with opposite-sign DV01', () => {
    const row = rowWith([
      leg('LCH', 10_000, 5),
      leg('CME', -10_000, 5),
    ])
    const out = detectCcpSwitch(row)
    expect(out.isCcpSwitch).toBe(true)
    expect(out.fromCcp).toBe('LCH')
    expect(out.toCcp).toBe('CME')
  })

  it('detects an CME ↔ LCH switch (sign-asymmetric)', () => {
    const row = rowWith([
      leg('CME', 5_000, 10),
      leg('LCH', -5_000, 10),
    ])
    const out = detectCcpSwitch(row)
    expect(out.isCcpSwitch).toBe(true)
    expect(out.fromCcp).toBe('CME')
    expect(out.toCcp).toBe('LCH')
  })

  it('rejects same-CCP packages', () => {
    expect(
      detectCcpSwitch(
        rowWith([leg('LCH', 10_000, 5), leg('LCH', -10_000, 5)]),
      ).isCcpSwitch,
    ).toBe(false)
  })

  it('rejects packages with mismatched tenors (not a CCP switch by Clarus rule)', () => {
    expect(
      detectCcpSwitch(
        rowWith([leg('LCH', 10_000, 5), leg('CME', -10_000, 10)]),
      ).isCcpSwitch,
    ).toBe(false)
  })

  it('rejects packages without two opposite-sign legs', () => {
    expect(
      detectCcpSwitch(
        rowWith([leg('LCH', 10_000, 5), leg('CME', 5_000, 5)]),
      ).isCcpSwitch,
    ).toBe(false)
  })

  it('rejects single-leg packages', () => {
    expect(detectCcpSwitch(rowWith([leg('LCH', 10_000, 5)])).isCcpSwitch).toBe(
      false,
    )
  })

  it('rejects when neither leg has a CCP tag', () => {
    expect(
      detectCcpSwitch(
        rowWith([leg(null, 10_000, 5), leg(null, -10_000, 5)]),
      ).isCcpSwitch,
    ).toBe(false)
  })

  it('rejects when only one leg has a CCP tag', () => {
    expect(
      detectCcpSwitch(
        rowWith([leg('LCH', 10_000, 5), leg(null, -10_000, 5)]),
      ).isCcpSwitch,
    ).toBe(false)
  })

  it('rejects unsupported CCP combinations (e.g. JSCC vs LCH for USD)', () => {
    expect(
      detectCcpSwitch(
        rowWith([leg('LCH', 10_000, 5), leg('JSCC', -10_000, 5)]),
      ).isCcpSwitch,
    ).toBe(false)
  })
})

describe('summarizeCcpSwitchActivity', () => {
  const switchRow = (date: string, risk: number, dir: 'LCH→CME' | 'CME→LCH') => {
    const a = dir === 'LCH→CME' ? 'LCH' : 'CME'
    const b = dir === 'LCH→CME' ? 'CME' : 'LCH'
    return rowWith(
      [leg(a, risk, 5), leg(b, -risk, 5)],
      { execution_start: date },
    )
  }

  it('aggregates by day with directional flow', () => {
    const rows: UsdSwapTapeRow[] = [
      switchRow('2026-05-01T10:00:00Z', 10_000, 'LCH→CME'),
      switchRow('2026-05-01T15:00:00Z', 5_000, 'CME→LCH'),
      switchRow('2026-05-02T10:00:00Z', 7_500, 'LCH→CME'),
      // not a switch — should be ignored
      rowWith([leg('LCH', 10_000, 5), leg('LCH', -10_000, 5)], {
        execution_start: '2026-05-01T13:00:00Z',
      }),
    ]
    const out = summarizeCcpSwitchActivity(rows)
    expect(out).toHaveLength(2)
    expect(out[0].day).toBe('2026-05-01')
    expect(out[0].switchCount).toBe(2)
    expect(out[0].dv01).toBe(15_000)
    expect(out[0].lchToCmeDv01).toBe(10_000)
    expect(out[0].cmeToLchDv01).toBe(5_000)
  })

  it('breaks down by tenor', () => {
    const rows: UsdSwapTapeRow[] = [
      rowWith(
        [leg('LCH', 10_000, 5), leg('CME', -10_000, 5)],
        { execution_start: '2026-05-01T10:00:00Z' },
      ),
      rowWith(
        [leg('LCH', 10_000, 10), leg('CME', -10_000, 10)],
        { execution_start: '2026-05-01T11:00:00Z' },
      ),
    ]
    const out = summarizeCcpSwitchActivity(rows)
    expect(out[0].byTenor).toEqual({ '5': 10_000, '10': 10_000 })
  })

  it('returns empty array for no switches', () => {
    expect(summarizeCcpSwitchActivity([])).toEqual([])
  })
})
