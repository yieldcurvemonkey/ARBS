import type {
  QuadrantTrade,
  SparklinePattern,
  SparklinePoint,
} from "./quadrantSparkline.types";

const DEFAULT_DOMAIN: [number, number] = [-1, 1];

export function buildQuadrantSparklineData(
  trades: QuadrantTrade[],
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
      cumulativeNet: 0,
      tradeIndex: -1,
      tradeNotional: 0,
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
      cumulativeNet: cumulative,
      tradeIndex: index,
      tradeNotional: signedNotional,
      tradeId: trade.packageId,
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
    .map((point) => point.cumulativeNet)
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

export function computeSparklineDomain(
  points: SparklinePoint[],
): [number, number] {
  if (!points.length) return DEFAULT_DOMAIN;
  const values = points
    .map((point) => point.cumulativeNet)
    .filter((value) => Number.isFinite(value));
  if (!values.length) return DEFAULT_DOMAIN;

  let minValue = Math.min(...values, 0);
  let maxValue = Math.max(...values, 0);
  if (minValue === 0 && maxValue === 0) return DEFAULT_DOMAIN;

  const minPadding = minValue < 0 ? Math.abs(minValue) * 0.1 : 0;
  const maxPadding = maxValue > 0 ? Math.abs(maxValue) * 0.1 : 0;
  minValue -= minPadding;
  maxValue += maxPadding;

  const oppositePaddingRatio = 0.35;
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

export function classifySparklineShape(
  points: SparklinePoint[],
): SparklinePattern {
  if (!points.length) return "empty";
  if (points.length === 1) return "empty";

  const tradeCount = Math.max(points.length - 1, 0);
  if (tradeCount === 0) return "empty";
  if (tradeCount === 1) return "single_trade";

  const values = points.map((point) => point.cumulativeNet);
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
