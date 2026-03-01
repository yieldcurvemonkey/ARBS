import type { PointSignal } from "./pointGridFlow.types";

export type PointGridAxisNode = {
  label: string;
  years: number;
};

export type PointGridNodeDefinition = {
  pointKey: string;
  expiryLabel: string;
  tenorLabel: string;
  expiryYears: number;
  tenorYears: number;
};

export const POINT_GRID_EXPIRY_NODES: PointGridAxisNode[] = [
  { label: "1M", years: 1 / 12 },
  { label: "3M", years: 3 / 12 },
  { label: "6M", years: 6 / 12 },
  { label: "1Y", years: 1 },
  { label: "2Y", years: 2 },
  { label: "3Y", years: 3 },
  { label: "5Y", years: 5 },
  { label: "10Y", years: 10 },
  { label: "20Y", years: 20 },
];

export const POINT_GRID_TENOR_NODES: PointGridAxisNode[] = [
  { label: "1Y", years: 1 },
  { label: "2Y", years: 2 },
  { label: "3Y", years: 3 },
  { label: "5Y", years: 5 },
  { label: "7Y", years: 7 },
  { label: "10Y", years: 10 },
  { label: "20Y", years: 20 },
  { label: "30Y", years: 30 },
];

export const POINT_GRID_TENOR_WEIGHT = 0.7;

export function buildPointKey(expiryLabel: string, tenorLabel: string) {
  return `${expiryLabel}x${tenorLabel}`;
}

export const POINT_GRID_NODES: PointGridNodeDefinition[] =
  POINT_GRID_EXPIRY_NODES.flatMap((expiryNode) =>
    POINT_GRID_TENOR_NODES.map((tenorNode) => ({
      pointKey: buildPointKey(expiryNode.label, tenorNode.label),
      expiryLabel: expiryNode.label,
      tenorLabel: tenorNode.label,
      expiryYears: expiryNode.years,
      tenorYears: tenorNode.years,
    })),
  );

export function computeWeightedLogDistance(
  expiryYears: number,
  tenorYears: number,
  nodeExpiryYears: number,
  nodeTenorYears: number,
  tenorWeight: number = POINT_GRID_TENOR_WEIGHT,
): number {
  if (
    !Number.isFinite(expiryYears) ||
    !Number.isFinite(tenorYears) ||
    !Number.isFinite(nodeExpiryYears) ||
    !Number.isFinite(nodeTenorYears) ||
    expiryYears <= 0 ||
    tenorYears <= 0 ||
    nodeExpiryYears <= 0 ||
    nodeTenorYears <= 0
  ) {
    return Number.POSITIVE_INFINITY;
  }
  const logExpiry = Math.abs(Math.log(expiryYears) - Math.log(nodeExpiryYears));
  const logTenor = Math.abs(Math.log(tenorYears) - Math.log(nodeTenorYears));
  return Math.sqrt(logExpiry ** 2 + (tenorWeight * logTenor) ** 2);
}

export function assignNearestPoint(
  expiryYears: number,
  tenorYears: number,
  nodes: PointGridNodeDefinition[] = POINT_GRID_NODES,
  tenorWeight: number = POINT_GRID_TENOR_WEIGHT,
): PointGridNodeDefinition | null {
  if (!nodes.length) return null;
  let nearestNode: PointGridNodeDefinition | null = null;
  let nearestDistance = Number.POSITIVE_INFINITY;

  nodes.forEach((node) => {
    const distance = computeWeightedLogDistance(
      expiryYears,
      tenorYears,
      node.expiryYears,
      node.tenorYears,
      tenorWeight,
    );
    if (distance < nearestDistance) {
      nearestDistance = distance;
      nearestNode = node;
    }
  });

  return nearestNode;
}

export function computeZeroFilledAverage(
  values: Array<number | null | undefined>,
  sessionsUsed: number,
): number {
  if (!Number.isFinite(sessionsUsed) || sessionsUsed <= 0) return 0;
  const total = values.reduce<number>((sum, value) => {
    if (!Number.isFinite(value as number)) return sum;
    return sum + Number(value);
  }, 0);
  return total / sessionsUsed;
}

export function computeSparseAverage(
  values: Array<number | null | undefined>,
): number | null {
  const valid = values.filter(
    (value): value is number =>
      value !== null && value !== undefined && Number.isFinite(value),
  );
  if (!valid.length) return null;
  return valid.reduce((sum, value) => sum + value, 0) / valid.length;
}

export function computeGrossVsAverage(
  reportGross: number | null | undefined,
  avgGross: number | null | undefined,
): number | null {
  if (!Number.isFinite(reportGross as number)) return null;
  if (!Number.isFinite(avgGross as number) || Number(avgGross) <= 0) return null;
  return Number(reportGross) / Number(avgGross);
}

export function buildPointSignal(input: {
  reportTradeCount: number | null | undefined;
  grossVs5SessionAvg: number | null | undefined;
  daysSinceLastTrade: number | null | undefined;
}): { signal: PointSignal; signalReason: string } {
  const reportTradeCount = Number(input.reportTradeCount ?? 0);
  const grossVs = Number.isFinite(input.grossVs5SessionAvg as number)
    ? Number(input.grossVs5SessionAvg)
    : null;
  const daysSince = Number.isFinite(input.daysSinceLastTrade as number)
    ? Number(input.daysSinceLastTrade)
    : null;

  if (reportTradeCount >= 2 && grossVs !== null && grossVs >= 1.5) {
    return {
      signal: "positive",
      signalReason:
        "Continuation watch: multi-print flow with gross notional at least 1.5x the 5-session baseline.",
    };
  }
  if (
    (daysSince !== null && daysSince >= 10) ||
    (reportTradeCount > 0 && grossVs !== null && grossVs <= 0.5)
  ) {
    return {
      signal: "negative",
      signalReason:
        "Stale/faded flow: point is inactive for 10+ days or current gross notional is <= 0.5x baseline.",
    };
  }
  return {
    signal: "neutral",
    signalReason: "No strong deviation: flow is within normal range for this point.",
  };
}

export function signalToneClasses(signal: PointSignal, selected: boolean): string {
  const base = selected ? "ring-2 ring-sky-400" : "";
  if (signal === "positive") {
    return `bg-emerald-900/35 border-emerald-600/60 text-emerald-100 ${base}`.trim();
  }
  if (signal === "negative") {
    return `bg-rose-900/35 border-rose-600/60 text-rose-100 ${base}`.trim();
  }
  return `bg-slate-900/50 border-slate-700 text-slate-200 ${base}`.trim();
}
