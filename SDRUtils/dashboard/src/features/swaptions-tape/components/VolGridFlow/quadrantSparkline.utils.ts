import type {
  DirectionalSparklinePattern,
  QuadrantTradeFlows,
  SparklinePoint,
  SteepestSegment,
  StructureDecomposition,
  VolFlowAxisMetric,
  VolFlowPattern,
} from "./quadrantSparkline.types";

const DEFAULT_DIRECTIONAL_DOMAIN: [number, number] = [-1, 1];
const DEFAULT_VOL_DOMAIN: [number, number] = [0, 1];
const ONE_HOUR_MS = 60 * 60 * 1000;
const ONE_MINUTE_MS = 60 * 1000;

const DELTA_NEUTRAL_TYPES = new Set([
  "STRADDLE",
  "RISK_REVERSAL",
  "CUSTY_RR_STRANGLE",
]);

function normalizePackageType(type: string | null | undefined): string {
  if (!type) return "";
  return type.replace(/-/g, "_").toUpperCase();
}

export function isDeltaNeutral(packageType: string): boolean {
  return DELTA_NEUTRAL_TYPES.has(normalizePackageType(packageType));
}

export function getEconomicNotional(
  totalNotional: number,
  packageType: string,
): number {
  const total = Number.isFinite(totalNotional) ? Math.abs(totalNotional) : 0;
  const normalized = normalizePackageType(packageType);
  if (!total) return 0;
  switch (normalized) {
    case "STRADDLE":
      return total / 2;
    case "RISK_REVERSAL":
    case "VERTICAL_SPREAD_1X1":
    case "VERTICAL_SPREAD_1X2":
    case "CUSTY_RR_STRANGLE":
      return normalized === "VERTICAL_SPREAD_1X2" ? total / 3 : total / 2;
    default:
      return total;
  }
}

export function formatCompactNotional(value: number | null | undefined): string {
  if (!Number.isFinite(value as number)) return "--";
  const numeric = Number(value);
  const abs = Math.abs(numeric);
  const sign = numeric < 0 ? "-" : "";
  if (abs >= 1_000_000_000) {
    const bn = abs / 1_000_000_000;
    const digits = bn >= 100 ? 2 : bn >= 10 ? 3 : 4;
    return `${sign}${bn.toFixed(digits)}bn`;
  }
  if (abs >= 1_000_000) {
    const mm = abs / 1_000_000;
    const digits = mm >= 100 ? 2 : mm >= 10 ? 3 : 4;
    return `${sign}${mm.toFixed(digits)}mm`;
  }
  if (abs >= 1_000) {
    const kk = abs / 1_000;
    const digits = kk >= 100 ? 2 : kk >= 10 ? 3 : 4;
    return `${sign}${kk.toFixed(digits)}k`;
  }
  return `${sign}${abs.toFixed(2)}`;
}

export function buildDirectionalSparklineData(
  trades: QuadrantTradeFlows[],
): SparklinePoint[] {
  if (!Array.isArray(trades) || trades.length === 0) return [];

  const sorted = trades
    .map((trade, index) => ({ trade, index }))
    .filter(({ trade }) => Number.isFinite(trade.executionTimestamp))
    .sort((left, right) => {
      const diff = left.trade.executionTimestamp - right.trade.executionTimestamp;
      if (diff !== 0) return diff;
      return left.index - right.index;
    });

  if (!sorted.length) return [];

  const firstTimestamp = sorted[0].trade.executionTimestamp;
  let cumulative = 0;
  const points: SparklinePoint[] = [
    {
      timestamp: firstTimestamp,
      cumulativeValue: 0,
      tradeIndex: -1,
      tradeValue: 0,
      tradeId: "baseline",
      isBaseline: true,
    },
  ];

  sorted.forEach(({ trade }, index) => {
    const signedNotional = Number.isFinite(trade.signedNotional)
      ? trade.signedNotional
      : 0;
    cumulative += signedNotional;
    points.push({
      timestamp: trade.executionTimestamp,
      cumulativeValue: cumulative,
      tradeIndex: index,
      tradeValue: signedNotional,
      tradeId: trade.packageId,
      packageType: trade.packageType,
      platform: trade.platform,
      signedNotional: trade.signedNotional,
      economicNotional: trade.economicNotional,
      isDeltaNeutral: trade.isDeltaNeutral,
      isStraddle: trade.isStraddle,
    });
  });

  return points;
}

export function buildVolFlowSparklineData(
  trades: QuadrantTradeFlows[],
  flowMetric: VolFlowAxisMetric = "vega",
): SparklinePoint[] {
  if (!Array.isArray(trades) || trades.length === 0) return [];

  const sorted = trades
    .map((trade, index) => ({ trade, index }))
    .filter(({ trade }) => Number.isFinite(trade.executionTimestamp))
    .sort((left, right) => {
      const diff = left.trade.executionTimestamp - right.trade.executionTimestamp;
      if (diff !== 0) return diff;
      return left.index - right.index;
    });

  if (!sorted.length) return [];

  const firstTimestamp = sorted[0].trade.executionTimestamp;
  let cumulative = 0;
  const points: SparklinePoint[] = [
    {
      timestamp: firstTimestamp,
      cumulativeValue: 0,
      tradeIndex: -1,
      tradeValue: 0,
      tradeId: "baseline",
      isBaseline: true,
    },
  ];

  sorted.forEach(({ trade }, index) => {
    const flowVega = Number.isFinite(trade.flowVega01 as number)
      ? Math.abs(Number(trade.flowVega01))
      : null;
    const flowGamma = Number.isFinite(trade.flowGamma01 as number)
      ? Math.abs(Number(trade.flowGamma01))
      : null;
    const selectedFlowValue = flowMetric === "gamma" ? flowGamma : flowVega;
    const absoluteSelectedFlowValue =
      selectedFlowValue !== null && Number.isFinite(selectedFlowValue)
        ? Math.abs(Number(selectedFlowValue))
        : null;
    const flowValue =
      absoluteSelectedFlowValue !== null && absoluteSelectedFlowValue > 0
        ? absoluteSelectedFlowValue
        : Number.isFinite(trade.economicNotional)
          ? Math.abs(trade.economicNotional)
          : 0;
    cumulative += flowValue;
    points.push({
      timestamp: trade.executionTimestamp,
      cumulativeValue: cumulative,
      tradeIndex: index,
      tradeValue: flowValue,
      tradeId: trade.packageId,
      packageType: trade.packageType,
      platform: trade.platform,
      signedNotional: trade.signedNotional,
      economicNotional: trade.economicNotional,
      flowVega01: trade.flowVega01,
      flowGamma01: trade.flowGamma01,
      flowMetric,
      isDeltaNeutral: trade.isDeltaNeutral,
      isStraddle: trade.isStraddle,
    });
  });

  return points;
}

export function findPeakImbalance(
  points: SparklinePoint[],
  reversionThreshold = 1.5,
): SparklinePoint | null {
  if (!points.length) return null;
  const values = points
    .map((point) => point.cumulativeValue)
    .filter((value) => Number.isFinite(value));
  if (!values.length) return null;
  const finalValue = values[values.length - 1];
  const finalAbs = Math.abs(finalValue);
  const maxAbs = values.reduce(
    (max, value) => Math.max(max, Math.abs(value)),
    0,
  );
  if (finalAbs >= maxAbs) return null;
  if (maxAbs <= finalAbs * reversionThreshold) return null;
  const peakIndex = values.findIndex(
    (value) => Math.abs(value) === maxAbs,
  );
  if (peakIndex < 0 || peakIndex === values.length - 1) return null;
  return points[peakIndex] ?? null;
}

export function computeDirectionalDomain(
  points: SparklinePoint[],
): [number, number] {
  if (!points.length) return DEFAULT_DIRECTIONAL_DOMAIN;
  const values = points
    .map((point) => point.cumulativeValue)
    .filter((value) => Number.isFinite(value));
  if (!values.length) return DEFAULT_DIRECTIONAL_DOMAIN;

  let minValue = Math.min(...values, 0);
  let maxValue = Math.max(...values, 0);
  if (minValue === 0 && maxValue === 0) return DEFAULT_DIRECTIONAL_DOMAIN;

  const minPadding = minValue < 0 ? Math.abs(minValue) * 0.1 : 0;
  const maxPadding = maxValue > 0 ? Math.abs(maxValue) * 0.1 : 0;
  minValue -= minPadding;
  maxValue += maxPadding;

  const oppositePaddingRatio = 0.25;
  if (maxValue <= 0) {
    maxValue = Math.max(
      maxValue,
      Math.abs(minValue) * oppositePaddingRatio,
    );
  } else if (minValue >= 0) {
    minValue = Math.min(
      minValue,
      -Math.abs(maxValue) * oppositePaddingRatio,
    );
  }

  if (minValue === maxValue) {
    const anchor = minValue || 1;
    return [anchor - 1, anchor + 1];
  }

  return [minValue, maxValue];
}

export function computeVolFlowDomain(
  points: SparklinePoint[],
): [number, number] {
  if (!points.length) return DEFAULT_VOL_DOMAIN;
  const values = points
    .map((point) => point.cumulativeValue)
    .filter((value) => Number.isFinite(value));
  if (!values.length) return DEFAULT_VOL_DOMAIN;

  const maxValue = Math.max(...values, 0);
  if (maxValue === 0) return DEFAULT_VOL_DOMAIN;
  const padded = maxValue * 1.1;
  return [0, padded === 0 ? 1 : padded];
}

export function classifyDirectionalShape(
  points: SparklinePoint[],
): DirectionalSparklinePattern {
  if (!points.length) return "empty";
  if (points.length === 1) return "empty";

  const tradeCount = Math.max(points.length - 1, 0);
  if (tradeCount === 0) return "empty";
  if (tradeCount === 1) return "single_trade";

  const values = points.map((point) => point.cumulativeValue);
  const finalValue = values[values.length - 1];
  const finalAbs = Math.abs(finalValue);
  const peakAbs = values.reduce(
    (max, value) => Math.max(max, Math.abs(value)),
    0,
  );

  const zeroCrossings = countZeroCrossings(values);
  if (zeroCrossings >= 2 && peakAbs > 0 && finalAbs < peakAbs * 0.3) {
    return "oscillating";
  }

  const peakValue = values.reduce((maxValue, value) =>
    Math.abs(value) > Math.abs(maxValue) ? value : maxValue,
  );
  const peakSign = Math.sign(peakValue);
  const finalSign = Math.sign(finalValue);
  if (finalAbs > 0 && peakAbs >= finalAbs * 1.5) {
    if (peakSign !== 0 && finalSign !== 0 && peakSign !== finalSign) {
      return "reversal";
    }
    if (peakSign === finalSign && peakAbs >= finalAbs * 2) {
      return "reversal";
    }
  }

  if (finalAbs > 0 && tradeCount >= 2) {
    const firstQuarterTrades = Math.max(1, Math.floor(tradeCount * 0.25));
    const threshold = finalAbs * 0.6;
    let earlyIndex = -1;
    for (let index = 1; index <= firstQuarterTrades; index += 1) {
      if (Math.abs(values[index]) >= threshold) {
        earlyIndex = index;
        break;
      }
    }
    if (earlyIndex >= 0) {
      const earlyValue = values[earlyIndex];
      const tolerance = Math.abs(earlyValue) * 0.2;
      if (tolerance > 0) {
        const stable = values
          .slice(earlyIndex + 1)
          .every((value) => Math.abs(value - earlyValue) <= tolerance);
        if (stable) return "burst_then_flat";
      }
    }
  }

  const isNonIncreasing = values.every(
    (value, index) => index === 0 || value <= values[index - 1],
  );
  const isNonDecreasing = values.every(
    (value, index) => index === 0 || value >= values[index - 1],
  );

  if (isNonIncreasing && finalValue < 0) return "monotonic_receiver";
  if (isNonDecreasing && finalValue > 0) return "monotonic_payer";

  if (finalValue < 0) return "monotonic_receiver";
  if (finalValue > 0) return "monotonic_payer";
  return "oscillating";
}

export function classifyVolFlowShape(points: SparklinePoint[]): VolFlowPattern {
  const trades = points.filter((point) => point.tradeIndex >= 0);
  if (!trades.length) return "empty";
  if (trades.length === 1) return "single_burst";

  const firstTimestamp = trades[0].timestamp;
  const lastTimestamp = trades[trades.length - 1].timestamp;
  const elapsedMs = lastTimestamp - firstTimestamp;

  if (elapsedMs <= 15 * ONE_MINUTE_MS) return "single_burst";

  const gaps = trades
    .slice(1)
    .map((trade, index) => trade.timestamp - trades[index].timestamp)
    .filter((gap) => Number.isFinite(gap));
  const avgGap =
    gaps.length > 0
      ? gaps.reduce((sum, gap) => sum + gap, 0) / gaps.length
      : 0;

  if (trades.length <= 3 || avgGap > 60 * ONE_MINUTE_MS) return "sparse";

  const total =
    trades[trades.length - 1].cumulativeValue -
    (points[0]?.cumulativeValue ?? 0);
  if (!Number.isFinite(total) || total <= 0) return "steady";

  const firstThirdEnd = firstTimestamp + elapsedMs / 3;
  const lastThirdStart = firstTimestamp + (2 * elapsedMs) / 3;

  const valueAt = (timestamp: number) => {
    let value = 0;
    for (const trade of trades) {
      if (trade.timestamp > timestamp) break;
      value = trade.cumulativeValue;
    }
    return value;
  };

  const firstThirdValue = valueAt(firstThirdEnd);
  if (firstThirdValue / total >= 0.6) return "front_loaded";

  const lastThirdValue = valueAt(lastThirdStart);
  if ((total - lastThirdValue) / total >= 0.6) return "back_loaded";

  const windowMs = elapsedMs * 0.25;
  let maxShare = 0;
  let endIndex = 0;

  for (let startIndex = 0; startIndex < trades.length; startIndex += 1) {
    if (endIndex < startIndex) endIndex = startIndex;
    while (
      endIndex < trades.length &&
      trades[endIndex].timestamp - trades[startIndex].timestamp <= windowMs
    ) {
      endIndex += 1;
    }
    const end = endIndex - 1;
    if (end < startIndex) continue;
    const startCumulative =
      startIndex === 0 ? points[0]?.cumulativeValue ?? 0 : trades[startIndex - 1].cumulativeValue;
    const endCumulative = trades[end].cumulativeValue;
    const windowNotional = endCumulative - startCumulative;
    if (windowNotional <= 0) continue;
    const share = windowNotional / total;
    if (share > maxShare) maxShare = share;
  }

  if (maxShare >= 0.5) return "midday_burst";

  const maxGap = gaps.length ? Math.max(...gaps) : 0;
  if (maxShare <= 0.4 && avgGap > 0 && maxGap <= avgGap * 3) {
    return "steady";
  }

  return "steady";
}

export function findSteepestSegment(
  points: SparklinePoint[],
  windowTrades = 3,
  minShareOfTotal = 0.3,
): SteepestSegment | null {
  if (windowTrades <= 0) return null;
  const trades = points.filter((point) => point.tradeIndex >= 0);
  if (trades.length < windowTrades) return null;

  const total =
    trades[trades.length - 1].cumulativeValue -
    (points[0]?.cumulativeValue ?? 0);
  if (!Number.isFinite(total) || total <= 0) return null;

  const firstTimestamp = trades[0].timestamp;
  const lastTimestamp = trades[trades.length - 1].timestamp;
  const totalDurationHours = (lastTimestamp - firstTimestamp) / ONE_HOUR_MS;

  let best: SteepestSegment | null = null;

  for (let startIndex = 0; startIndex <= trades.length - windowTrades; startIndex += 1) {
    const endIndex = startIndex + windowTrades - 1;
    const startCumulative =
      startIndex === 0 ? points[0]?.cumulativeValue ?? 0 : trades[startIndex - 1].cumulativeValue;
    const endPoint = trades[endIndex];
    const notionalInWindow = endPoint.cumulativeValue - startCumulative;
    if (notionalInWindow <= 0) continue;

    const startTimestamp = trades[startIndex].timestamp;
    const endTimestamp = endPoint.timestamp;
    const durationMinutes = Math.max(
      (endTimestamp - startTimestamp) / ONE_MINUTE_MS,
      0,
    );
    const pacePerHour =
      durationMinutes > 0
        ? notionalInWindow / (durationMinutes / 60)
        : notionalInWindow * 60;
    const shareOfTotal = notionalInWindow / total;

    if (!best || notionalInWindow > best.notionalInWindow) {
      best = {
        startTimestamp,
        endTimestamp,
        startCumulative,
        endCumulative: endPoint.cumulativeValue,
        notionalInWindow,
        durationMinutes,
        pacePerHour,
        shareOfTotal,
      };
    }
  }

  if (!best || best.shareOfTotal < minShareOfTotal) return null;

  if (totalDurationHours > 0) {
    const averagePace = total / totalDurationHours;
    if (best.pacePerHour <= averagePace * 1.5) return null;
  }

  return best;
}

export function computeStraddleShare(trades: QuadrantTradeFlows[]): number {
  if (!trades.length) return 0;
  const totals = trades.reduce(
    (acc, trade) => {
      const notional = Number.isFinite(trade.economicNotional)
        ? Math.abs(trade.economicNotional)
        : 0;
      acc.total += notional;
      if (trade.isDeltaNeutral) acc.straddle += notional;
      return acc;
    },
    { total: 0, straddle: 0 },
  );
  if (totals.total === 0) return 0;
  return totals.straddle / totals.total;
}

export function computeStructureDecomposition(
  trades: QuadrantTradeFlows[],
): StructureDecomposition {
  let totalEconomicNotional = 0;
  let straddleNotional = 0;
  let skewNotional = 0;

  trades.forEach((trade) => {
    const notional = Number.isFinite(trade.economicNotional)
      ? Math.abs(trade.economicNotional)
      : 0;
    if (!notional) return;
    totalEconomicNotional += notional;
    if (trade.isDeltaNeutral) {
      straddleNotional += notional;
    }
    if (normalizePackageType(trade.packageType) === "RISK_REVERSAL") {
      skewNotional += notional;
    }
  });

  const outrightNotional = Math.max(totalEconomicNotional - straddleNotional, 0);
  const straddleShare =
    totalEconomicNotional > 0 ? straddleNotional / totalEconomicNotional : 0;
  const outrightShare =
    totalEconomicNotional > 0 ? outrightNotional / totalEconomicNotional : 0;
  const skewShare =
    totalEconomicNotional > 0 ? skewNotional / totalEconomicNotional : 0;

  return {
    straddleNotional,
    straddleShare,
    outrightNotional,
    outrightShare,
    skewNotional,
    skewShare,
    totalEconomicNotional,
  };
}

export const buildQuadrantSparklineData = buildDirectionalSparklineData;
export const classifySparklineShape = classifyDirectionalShape;
export const computeSparklineDomain = computeDirectionalDomain;

function countZeroCrossings(values: number[]): number {
  let crossings = 0;
  let previousSign = 0;
  values.forEach((value) => {
    const sign = Math.sign(value);
    if (sign === 0) return;
    if (previousSign !== 0 && sign !== previousSign) {
      crossings += 1;
    }
    previousSign = sign;
  });
  return crossings;
}
