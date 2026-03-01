import { describe, expect, it } from '@jest/globals';
import type { TapeRow } from '../../../types/trade.types';
import {
  buildNotionalProfileLabel,
  computeDerivedMetrics,
  computeHistogram,
  computeRank,
  distributionStats,
  findLastSimilarByStructure,
  getMetricValueByKey,
  isSimilarTrade,
  percentileRank,
  splitRowsByPlatform,
  zScore,
} from '../rarity.utils';

const makeRow = (overrides: Partial<TapeRow>): TapeRow => ({
  package_id: 'pkg-1',
  package_type: 'STRADDLE',
  as_of_date: null,
  execution_start: '2026-01-31T12:00:00Z',
  execution_end: '2026-01-31T12:00:00Z',
  expiration_date: null,
  underlying_expiration_date: null,
  tenor_label: '1Y',
  forward_label: '2Y',
  legs_count: 1,
  total_notional: 100_000_000,
  total_premium: 1_000_000,
  package_indicator: null,
  package_transaction_price: null,
  package_confidence: null,
  package_reason: null,
  package_metrics: {},
  legs_json: [],
  ...overrides,
});

describe('rarity.utils', () => {
  it('computes percentile rank with interpolation', () => {
    const values = [1, 2, 3, 4, 5];
    const pct = percentileRank(3, values);
    expect(pct).toBeCloseTo(50, 0);
    expect(percentileRank(1, values)).toBe(0);
    expect(percentileRank(5, values)).toBe(100);
  });

  it('computes histogram bins and counts', () => {
    const result = computeHistogram([1, 2, 3, 4], 2);
    expect(result.totalCount).toBe(4);
    expect(result.bins.length).toBe(2);
    expect(result.bins[0].count + result.bins[1].count).toBe(4);
  });

  it('collapses flat distributions into a single non-empty bin', () => {
    const result = computeHistogram([7, 7, 7], 20);
    expect(result.totalCount).toBe(3);
    expect(result.bins.length).toBe(1);
    expect(result.bins[0].count).toBe(3);
    expect(result.bins[0].cumulativePercent).toBe(100);
  });

  it('ignores non-finite values while preserving split counts', () => {
    const result = computeHistogram([1, Number.POSITIVE_INFINITY, 2], 2, [true, false, false]);
    expect(result.totalCount).toBe(2);
    expect(result.bins.reduce((sum, bin) => sum + bin.custyCount, 0)).toBe(1);
    expect(result.bins.reduce((sum, bin) => sum + bin.idbCount, 0)).toBe(1);
  });

  it('clips extreme tails for large samples while preserving counts', () => {
    const values = [...Array.from({ length: 100 }, (_, index) => index + 1), 1_000_000];
    const result = computeHistogram(values, 20);
    expect(result.totalCount).toBe(101);
    expect(result.bins.reduce((sum, bin) => sum + bin.count, 0)).toBe(101);
    expect(result.bins[result.bins.length - 1].binEnd).toBeLessThan(1_000_000);
  });

  it('computes distribution stats', () => {
    const stats = distributionStats([1, 2, 3, 4]);
    expect(stats.count).toBe(4);
    expect(stats.mean).toBeCloseTo(2.5, 5);
    expect(stats.median).toBeCloseTo(2.5, 5);
  });

  it('computes rank descending by default', () => {
    const rank = computeRank(5, [10, 5, 1]);
    expect(rank.rank).toBe(2);
    expect(rank.total).toBe(3);
  });

  it('computes z-score safely', () => {
    expect(zScore(3, 2, 1)).toBeCloseTo(1, 5);
    expect(zScore(3, 2, 0)).toBe(0);
  });

  it('computes derived metrics for straddles', () => {
    const row = makeRow({
      package_metrics: {
        straddle_vega01: 2000,
        straddle_theta1d: -100,
      },
    });
    const derived = computeDerivedMetrics(row);
    expect(derived.breakeven_width_bps).toBeCloseTo(100, 5);
    expect(derived.theta_vega_ratio).toBeCloseTo(-0.05, 5);
  });

  it('computes notional profile label for ladders', () => {
    const row = makeRow({
      package_type: 'RECEIVER_LADDER',
      package_metrics: {
        ladder_notionals: [100, 200, 200],
      },
    });
    expect(buildNotionalProfileLabel(row)).toBe('1:2:2');
  });

  it('detects similar trades by criteria', () => {
    const current = makeRow({
      package_type: 'VERTICAL_SPREAD_1X1',
      package_metrics: {
        vs_strike_width_bps: 50,
        vs_spread_type: 'PAYER',
      },
    });
    const candidate = makeRow({
      package_id: 'pkg-2',
      execution_start: '2026-01-20T12:00:00Z',
      package_type: 'VERTICAL_SPREAD_1X1',
      package_metrics: {
        vs_strike_width_bps: 60,
        vs_spread_type: 'PAYER',
      },
    });
    expect(
      isSimilarTrade(current, candidate, {
        metric: 'vs_strike_width_bps',
        mode: 'absolute_range',
        threshold: 25,
        requireDirection: true,
      }),
    ).toBe(true);
  });

  it('finds last similar trade', () => {
    const current = makeRow({
      package_type: 'RISK_REVERSAL',
      package_metrics: { rr_skew_bpvol: 5 },
    });
    const candidate = makeRow({
      package_id: 'pkg-2',
      execution_start: '2026-01-20T12:00:00Z',
      package_type: 'RISK_REVERSAL',
      package_metrics: { rr_skew_bpvol: 6 },
    });
    const result = findLastSimilarByStructure(current, [candidate], {
      metric: 'rr_skew_bpvol',
      mode: 'absolute_range',
      threshold: 2,
    });
    expect(result?.tradeId).toBe('pkg-2');
    expect(result?.value).toBe(6);
  });

  it('extracts metric values by key', () => {
    const row = makeRow({
      package_metrics: {
        rr_skew_bpvol: 4.2,
      },
    });
    expect(getMetricValueByKey(row, 'rr_skew_bpvol')).toBeCloseTo(4.2, 5);
  });

  it('falls back straddle vega to inferred outright leg metrics', () => {
    const row = makeRow({
      package_type: 'STRADDLE',
      package_metrics: {},
      assumed_incomplete_straddle: true as any,
      legs_json: [
        {
          leg_metrics: {
            outright_vega01: 16378,
          },
        } as any,
      ],
    });
    expect(getMetricValueByKey(row, 'straddle_vega01')).toBeCloseTo(32756, 5);
  });

  it('splits combined rows using package_metrics platform fallback', () => {
    const idbRow = makeRow({
      package_id: 'idb-1',
      package_metrics: { platform: 'BGCD' },
      platform_identifier: null,
      legs_json: [],
    });
    const custyRow = makeRow({
      package_id: 'custy-1',
      package_metrics: { platform: 'XOFF' },
      platform_identifier: null,
      legs_json: [],
    });
    const split = splitRowsByPlatform([idbRow, custyRow]);
    expect(split.idb.map((row) => row.package_id)).toEqual(['idb-1']);
    expect(split.custy.map((row) => row.package_id)).toEqual(['custy-1']);
  });

  it('treats mixed platform tokens as IDB when an IDB MIC is present', () => {
    const mixedRow = makeRow({
      package_id: 'mixed-1',
      platform_identifier: 'BGCD XOFF',
      package_metrics: {},
    });
    const split = splitRowsByPlatform([mixedRow]);
    expect(split.idb.map((row) => row.package_id)).toEqual(['mixed-1']);
    expect(split.custy).toHaveLength(0);
  });
});

