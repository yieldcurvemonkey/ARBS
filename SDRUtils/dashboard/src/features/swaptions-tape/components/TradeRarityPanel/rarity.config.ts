import type { MetricConfig, StructureAnalyticsConfig } from './rarity.types';
import type { TapeRow } from '../../types/trade.types';

const metric = (
  key: string,
  label: string,
  unit: string | undefined,
  options: Partial<MetricConfig> = {},
): MetricConfig => ({
  key,
  label,
  unit,
  showFor: [],
  ...options,
});

const derivedMetric = (
  key: string,
  label: string,
  unit: string | undefined,
  options: Partial<MetricConfig> = {},
): MetricConfig => ({
  key,
  label,
  unit,
  derived: true,
  showFor: [],
  ...options,
});

const ladderWidthDerived = (row: TapeRow): number | null => {
  const metrics = row.package_metrics || {};
  const strikes = Array.isArray(metrics.ladder_strikes)
    ? metrics.ladder_strikes
    : (row.legs_json || []).map((leg) => leg.strike).filter((v) => v != null);
  if (!strikes || strikes.length < 2) return null;
  const numeric = strikes
    .map((strike: any) => (strike == null ? null : Number(strike)))
    .filter((value: any): value is number => Number.isFinite(value));
  if (numeric.length < 2) return null;
  const max = Math.max(...numeric);
  const min = Math.min(...numeric);
  return (max - min) * 10000;
};

const STRUCTURE_ANALYTICS_CONFIG: Record<string, StructureAnalyticsConfig> = {
  STRADDLE: {
    packageType: 'STRADDLE',
    primaryMetric: metric('straddle_bpvol_yr', 'BPVol/Yr', 'bpvol/yr', {
      primary: true,
      decimals: 3,
      formatKind: 'metric',
    }),
    secondaryMetrics: [
      metric('total_notional', 'Notional', 'USD', {
        formatKind: 'notional',
        absolute: true,
      }),
      metric('total_premium', 'Premium', 'USD', {
        formatKind: 'premium',
        absolute: true,
      }),
      metric('straddle_vega01', 'Vega01', 'USD/bp', {
        decimals: 2,
        formatKind: 'metric',
        absolute: true,
      }),
      derivedMetric('breakeven_width_bps', 'Breakeven', 'bps', {
        decimals: 2,
        formatKind: 'bps',
        formula: 'total_premium / total_notional * 10000',
      }),
      derivedMetric('theta_vega_ratio', 'Theta/Vega', 'ratio', {
        decimals: 3,
        formatKind: 'ratio',
        formula: 'straddle_theta1d / straddle_vega01',
      }),
      derivedMetric('fwd_premium_ratio', 'Fwd Premium Ratio', 'ratio', {
        decimals: 3,
        formatKind: 'ratio',
        formula: 'straddle_fwd_premium / total_premium',
      }),
      derivedMetric('vega_per_notional', 'Vega/Notional', 'per USD', {
        decimals: 4,
        formatKind: 'ratio',
        formula: 'straddle_vega01 / total_notional',
      }),
      metric('straddle_dv01', 'DV01', 'USD/bp', {
        decimals: 2,
        formatKind: 'metric',
        absolute: true,
      }),
      derivedMetric('premium_bps', 'Premium (bps)', 'bps', {
        decimals: 2,
        formatKind: 'bps',
        formula: 'total_premium / total_notional * 10000',
      }),
    ],
    similarityCriteria: {
      metric: 'straddle_bpvol_yr',
      mode: 'absolute_range',
      threshold: 5,
    },
    histogramDefault: 'straddle_bpvol_yr',
    histogramOverlay: 'breakeven',
  },
  RISK_REVERSAL: {
    packageType: 'RISK_REVERSAL',
    primaryMetric: metric('rr_skew_bpvol', 'Skew', 'bpvol', {
      primary: true,
      decimals: 2,
      formatKind: 'metric',
    }),
    secondaryMetrics: [
      derivedMetric('skew_atm_ratio', 'Skew/ATM', 'ratio', {
        decimals: 3,
        formatKind: 'ratio',
        formula: 'rr_skew_bpvol / rr_atm_bpvol',
      }),
      metric('rr_wing_dv01', 'Wing DV01', 'USD/bp', {
        decimals: 2,
        formatKind: 'metric',
        absolute: true,
      }),
      derivedMetric('net_dv01_vega_ratio', 'DV01/Vega', 'ratio', {
        decimals: 3,
        formatKind: 'ratio',
        formula: 'rr_dv01 / rr_vega01',
      }),
      derivedMetric('wing_distance_bps', 'Wing Distance', 'bps', {
        decimals: 1,
        formatKind: 'bps',
        formula: 'rr_out_strike - rr_atmf',
      }),
      metric('total_notional', 'Notional', 'USD', {
        formatKind: 'notional',
        absolute: true,
      }),
      metric('total_premium', 'Premium', 'USD', {
        formatKind: 'premium',
        absolute: true,
      }),
      metric('rr_vega01', 'Vega01', 'USD/bp', {
        decimals: 2,
        formatKind: 'metric',
        absolute: true,
      }),
    ],
    similarityCriteria: {
      metric: 'rr_skew_bpvol',
      mode: 'absolute_range',
      threshold: 2,
    },
    histogramDefault: 'rr_skew_bpvol',
    histogramOverlay: 'skew_direction',
  },
  VERTICAL_SPREAD_1X1: {
    packageType: 'VERTICAL_SPREAD_1X1',
    primaryMetric: metric('vs_vol_spread_bpvol_yr', 'Vol Spread', 'bpvol/yr', {
      primary: true,
      decimals: 2,
      formatKind: 'metric',
    }),
    secondaryMetrics: [
      metric('vs_strike_width_bps', 'Strike Width', 'bps', {
        decimals: 1,
        formatKind: 'bps',
      }),
      metric('vs_net_premium', 'Net Premium', 'USD', {
        decimals: 2,
        formatKind: 'premium',
        absolute: true,
      }),
      derivedMetric('premium_offset_ratio', 'Premium Offset', 'ratio', {
        decimals: 2,
        formatKind: 'ratio',
        formula: 'vs_net_premium / vs_atm_premium',
      }),
      derivedMetric('net_dv01_ratio', 'Net DV01 Ratio', 'ratio', {
        decimals: 2,
        formatKind: 'ratio',
        formula: 'vs_dv01 / vs_atm_dv01',
      }),
      metric('vs_atm_strike_offset', 'ATM Strike Offset', 'bps', {
        decimals: 1,
        formatKind: 'bps',
      }),
      metric('total_notional', 'Notional', 'USD', {
        formatKind: 'notional',
        absolute: true,
      }),
      metric('total_premium', 'Premium', 'USD', {
        formatKind: 'premium',
        absolute: true,
      }),
    ],
    similarityCriteria: {
      metric: 'vs_strike_width_bps',
      mode: 'absolute_range',
      threshold: 25,
      requireDirection: true,
    },
    histogramDefault: 'vs_vol_spread_bpvol_yr',
    histogramOverlay: 'iqr_band',
  },
  VERTICAL_SPREAD_1X2: {
    packageType: 'VERTICAL_SPREAD_1X2',
    primaryMetric: metric('vs_notional_ratio', 'Notional Ratio', 'ratio', {
      primary: true,
      decimals: 2,
      formatKind: 'ratio',
    }),
    secondaryMetrics: [
      derivedMetric('notional_ratio_deviation', 'Ratio Deviation', 'ratio', {
        decimals: 2,
        formatKind: 'ratio',
        formula: 'abs(vs_notional_ratio - 2.0)',
      }),
      metric('vs_vol_spread_bpvol_yr', 'Vol Spread', 'bpvol/yr', {
        decimals: 2,
        formatKind: 'metric',
      }),
      metric('vs_strike_width_bps', 'Strike Width', 'bps', {
        decimals: 1,
        formatKind: 'bps',
      }),
      metric('vs_net_premium', 'Net Premium', 'USD', {
        decimals: 2,
        formatKind: 'premium',
        absolute: true,
      }),
      derivedMetric('net_premium_sign', 'Net Prem Sign', 'sign', {
        decimals: 0,
        formatKind: 'raw',
        formula: 'sign(vs_net_premium)',
      }),
      metric('total_notional', 'Notional', 'USD', {
        formatKind: 'notional',
        absolute: true,
      }),
      metric('total_premium', 'Premium', 'USD', {
        formatKind: 'premium',
        absolute: true,
      }),
    ],
    similarityCriteria: {
      metric: 'vs_notional_ratio',
      mode: 'absolute_range',
      threshold: 0.2,
      requireDirection: true,
    },
    histogramDefault: 'vs_notional_ratio',
    histogramOverlay: 'ratio_reference',
  },
  RECEIVER_LADDER: {
    packageType: 'RECEIVER_LADDER',
    primaryMetric: metric('ladder_width', 'Ladder Width', 'bps', {
      primary: true,
      decimals: 1,
      formatKind: 'bps',
      derivedFrom: ladderWidthDerived,
    }),
    secondaryMetrics: [
      derivedMetric('spacing_uniformity', 'Spacing Uniformity', 'ratio', {
        decimals: 2,
        formatKind: 'ratio',
        formula: 'stddev(gaps) / mean(gaps)',
      }),
      derivedMetric('notional_profile', 'Notional Profile', 'pattern', {
        decimals: 0,
        formatKind: 'raw',
        formula: 'ladder_notionals normalized',
        percentile: false,
      }),
      metric('total_notional', 'Notional', 'USD', {
        formatKind: 'notional',
        absolute: true,
      }),
      metric('total_premium', 'Premium', 'USD', {
        formatKind: 'premium',
        absolute: true,
      }),
    ],
    similarityCriteria: {
      metric: 'ladder_width',
      mode: 'absolute_range',
      threshold: 50,
    },
    histogramDefault: 'ladder_width',
  },
  PAYER_LADDER: {
    packageType: 'PAYER_LADDER',
    primaryMetric: metric('ladder_width', 'Ladder Width', 'bps', {
      primary: true,
      decimals: 1,
      formatKind: 'bps',
      derivedFrom: ladderWidthDerived,
    }),
    secondaryMetrics: [
      derivedMetric('spacing_uniformity', 'Spacing Uniformity', 'ratio', {
        decimals: 2,
        formatKind: 'ratio',
        formula: 'stddev(gaps) / mean(gaps)',
      }),
      derivedMetric('notional_profile', 'Notional Profile', 'pattern', {
        decimals: 0,
        formatKind: 'raw',
        formula: 'ladder_notionals normalized',
        percentile: false,
      }),
      metric('total_notional', 'Notional', 'USD', {
        formatKind: 'notional',
        absolute: true,
      }),
      metric('total_premium', 'Premium', 'USD', {
        formatKind: 'premium',
        absolute: true,
      }),
    ],
    similarityCriteria: {
      metric: 'ladder_width',
      mode: 'absolute_range',
      threshold: 50,
    },
    histogramDefault: 'ladder_width',
  },
  CUSTY_RR_STRANGLE: {
    packageType: 'CUSTY_RR_STRANGLE',
    primaryMetric: metric('custy_rr_width_bps', 'Width', 'bps', {
      primary: true,
      decimals: 1,
      formatKind: 'bps',
    }),
    secondaryMetrics: [
      metric('total_notional', 'Notional', 'USD', {
        formatKind: 'notional',
        absolute: true,
      }),
      metric('total_premium', 'Premium', 'USD', {
        formatKind: 'premium',
        absolute: true,
      }),
    ],
    similarityCriteria: {
      metric: 'custy_rr_width_bps',
      mode: 'absolute_range',
      threshold: 25,
    },
    histogramDefault: 'custy_rr_width_bps',
  },
  DELTA_HEDGE: {
    packageType: 'DELTA_HEDGE',
    primaryMetric: metric('delta_hedge_implied_delta', 'Implied Delta', 'ratio', {
      primary: true,
      decimals: 3,
      formatKind: 'ratio',
    }),
    secondaryMetrics: [
      metric('delta_hedge_dv01_ratio', 'DV01 Ratio', 'ratio', {
        decimals: 3,
        formatKind: 'ratio',
      }),
      derivedMetric('delta_ratio_gap', 'Delta/DV01 Gap', 'ratio', {
        decimals: 3,
        formatKind: 'ratio',
        formula: 'abs(delta_hedge_dv01_ratio - delta_hedge_implied_delta)',
      }),
      metric('delta_hedge_match_window_seconds', 'Match Window', 'sec', {
        decimals: 0,
        formatKind: 'count',
      }),
      metric('delta_hedge_swap_tenor_years', 'Swap Tenor', 'years', {
        decimals: 2,
        formatKind: 'raw',
      }),
      metric('delta_hedge_swap_notional', 'Swap Notional', 'USD', {
        formatKind: 'notional',
        absolute: true,
      }),
      metric('total_notional', 'Swaption Notional', 'USD', {
        formatKind: 'notional',
        absolute: true,
      }),
      metric('total_premium', 'Premium', 'USD', {
        formatKind: 'premium',
        absolute: true,
      }),
    ],
    similarityCriteria: {
      metric: 'delta_hedge_implied_delta',
      mode: 'absolute_range',
      threshold: 0.1,
    },
    histogramDefault: 'delta_hedge_implied_delta',
  },
  OUTRIGHT: {
    packageType: 'OUTRIGHT',
    primaryMetric: metric('outright_bpvol_yr', 'BPVol/Yr', 'bpvol/yr', {
      primary: true,
      decimals: 3,
      formatKind: 'metric',
    }),
    secondaryMetrics: [
      metric('outright_strike_offset_bps', 'Strike Offset', 'bps', {
        decimals: 1,
        formatKind: 'bps',
      }),
      derivedMetric('outright_moneyness', 'Moneyness', 'label', {
        decimals: 0,
        formatKind: 'raw',
        formula: 'sign(strike_offset_bps)',
      }),
      metric('total_notional', 'Notional', 'USD', {
        formatKind: 'notional',
        absolute: true,
      }),
      metric('total_premium', 'Premium', 'USD', {
        formatKind: 'premium',
        absolute: true,
      }),
      metric('outright_vega01', 'Vega01', 'USD/bp', {
        decimals: 2,
        formatKind: 'metric',
        absolute: true,
      }),
      metric('outright_dv01', 'DV01', 'USD/bp', {
        decimals: 2,
        formatKind: 'metric',
        absolute: true,
      }),
    ],
    similarityCriteria: {
      metric: 'outright_strike_offset_bps',
      mode: 'absolute_range',
      threshold: 25,
      requireOptionType: true,
    },
    histogramDefault: 'outright_bpvol_yr',
  },
};

const KNOWN_PACKAGE_TYPES = Object.keys(STRUCTURE_ANALYTICS_CONFIG);

const buildConfigWithShowFor = (): Record<string, StructureAnalyticsConfig> => {
  const next: Record<string, StructureAnalyticsConfig> = {};
  Object.entries(STRUCTURE_ANALYTICS_CONFIG).forEach(([key, config]) => {
    const tag = config.packageType || key;
    const primaryMetric = { ...config.primaryMetric, showFor: [tag] };
    const secondaryMetrics = config.secondaryMetrics.map((metricItem) => ({
      ...metricItem,
      showFor: metricItem.showFor.length ? metricItem.showFor : [tag],
    }));
    next[key] = {
      ...config,
      primaryMetric,
      secondaryMetrics,
    };
  });
  return next;
};

const STRUCTURE_ANALYTICS = buildConfigWithShowFor();

export { STRUCTURE_ANALYTICS, STRUCTURE_ANALYTICS_CONFIG, KNOWN_PACKAGE_TYPES };
