import { describe, expect, it, jest, beforeEach } from '@jest/globals'

const queryMock = jest.fn<(sql: string, params?: unknown[]) => Promise<{ rows: unknown[] }>>(
  async () => ({ rows: [] as unknown[] }),
)
jest.unstable_mockModule('@/lib/db', () => ({ query: queryMock, withClient: jest.fn() }))

const mod = await import('../tape-overrides')
const {
  normalizeIdList,
  normalizeText,
  normalizeTags,
  generateManualPackageId,
  validateOverride,
  computeOverrideMetrics,
  buildMemberRows,
  resolveManualPackageId,
} = mod

beforeEach(() => {
  queryMock.mockReset()
  queryMock.mockResolvedValue({ rows: [] })
})

describe('normalizeIdList', () => {
  it('splits, trims, dedupes, drops blanks', () => {
    expect(normalizeIdList('a, b ,a\n c')).toEqual(['a', 'b', 'c'])
    expect(normalizeIdList(['x', 'x', ' y '])).toEqual(['x', 'y'])
    expect(normalizeIdList(undefined)).toEqual([])
  })
})

describe('validateOverride', () => {
  it('GROUP requires >= 2 trades', () => {
    const one = validateOverride('GROUP', ['T1'])
    expect(one.hasErrors).toBe(true)
    expect(one.validation[0]).toMatchObject({ level: 'error', code: 'GROUP_MIN_TRADES' })
    const two = validateOverride('GROUP', ['T1', 'T2'])
    expect(two.hasErrors).toBe(false)
    expect(two.validation.some((v) => v.level === 'info')).toBe(true)
  })
  it('SPLIT/DETACH allow >= 1 trade', () => {
    expect(validateOverride('SPLIT', ['T1']).hasErrors).toBe(false)
    expect(validateOverride('DETACH', ['T1']).hasErrors).toBe(false)
    expect(validateOverride('SPLIT', []).hasErrors).toBe(true)
  })
})

describe('computeOverrideMetrics', () => {
  it('counts trades and distinct source packages', () => {
    const m = computeOverrideMetrics('GROUP', ['T1', 'T2', 'T3'], [
      { trade_id: 'T1', package_id: 'P1' },
      { trade_id: 'T2', package_id: 'P1' },
      { trade_id: 'T3', package_id: 'P2' },
    ])
    expect(m.trade_count).toBe(3)
    expect(m.override_type).toBe('GROUP')
    expect(m.distinct_package_ids).toBe(2)
    expect(m.source_package_ids.sort()).toEqual(['P1', 'P2'])
  })
})

describe('generateManualPackageId', () => {
  it('matches SMO-YYYYMMDD-<8 upper hex>', () => {
    expect(generateManualPackageId()).toMatch(/^SMO-\d{8}-[0-9A-F]{8}$/)
  })
})

describe('resolveManualPackageId', () => {
  it('returns provided id verbatim regardless of type', () => {
    expect(resolveManualPackageId('SPLIT', 'SMO-20260708-AAAA1111')).toBe('SMO-20260708-AAAA1111')
  })
  it('null for SPLIT/DETACH when none provided', () => {
    expect(resolveManualPackageId('SPLIT', null)).toBeNull()
    expect(resolveManualPackageId('DETACH', null)).toBeNull()
  })
  it('signals generation for GROUP when none provided', () => {
    expect(resolveManualPackageId('GROUP', null)).toBe('__GENERATE__')
  })
})

describe('buildMemberRows', () => {
  it('one row per trade carrying override metadata', () => {
    const rows = buildMemberRows('OID', 'GROUP', 'SMO-20260708-AAAA1111', ['T1', 'T2'])
    expect(rows).toEqual([
      { trade_id: 'T1', override_id: 'OID', override_type: 'GROUP', manual_package_id: 'SMO-20260708-AAAA1111' },
      { trade_id: 'T2', override_id: 'OID', override_type: 'GROUP', manual_package_id: 'SMO-20260708-AAAA1111' },
    ])
  })
})

describe('resolveOverrideLegs (db)', () => {
  it('reads trade_id/package_id from the tape legs table', async () => {
    queryMock.mockResolvedValueOnce({ rows: [{ trade_id: 'T1', package_id: 'P1' }] })
    const legs = await mod.resolveOverrideLegs(['T1'])
    expect(legs).toEqual([{ trade_id: 'T1', package_id: 'P1' }])
    expect(queryMock).toHaveBeenCalledTimes(1)
    expect(String(queryMock.mock.calls[0][0])).toContain('arbs_usd_swap_tape_legs_v2')
  })
  it('short-circuits on empty input', async () => {
    expect(await mod.resolveOverrideLegs([])).toEqual([])
    expect(queryMock).not.toHaveBeenCalled()
  })
})

describe('findOverlappingActiveOverrideIds (db)', () => {
  it('excludes the given override id and returns ids', async () => {
    queryMock.mockResolvedValueOnce({ rows: [{ override_id: 'OLD1' }, { override_id: 'OLD2' }] })
    const ids = await mod.findOverlappingActiveOverrideIds(['T1', 'T2'], 'NEW')
    expect(ids).toEqual(['OLD1', 'OLD2'])
    const [sql, params] = queryMock.mock.calls[0]
    expect(String(sql)).toContain('trade_ids && $1')
    expect(String(sql)).toContain('override_id <> $2')
    expect(params).toEqual([['T1', 'T2'], 'NEW'])
  })
})
