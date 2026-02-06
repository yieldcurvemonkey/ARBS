import { describe, expect, it } from "@jest/globals";
import type { QuadrantTrade } from "../quadrantSparkline.types";
import {
  buildQuadrantSparklineData,
  classifySparklineShape,
  computeSparklineDomain,
  findPeakImbalance,
} from "../quadrantSparkline.utils";

const makeTrade = (
  overrides: Partial<QuadrantTrade> = {},
): QuadrantTrade => ({
  packageId: "pkg-1",
  executionTimestamp: 1,
  signedNotional: 0,
  platform: "idb",
  ...overrides,
});

const buildPoints = (values: number[]) =>
  values.map((value, index) => ({
    timestamp: index,
    cumulativeNet: value,
    tradeIndex: index - 1,
    tradeNotional: 0,
    tradeId: `t-${index}`,
  }));

describe("quadrantSparkline.utils", () => {
  it("builds empty sparkline data", () => {
    expect(buildQuadrantSparklineData([])).toEqual([]);
  });

  it("builds sparkline data for a single payer trade", () => {
    const trades = [
      makeTrade({ executionTimestamp: 1000, signedNotional: 50_000_000 }),
    ];
    const points = buildQuadrantSparklineData(trades);
    expect(points).toHaveLength(2);
    expect(points[0].cumulativeNet).toBe(0);
    expect(points[0].timestamp).toBe(1000);
    expect(points[1].cumulativeNet).toBe(50_000_000);
  });

  it("builds sparkline data for a single receiver trade", () => {
    const trades = [
      makeTrade({ executionTimestamp: 2000, signedNotional: -50_000_000 }),
    ];
    const points = buildQuadrantSparklineData(trades);
    expect(points).toHaveLength(2);
    expect(points[0].cumulativeNet).toBe(0);
    expect(points[1].cumulativeNet).toBe(-50_000_000);
  });

  it("accumulates multiple trades in order", () => {
    const trades = [
      makeTrade({ executionTimestamp: 1000, signedNotional: -50_000_000 }),
      makeTrade({ executionTimestamp: 2000, signedNotional: -25_000_000 }),
      makeTrade({ executionTimestamp: 3000, signedNotional: 50_000_000 }),
    ];
    const points = buildQuadrantSparklineData(trades);
    expect(points.map((point) => point.cumulativeNet)).toEqual([
      0,
      -50_000_000,
      -75_000_000,
      -25_000_000,
    ]);
  });

  it("sorts trades by timestamp before computing cumulative", () => {
    const trades = [
      makeTrade({ executionTimestamp: 3000, signedNotional: 10 }),
      makeTrade({ executionTimestamp: 1000, signedNotional: 20 }),
      makeTrade({ executionTimestamp: 2000, signedNotional: -5 }),
    ];
    const points = buildQuadrantSparklineData(trades);
    expect(points.slice(1).map((point) => point.timestamp)).toEqual([
      1000,
      2000,
      3000,
    ]);
    expect(points.map((point) => point.cumulativeNet)).toEqual([0, 20, 15, 25]);
  });

  it("keeps stable order when timestamps match", () => {
    const trades = [
      makeTrade({ executionTimestamp: 1000, signedNotional: 10 }),
      makeTrade({ executionTimestamp: 1000, signedNotional: -5 }),
      makeTrade({ executionTimestamp: 1000, signedNotional: 20 }),
    ];
    const points = buildQuadrantSparklineData(trades);
    expect(points.slice(1).map((point) => point.cumulativeNet)).toEqual([
      10,
      5,
      25,
    ]);
  });

  it("finds peak imbalance when reversion is large", () => {
    const points = buildPoints([0, -100, -400, -300, -225]);
    const peak = findPeakImbalance(points);
    expect(peak?.cumulativeNet).toBe(-400);
  });

  it("returns null when peak equals final", () => {
    const points = buildPoints([0, -50, -100, -200]);
    expect(findPeakImbalance(points)).toBeNull();
  });

  it("returns null for small reversions", () => {
    const points = buildPoints([0, -100, -130, -100]);
    expect(findPeakImbalance(points)).toBeNull();
  });

  it("detects payer peak reversion", () => {
    const points = buildPoints([0, 500, 300, 200]);
    const peak = findPeakImbalance(points);
    expect(peak?.cumulativeNet).toBe(500);
  });

  it("returns null when no points", () => {
    expect(findPeakImbalance([])).toBeNull();
  });

  it("computes sparkline domain with padding", () => {
    const negativeDomain = computeSparklineDomain(
      buildPoints([-200, -100, -50]),
    );
    expect(negativeDomain[0]).toBeCloseTo(-220, 5);
    expect(negativeDomain[1]).toBeCloseTo(77, 5);

    const positiveDomain = computeSparklineDomain(buildPoints([50, 100, 300]));
    expect(positiveDomain[0]).toBeCloseTo(-115.5, 5);
    expect(positiveDomain[1]).toBeCloseTo(330, 5);

    expect(computeSparklineDomain(buildPoints([-100, 200]))).toEqual([
      -110,
      220,
    ]);
  });

  it("returns safe domain for empty or zero", () => {
    expect(computeSparklineDomain(buildPoints([0]))).toEqual([-1, 1]);
    expect(computeSparklineDomain([])).toEqual([-1, 1]);
  });

  it("classifies empty and single trade", () => {
    expect(classifySparklineShape([])).toBe("empty");
    expect(classifySparklineShape(buildPoints([0, -50]))).toBe("single_trade");
  });

  it("classifies monotonic receiver and payer", () => {
    expect(
      classifySparklineShape(buildPoints([0, -50, -100, -200, -300])),
    ).toBe("monotonic_receiver");
    expect(classifySparklineShape(buildPoints([0, 50, 100, 200]))).toBe(
      "monotonic_payer",
    );
  });

  it("classifies burst then flat", () => {
    expect(
      classifySparklineShape(buildPoints([0, -300, -310, -305, -300])),
    ).toBe("burst_then_flat");
  });

  it("classifies oscillating", () => {
    expect(
      classifySparklineShape(buildPoints([0, 50, -30, 40, -10])),
    ).toBe("oscillating");
  });

  it("classifies reversal", () => {
    expect(
      classifySparklineShape(buildPoints([0, -400, -350, -200])),
    ).toBe("reversal");
  });
});
