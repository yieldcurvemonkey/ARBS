export type QuadrantTrade = {
  packageId: string;
  executionTimestamp: number;
  signedNotional: number;
  platform?: "custy" | "idb";
};

export type SparklinePoint = {
  timestamp: number;
  cumulativeNet: number;
  tradeIndex: number;
  tradeNotional: number;
  tradeId: string;
  isBaseline?: boolean;
};

export type SparklinePattern =
  | "monotonic_receiver"
  | "monotonic_payer"
  | "burst_then_flat"
  | "reversal"
  | "oscillating"
  | "single_trade"
  | "empty";
