export type SparklineMode = "net_directional" | "vol_flow";
export type VolFlowAxisMetric = "vega" | "gamma" | "notional";

export type QuadrantTradeFlows = {
  packageId: string;
  executionTimestamp: number;
  packageType: string;
  platform?: "custy" | "idb";
  signedNotional: number;
  economicNotional: number;
  flowVega01?: number | null;
  flowGamma01?: number | null;
  isDeltaNeutral: boolean;
  isStraddle: boolean;
};

export type SparklinePoint = {
  timestamp: number;
  cumulativeValue: number;
  tradeIndex: number;
  tradeValue: number;
  tradeId: string;
  isBaseline?: boolean;
  packageType?: string;
  platform?: "custy" | "idb";
  signedNotional?: number;
  economicNotional?: number;
  flowVega01?: number | null;
  flowGamma01?: number | null;
  flowMetric?: VolFlowAxisMetric;
  isDeltaNeutral?: boolean;
  isStraddle?: boolean;
};

export type DirectionalSparklinePattern =
  | "monotonic_receiver"
  | "monotonic_payer"
  | "burst_then_flat"
  | "reversal"
  | "oscillating"
  | "single_trade"
  | "empty";

export type VolFlowPattern =
  | "front_loaded"
  | "back_loaded"
  | "midday_burst"
  | "steady"
  | "sparse"
  | "single_burst"
  | "empty";

export type SteepestSegment = {
  startTimestamp: number;
  endTimestamp: number;
  startCumulative: number;
  endCumulative: number;
  notionalInWindow: number;
  durationMinutes: number;
  pacePerHour: number;
  shareOfTotal: number;
};

export type StructureDecomposition = {
  straddleNotional: number;
  straddleShare: number;
  outrightNotional: number;
  outrightShare: number;
  skewNotional: number;
  skewShare: number;
  totalEconomicNotional: number;
};

export type QuadrantTrade = QuadrantTradeFlows;
