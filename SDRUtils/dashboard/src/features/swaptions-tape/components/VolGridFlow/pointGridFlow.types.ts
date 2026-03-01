export type PointSignal = "positive" | "negative" | "neutral";

export type PointGridPlatform = "combined" | "idb" | "custy";

export type PointMetrics = {
  tradeCount: number;
  grossNotional: number;
  totalPremium: number;
  avgPremium: number | null;
  avgBpvolYr: number | null;
  bpvolObsCount: number;
};

export type PointNode = {
  pointKey: string;
  expiryLabel: string;
  tenorLabel: string;
  expiryYears: number;
  tenorYears: number;
};

export type PointRow = {
  pointKey: string;
  expiryLabel: string;
  tenorLabel: string;
  lastTradeDate: string | null;
  daysSinceLastTrade: number | null;
  reportDate: PointMetrics;
  previousSessionDate: PointMetrics;
  previousSessionLabel: string | null;
  avg5Sessions: PointMetrics;
  grossVs5SessionAvg: number | null;
  bpvol1dChange: number | null;
  avgPremium1dChange: number | null;
  signal: PointSignal;
  signalReason: string;
};

export type PointGridFlowResponse = {
  meta: {
    timezone: "America/New_York";
    asOfDate: string;
    platform: PointGridPlatform;
    lookbackDays: number;
    avgSessions: number;
    baselineSessionsUsed: number;
  };
  nodes: PointNode[];
  rows: PointRow[];
  summary: {
    positiveCount: number;
    negativeCount: number;
    neutralCount: number;
    topGrossPoint: string | null;
    topSurgePoint: string | null;
    stalestPoint: string | null;
  };
  diagnostics: {
    reportDate: string | null;
    previousSessionDate: string | null;
    baselineDates: string[];
    lookbackTradeCount: number;
    unmappedTradeCount: number;
  };
};
