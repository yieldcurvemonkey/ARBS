// Types for vol grid quadrant framework
import type { TapeRow } from './trade.types';

/** The four quadrants of the vol grid, plus boundary */
export type VolGridQuadrant = 'ULC' | 'URC' | 'LLC' | 'LRC' | 'BOUNDARY';

/** Configurable boundaries for quadrant classification */
export type QuadrantConfig = {
  /** Expiry boundary in years (default 1.5 = between 1Y and 2Y) */
  expiryBoundaryYears: number;
  /** Tenor boundary in years (default 7.5 = between 5Y and 10Y) */
  tenorBoundaryYears: number;
  /** Tolerance in years for boundary tagging (default 0.5) */
  boundaryToleranceYears: number;
};

/** Result of quadrant classification */
export type QuadrantClassification = {
  quadrant: VolGridQuadrant;
  /** For BOUNDARY trades, which quadrants they straddle */
  adjacentQuadrants?: VolGridQuadrant[];
  /** Parsed expiry in years */
  expiryYears: number | null;
  /** Parsed tenor in years */
  tenorYears: number | null;
};

/** Net direction summary */
export type FlowDirection = 'payer' | 'receiver' | 'balanced';

/** Aggregated flow snapshot for a single quadrant */
export type QuadrantFlowSnapshot = {
  quadrant: VolGridQuadrant;
  tradeCount: number;
  grossNotional: number;
  /** Signed: + = payer, - = receiver */
  netNotional: number;
  /** abs(net) / gross */
  netGrossRatio: number;
  totalPremium: number;
  /** 1.0 = normal, 2.0 = 2x normal */
  paceVsBaseline: number;
  dominantDirection: FlowDirection;
  /** Most common package_type in this quadrant */
  dominantStructure: string;
  /** Trade rows in this quadrant */
  trades: TapeRow[];
};

/** Cross-quadrant correlation signal */
export type CrossQuadrantSignal = {
  /** e.g. "URC_receiver_LRC_payer" */
  signalId: string;
  label: string;
  description: string;
  quadrants: VolGridQuadrant[];
  /** 0-1 strength */
  confidence: number;
};

/** Full grid flow state across all four quadrants */
export type GridFlowState = {
  ulc: QuadrantFlowSnapshot;
  urc: QuadrantFlowSnapshot;
  llc: QuadrantFlowSnapshot;
  lrc: QuadrantFlowSnapshot;
  boundary: QuadrantFlowSnapshot;
  detectedRegime: FlowRegime | null;
  regimeConfidence: number;
  crossQuadrantSignals: CrossQuadrantSignal[];
  /** One-line narrative summary */
  dominantTheme: string;
};

/** Known flow regime identifiers */
export type FlowRegimeId =
  | 'GSE_HEDGING'
  | 'CALLABLE_ISSUANCE'
  | 'SYSTEMATIC_GAMMA_SELLING'
  | 'RISK_OFF_RALLY'
  | 'STEEPENER'
  | 'FLATTENER'
  | 'QUARTER_END_REBALANCING'
  | 'UNKNOWN';

/** Flow regime definition with expected signature */
export type FlowRegime = {
  id: FlowRegimeId;
  label: string;
  description: string;
  driver: string;
  /** Expected direction for each quadrant */
  signature: {
    ulc: FlowDirection | 'quiet' | 'any';
    urc: FlowDirection | 'quiet' | 'any';
    llc: FlowDirection | 'quiet' | 'any';
    lrc: FlowDirection | 'quiet' | 'any';
  };
  /** Expected intensity for each quadrant: 'low' | 'moderate' | 'heavy' */
  intensity: {
    ulc: 'low' | 'moderate' | 'heavy' | 'any';
    urc: 'low' | 'moderate' | 'heavy' | 'any';
    llc: 'low' | 'moderate' | 'heavy' | 'any';
    lrc: 'low' | 'moderate' | 'heavy' | 'any';
  };
};

/** Quadrant metadata with desk commentary */
export type QuadrantMeta = {
  id: VolGridQuadrant;
  label: string;
  fullName: string;
  description: string;
  typicalParticipants: string[];
  supplyDemandDrivers: string;
  deskView: string;
  deskViewUpdatedAt: string;
  deskViewUpdatedBy: string;
};

/** Anomaly detected in a quadrant */
export type QuadrantAnomaly = {
  type: 'volume' | 'direction' | 'premium' | 'cross_quadrant';
  quadrant: VolGridQuadrant;
  severity: 'info' | 'notable' | 'extreme';
  message: string;
  detail: string;
  /** Current value vs historical context */
  currentValue: number;
  historicalBaseline: number;
  /** Percentile of current value vs history */
  percentile?: number;
};

/** Quadrant timeseries data point */
export type QuadrantTimeseriesPoint = {
  timestamp: number;
  dateLabel: string;
  quadrant: VolGridQuadrant;
  grossNotional: number;
  netNotional: number;
  tradeCount: number;
  totalPremium: number;
  paceVsBaseline: number;
};

/** Quadrant context enrichment for a trade */
export type TradeQuadrantContext = {
  classification: QuadrantClassification;
  quadrantMeta: QuadrantMeta;
  /** Quadrant-level flow summary for the day */
  quadrantFlow: QuadrantFlowSnapshot;
  /** Does this trade reinforce or counter the quadrant direction? */
  reinforcesDirection: boolean;
  /** Fraction of quadrant's daily gross notional */
  shareOfQuadrant: number;
  /** Simultaneous activity in other quadrants (±30 min window) */
  simultaneousActivity: {
    quadrant: VolGridQuadrant;
    tradeCount: number;
    netNotional: number;
    direction: FlowDirection;
  }[];
  /** Detected cross-quadrant pattern (if any) */
  crossQuadrantPattern: CrossQuadrantSignal | null;
};

/** Premium share for quadrant rotation analysis */
export type QuadrantPremiumShare = {
  timestamp: number;
  dateLabel: string;
  ulcShare: number;
  urcShare: number;
  llcShare: number;
  lrcShare: number;
};
