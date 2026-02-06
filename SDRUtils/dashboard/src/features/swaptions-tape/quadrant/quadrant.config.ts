// Default configuration for vol grid quadrant framework
import type {
  QuadrantConfig,
  QuadrantMeta,
  FlowRegime,
  VolGridQuadrant,
} from '../types/quadrant.types';

/** Default boundary configuration */
export const DEFAULT_QUADRANT_CONFIG: QuadrantConfig = {
  expiryBoundaryYears: 1.5,
  tenorBoundaryYears: 7.5,
  boundaryToleranceYears: 0.5,
};

/** Default metadata for each quadrant */
export const DEFAULT_QUADRANT_META: Record<VolGridQuadrant, QuadrantMeta> = {
  ULC: {
    id: 'ULC',
    label: 'ULC',
    fullName: 'Gamma + Short Tails',
    description: 'Short-expiry options on short-tenor swaps (1M-1Y expiry × 2Y-5Y tenor)',
    typicalParticipants: ['Pay-fix hedgers in 2Y sector', 'Short-dated rate hedgers'],
    supplyDemandDrivers: 'Pay-fix hedging in 2Y. Less desk focus — lower liquidity and flow.',
    deskView: 'Low priority — smaller notionals, less vol surface impact',
    deskViewUpdatedAt: new Date().toISOString(),
    deskViewUpdatedBy: 'SYSTEM',
  },
  URC: {
    id: 'URC',
    label: 'URC',
    fullName: 'Gamma + Long Tails',
    description: 'Short-expiry options on long-tenor swaps (1M-1Y expiry × 10Y-30Y tenor)',
    typicalParticipants: [
      'GSE hedging (pay-fix)',
      'Systematic gamma sellers',
      'Bank mortgage desks',
      'Op Twist participants',
    ],
    supplyDemandDrivers:
      'GSE pay-fix hedging creates receiver supply. Systematic gamma selling targets URC for carry.',
    deskView: 'SELL (3m10y straddles) — gamma-rich, high liquidity',
    deskViewUpdatedAt: new Date().toISOString(),
    deskViewUpdatedBy: 'SYSTEM',
  },
  LLC: {
    id: 'LLC',
    label: 'LLC',
    fullName: 'Vega + Short Tails',
    description: 'Long-expiry options on short-tenor swaps (2Y-10Y+ expiry × 2Y-5Y tenor)',
    typicalParticipants: [
      'Callable bond issuers',
      'Corporate hedgers',
      'Insurance companies',
    ],
    supplyDemandDrivers:
      'Callable issuance = vega supply headwind. Corporate callable bond issuance creates persistent supply.',
    deskView: 'Neutral/avoid — supply headwind from callable issuance',
    deskViewUpdatedAt: new Date().toISOString(),
    deskViewUpdatedBy: 'SYSTEM',
  },
  LRC: {
    id: 'LRC',
    label: 'LRC',
    fullName: 'Vega + Long Tails',
    description: 'Long-expiry options on long-tenor swaps (2Y-10Y+ expiry × 10Y-30Y tenor)',
    typicalParticipants: [
      'Pension funds',
      'Insurance ALM',
      'Macro hedge funds',
      'Long-vol structural buyers',
    ],
    supplyDemandDrivers:
      'Less GSE flow. Callable supply doesn\'t reach here. Structural demand from pension/insurance.',
    deskView: 'OWN (30y tail outperformance) — structural demand, less supply',
    deskViewUpdatedAt: new Date().toISOString(),
    deskViewUpdatedBy: 'SYSTEM',
  },
  BOUNDARY: {
    id: 'BOUNDARY',
    label: 'BOUNDARY',
    fullName: 'Boundary Trades',
    description:
      'Trades near quadrant boundaries with mixed characteristics from adjacent quadrants',
    typicalParticipants: ['Various — depends on adjacent quadrants'],
    supplyDemandDrivers: 'Mixed characteristics from adjacent quadrants',
    deskView: 'Context-dependent — review adjacent quadrant views',
    deskViewUpdatedAt: new Date().toISOString(),
    deskViewUpdatedBy: 'SYSTEM',
  },
};

/** Known flow regime definitions */
export const FLOW_REGIMES: FlowRegime[] = [
  {
    id: 'GSE_HEDGING',
    label: 'GSE Hedging Wave',
    description: 'Mortgage originators hedging rate locks via GSEs who receive in URC',
    driver: 'Mortgage origination → GSE pay-fix hedging → URC receiver supply',
    signature: { ulc: 'quiet', urc: 'receiver', llc: 'quiet', lrc: 'payer' },
    intensity: { ulc: 'low', urc: 'heavy', llc: 'low', lrc: 'moderate' },
  },
  {
    id: 'CALLABLE_ISSUANCE',
    label: 'Callable Issuance',
    description: 'Corporate callable bond issuance creates vega supply in LLC',
    driver: 'Corporate callable bond issuance → LLC vega supply',
    signature: { ulc: 'quiet', urc: 'quiet', llc: 'receiver', lrc: 'quiet' },
    intensity: { ulc: 'low', urc: 'low', llc: 'heavy', lrc: 'low' },
  },
  {
    id: 'SYSTEMATIC_GAMMA_SELLING',
    label: 'Systematic Gamma Selling',
    description: 'Vol-selling funds targeting gamma-rich URC for carry',
    driver: 'Systematic vol-selling strategies → URC payer flow',
    signature: { ulc: 'quiet', urc: 'payer', llc: 'quiet', lrc: 'quiet' },
    intensity: { ulc: 'low', urc: 'heavy', llc: 'low', lrc: 'low' },
  },
  {
    id: 'RISK_OFF_RALLY',
    label: 'Risk-Off / Rates Rally',
    description: 'Broad-based rate receiver flow across the grid',
    driver: 'Flight to safety → broad receiver flow',
    signature: { ulc: 'any', urc: 'receiver', llc: 'receiver', lrc: 'receiver' },
    intensity: { ulc: 'any', urc: 'heavy', llc: 'heavy', lrc: 'moderate' },
  },
  {
    id: 'STEEPENER',
    label: 'Steepener Positioning',
    description:
      'Curve steepener via vol — receiving gamma on long tail, paying vega on long tail',
    driver: 'Steepener trade: receive URC + pay LRC',
    signature: { ulc: 'quiet', urc: 'receiver', llc: 'quiet', lrc: 'payer' },
    intensity: { ulc: 'low', urc: 'moderate', llc: 'low', lrc: 'moderate' },
  },
  {
    id: 'FLATTENER',
    label: 'Flattener Positioning',
    description: 'Curve flattener via vol — paying gamma on long tail, receiving vega on long tail',
    driver: 'Flattener trade: pay URC + receive LRC',
    signature: { ulc: 'quiet', urc: 'payer', llc: 'quiet', lrc: 'receiver' },
    intensity: { ulc: 'low', urc: 'moderate', llc: 'low', lrc: 'moderate' },
  },
  {
    id: 'QUARTER_END_REBALANCING',
    label: 'Quarter-End Rebalancing',
    description: 'Broad, non-directional, balanced flow as books rebalance',
    driver: 'Quarter-end portfolio rebalancing',
    signature: { ulc: 'balanced', urc: 'balanced', llc: 'balanced', lrc: 'balanced' },
    intensity: { ulc: 'moderate', urc: 'moderate', llc: 'moderate', lrc: 'moderate' },
  },
];

/** Quadrant color scheme for dashboard display */
export const QUADRANT_COLORS: Record<VolGridQuadrant, { bg: string; border: string; text: string; accent: string }> = {
  ULC: {
    bg: 'bg-sky-950/40',
    border: 'border-sky-800/50',
    text: 'text-sky-300',
    accent: '#38bdf8',
  },
  URC: {
    bg: 'bg-amber-950/40',
    border: 'border-amber-800/50',
    text: 'text-amber-300',
    accent: '#f59e0b',
  },
  LLC: {
    bg: 'bg-emerald-950/40',
    border: 'border-emerald-800/50',
    text: 'text-emerald-300',
    accent: '#34d399',
  },
  LRC: {
    bg: 'bg-purple-950/40',
    border: 'border-purple-800/50',
    text: 'text-purple-300',
    accent: '#a855f7',
  },
  BOUNDARY: {
    bg: 'bg-slate-900/40',
    border: 'border-slate-700/50',
    text: 'text-slate-400',
    accent: '#94a3b8',
  },
};

/** Regime severity colors */
export const REGIME_COLORS: Record<string, string> = {
  GSE_HEDGING: 'text-amber-400',
  CALLABLE_ISSUANCE: 'text-emerald-400',
  SYSTEMATIC_GAMMA_SELLING: 'text-red-400',
  RISK_OFF_RALLY: 'text-blue-400',
  STEEPENER: 'text-purple-400',
  FLATTENER: 'text-cyan-400',
  QUARTER_END_REBALANCING: 'text-slate-400',
  UNKNOWN: 'text-slate-500',
};
