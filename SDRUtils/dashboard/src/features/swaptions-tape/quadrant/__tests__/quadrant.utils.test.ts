import {
  tenorLabelToYears,
  classifyQuadrant,
  classifyTradeQuadrant,
  inferTradeDirection,
  signedNotional,
  aggregateQuadrantFlow,
  computeGridFlowState,
  formatCompactNotional,
  formatPremium,
  formatPace,
  quadrantNarrative,
} from '../quadrant.utils';
import { DEFAULT_QUADRANT_CONFIG } from '../quadrant.config';
import type { TapeRow } from '../../types/trade.types';
import type { QuadrantConfig } from '../../types/quadrant.types';

// ---------------------------------------------------------------------------
// tenorLabelToYears
// ---------------------------------------------------------------------------

describe('tenorLabelToYears', () => {
  it('converts year labels', () => {
    expect(tenorLabelToYears('2Y')).toBe(2);
    expect(tenorLabelToYears('10Y')).toBe(10);
    expect(tenorLabelToYears('30Y')).toBe(30);
    expect(tenorLabelToYears('0.5Y')).toBe(0.5);
  });

  it('converts month labels', () => {
    expect(tenorLabelToYears('6M')).toBeCloseTo(0.5, 5);
    expect(tenorLabelToYears('3M')).toBeCloseTo(0.25, 5);
    expect(tenorLabelToYears('12M')).toBeCloseTo(1, 5);
    expect(tenorLabelToYears('18M')).toBeCloseTo(1.5, 5);
  });

  it('converts week labels', () => {
    expect(tenorLabelToYears('1W')).toBeCloseTo(7 / 365, 5);
    expect(tenorLabelToYears('4W')).toBeCloseTo(28 / 365, 5);
  });

  it('converts day labels', () => {
    expect(tenorLabelToYears('1D')).toBeCloseTo(1 / 365, 5);
    expect(tenorLabelToYears('30D')).toBeCloseTo(30 / 365, 5);
  });

  it('handles "spot" as 0', () => {
    expect(tenorLabelToYears('spot')).toBe(0);
    expect(tenorLabelToYears('SPOT')).toBe(0);
    expect(tenorLabelToYears('0D')).toBe(0);
  });

  it('returns null for null/undefined/empty', () => {
    expect(tenorLabelToYears(null)).toBeNull();
    expect(tenorLabelToYears(undefined)).toBeNull();
    expect(tenorLabelToYears('')).toBeNull();
  });

  it('returns null for unparseable labels', () => {
    expect(tenorLabelToYears('IMM_Z2025')).toBeNull();
    expect(tenorLabelToYears('FOMC_20250115')).toBeNull();
    expect(tenorLabelToYears('abc')).toBeNull();
  });

  it('is case-insensitive', () => {
    expect(tenorLabelToYears('5y')).toBe(5);
    expect(tenorLabelToYears('6m')).toBeCloseTo(0.5, 5);
  });
});

// ---------------------------------------------------------------------------
// classifyQuadrant
// ---------------------------------------------------------------------------

describe('classifyQuadrant', () => {
  const config: QuadrantConfig = {
    expiryBoundaryYears: 1.5,
    tenorBoundaryYears: 7.5,
    boundaryToleranceYears: 0.5,
  };

  it('classifies ULC: short expiry + short tenor', () => {
    // 3M expiry, 2Y tenor
    const result = classifyQuadrant('3M', '2Y', config);
    expect(result.quadrant).toBe('ULC');
    expect(result.expiryYears).toBeCloseTo(0.25, 5);
    expect(result.tenorYears).toBe(2);
  });

  it('classifies URC: short expiry + long tenor', () => {
    // 3M expiry, 10Y tenor
    const result = classifyQuadrant('3M', '10Y', config);
    expect(result.quadrant).toBe('URC');
  });

  it('classifies LLC: long expiry + short tenor', () => {
    // 5Y expiry, 2Y tenor
    const result = classifyQuadrant('5Y', '2Y', config);
    expect(result.quadrant).toBe('LLC');
  });

  it('classifies LRC: long expiry + long tenor', () => {
    // 5Y expiry, 10Y tenor
    const result = classifyQuadrant('5Y', '10Y', config);
    expect(result.quadrant).toBe('LRC');
  });

  it('classifies spot expiry as short expiry (ULC/URC)', () => {
    expect(classifyQuadrant('spot', '5Y', config).quadrant).toBe('ULC');
    expect(classifyQuadrant('spot', '10Y', config).quadrant).toBe('URC');
  });

  it('tags boundary trades near expiry boundary', () => {
    // 1Y expiry = 1.0 years, boundary is 1.5 with tolerance 0.5 → within range [1.0, 2.0]
    const result = classifyQuadrant('1Y', '5Y', config);
    expect(result.quadrant).toBe('BOUNDARY');
    expect(result.adjacentQuadrants).toBeDefined();
  });

  it('tags boundary trades near tenor boundary', () => {
    // 3M expiry, 7Y tenor = 7.0 years, boundary is 7.5 with tolerance 0.5 → within range [7.0, 8.0]
    const result = classifyQuadrant('3M', '7Y', config);
    expect(result.quadrant).toBe('BOUNDARY');
  });

  it('identifies adjacent quadrants for expiry boundary', () => {
    // 1Y expiry, 2Y tenor → near expiry boundary, short tenor
    const result = classifyQuadrant('1Y', '2Y', config);
    expect(result.quadrant).toBe('BOUNDARY');
    expect(result.adjacentQuadrants).toContain('ULC');
    expect(result.adjacentQuadrants).toContain('LLC');
  });

  it('identifies adjacent quadrants for tenor boundary', () => {
    // 3M expiry, 8Y tenor → near tenor boundary, short expiry
    const result = classifyQuadrant('3M', '8Y', config);
    expect(result.quadrant).toBe('BOUNDARY');
    expect(result.adjacentQuadrants).toContain('ULC');
    expect(result.adjacentQuadrants).toContain('URC');
  });

  it('returns BOUNDARY for null expiry/tenor', () => {
    expect(classifyQuadrant(null, '10Y', config).quadrant).toBe('BOUNDARY');
    expect(classifyQuadrant('3M', null, config).quadrant).toBe('BOUNDARY');
    expect(classifyQuadrant(null, null, config).quadrant).toBe('BOUNDARY');
  });

  it('returns BOUNDARY for unparseable labels (IMM/FOMC)', () => {
    expect(classifyQuadrant('IMM_Z2025', '10Y', config).quadrant).toBe('BOUNDARY');
    expect(classifyQuadrant('FOMC_20250115', '2Y', config).quadrant).toBe('BOUNDARY');
  });

  it('works with default config', () => {
    const result = classifyQuadrant('3M', '10Y');
    expect(result.quadrant).toBe('URC');
  });

  // Real-world vol grid points
  it('classifies common vol grid points correctly', () => {
    // 1Mx2Y → ULC (gamma + short tails)
    expect(classifyQuadrant('1M', '2Y', config).quadrant).toBe('ULC');
    // 3Mx10Y → URC (gamma + long tails) — the benchmark
    expect(classifyQuadrant('3M', '10Y', config).quadrant).toBe('URC');
    // 5Yx5Y → LLC (vega + short tails)
    expect(classifyQuadrant('5Y', '5Y', config).quadrant).toBe('LLC');
    // 10Yx30Y → LRC (vega + long tails)
    expect(classifyQuadrant('10Y', '30Y', config).quadrant).toBe('LRC');
  });
});

// ---------------------------------------------------------------------------
// inferTradeDirection
// ---------------------------------------------------------------------------

const makeRow = (overrides: Partial<TapeRow> = {}): TapeRow => ({
  package_id: 'test-pkg-1',
  package_type: 'STRADDLE',
  as_of_date: '2026-01-06',
  execution_start: '2026-01-06T16:00:00Z',
  execution_end: '2026-01-06T16:00:00Z',
  expiration_date: null,
  underlying_expiration_date: null,
  tenor_label: '10Y',
  forward_label: '3M',
  legs_count: 2,
  total_notional: 100000000,
  total_premium: 500000,
  package_indicator: true,
  package_transaction_price: null,
  package_confidence: null,
  package_reason: null,
  package_metrics: null,
  legs_json: [],
  ...overrides,
});

describe('inferTradeDirection', () => {
  it('returns "payer" for payer-dominated trade', () => {
    const row = makeRow({
      legs_json: [
        { product_type: 'SWAPTION_PAYER', notional: 100000000 },
      ],
    });
    expect(inferTradeDirection(row)).toBe('payer');
  });

  it('returns "receiver" for receiver-dominated trade', () => {
    const row = makeRow({
      legs_json: [
        { product_type: 'SWAPTION_RECEIVER', notional: 100000000 },
      ],
    });
    expect(inferTradeDirection(row)).toBe('receiver');
  });

  it('returns "balanced" for straddle (equal payer+receiver)', () => {
    const row = makeRow({
      legs_json: [
        { product_type: 'SWAPTION_PAYER', notional: 100000000 },
        { product_type: 'SWAPTION_RECEIVER', notional: 100000000 },
      ],
    });
    expect(inferTradeDirection(row)).toBe('balanced');
  });

  it('returns "balanced" for empty legs', () => {
    const row = makeRow({ legs_json: [] });
    expect(inferTradeDirection(row)).toBe('balanced');
  });
});

// ---------------------------------------------------------------------------
// signedNotional
// ---------------------------------------------------------------------------

describe('signedNotional', () => {
  it('returns positive for payer', () => {
    const row = makeRow({
      total_notional: 100000000,
      legs_json: [{ product_type: 'SWAPTION_PAYER', notional: 100000000 }],
    });
    expect(signedNotional(row)).toBe(100000000);
  });

  it('returns negative for receiver', () => {
    const row = makeRow({
      total_notional: 100000000,
      legs_json: [{ product_type: 'SWAPTION_RECEIVER', notional: 100000000 }],
    });
    expect(signedNotional(row)).toBe(-100000000);
  });

  it('returns 0 for balanced', () => {
    const row = makeRow({
      total_notional: 200000000,
      legs_json: [
        { product_type: 'SWAPTION_PAYER', notional: 100000000 },
        { product_type: 'SWAPTION_RECEIVER', notional: 100000000 },
      ],
    });
    expect(signedNotional(row)).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// aggregateQuadrantFlow
// ---------------------------------------------------------------------------

describe('aggregateQuadrantFlow', () => {
  it('returns empty snapshot for no trades', () => {
    const snap = aggregateQuadrantFlow('URC', []);
    expect(snap.tradeCount).toBe(0);
    expect(snap.grossNotional).toBe(0);
    expect(snap.netNotional).toBe(0);
    expect(snap.dominantDirection).toBe('balanced');
  });

  it('aggregates multiple payer trades', () => {
    const trades = [
      makeRow({ total_notional: 100e6, legs_json: [{ product_type: 'SWAPTION_PAYER', notional: 100e6 }] }),
      makeRow({ package_id: 'p2', total_notional: 50e6, legs_json: [{ product_type: 'SWAPTION_PAYER', notional: 50e6 }] }),
    ];
    const snap = aggregateQuadrantFlow('URC', trades);
    expect(snap.tradeCount).toBe(2);
    expect(snap.grossNotional).toBe(150e6);
    expect(snap.netNotional).toBe(150e6);
    expect(snap.dominantDirection).toBe('payer');
  });

  it('computes net correctly for mixed flow', () => {
    const trades = [
      makeRow({ total_notional: 100e6, legs_json: [{ product_type: 'SWAPTION_PAYER', notional: 100e6 }] }),
      makeRow({ package_id: 'p2', total_notional: 200e6, legs_json: [{ product_type: 'SWAPTION_RECEIVER', notional: 200e6 }] }),
    ];
    const snap = aggregateQuadrantFlow('URC', trades);
    expect(snap.tradeCount).toBe(2);
    expect(snap.grossNotional).toBe(300e6);
    expect(snap.netNotional).toBe(-100e6); // net receiver
    expect(snap.dominantDirection).toBe('receiver');
  });
});

// ---------------------------------------------------------------------------
// computeGridFlowState
// ---------------------------------------------------------------------------

describe('computeGridFlowState', () => {
  it('distributes trades to correct quadrants', () => {
    const trades = [
      makeRow({ forward_label: '3M', tenor_label: '2Y' }), // ULC
      makeRow({ package_id: 'p2', forward_label: '3M', tenor_label: '10Y' }), // URC
      makeRow({ package_id: 'p3', forward_label: '5Y', tenor_label: '2Y' }), // LLC
      makeRow({ package_id: 'p4', forward_label: '5Y', tenor_label: '10Y' }), // LRC
    ];
    const state = computeGridFlowState(trades);
    expect(state.ulc.tradeCount).toBe(1);
    expect(state.urc.tradeCount).toBe(1);
    expect(state.llc.tradeCount).toBe(1);
    expect(state.lrc.tradeCount).toBe(1);
  });

  it('generates a dominantTheme string', () => {
    const trades = [
      makeRow({ forward_label: '3M', tenor_label: '10Y' }),
    ];
    const state = computeGridFlowState(trades);
    expect(typeof state.dominantTheme).toBe('string');
    expect(state.dominantTheme.length).toBeGreaterThan(0);
  });

  it('returns empty state for no trades', () => {
    const state = computeGridFlowState([]);
    expect(state.ulc.tradeCount).toBe(0);
    expect(state.urc.tradeCount).toBe(0);
    expect(state.llc.tradeCount).toBe(0);
    expect(state.lrc.tradeCount).toBe(0);
    expect(state.dominantTheme).toContain('No significant flow');
  });
});

// ---------------------------------------------------------------------------
// Formatting helpers
// ---------------------------------------------------------------------------

describe('formatCompactNotional', () => {
  it('formats billions', () => {
    expect(formatCompactNotional(2.4e9)).toBe('+2.4bn');
    expect(formatCompactNotional(-1.5e9)).toBe('-1.5bn');
  });

  it('formats millions', () => {
    expect(formatCompactNotional(340e6)).toBe('+340mm');
    expect(formatCompactNotional(-80e6)).toBe('-80mm');
  });

  it('formats thousands', () => {
    expect(formatCompactNotional(50000)).toBe('+50k');
  });

  it('formats small values', () => {
    expect(formatCompactNotional(500)).toBe('+500');
    expect(formatCompactNotional(0)).toBe('+0');
  });
});

describe('formatPremium', () => {
  it('formats millions', () => {
    expect(formatPremium(34100000)).toBe('34.1m');
  });

  it('formats thousands', () => {
    expect(formatPremium(8200)).toBe('8k');
  });
});

describe('formatPace', () => {
  it('formats pace multiplier', () => {
    expect(formatPace(1.4)).toBe('1.4x');
    expect(formatPace(0.5)).toBe('0.5x');
  });

  it('returns dash for near-zero', () => {
    expect(formatPace(0.001)).toBe('\u2014');
  });
});

describe('quadrantNarrative', () => {
  it('returns "quiet" for empty snapshot', () => {
    const snap = aggregateQuadrantFlow('URC', []);
    expect(quadrantNarrative(snap)).toBe('quiet');
  });
});
