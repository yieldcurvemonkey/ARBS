import { describe, expect, it } from "@jest/globals";
import type { QuadrantTradeFlows, SparklinePoint } from "../quadrantSparkline.types";
import {
  buildDirectionalSparklineData,
  buildVolFlowSparklineData,
  classifyDirectionalShape,
  classifyVolFlowShape,
  computeDirectionalDomain,
  computeStraddleShare,
  findPeakImbalance,
  findSteepestSegment,
  getEconomicNotional,
  isDeltaNeutral,
} from "../quadrantSparkline.utils";

const makeTrade = (
  overrides: Partial<QuadrantTradeFlows> = {},
): QuadrantTradeFlows => ({
  packageId: "pkg-1",
  executionTimestamp: 1,
  packageType: "OUTRIGHT",
  signedNotional: 0,
  economicNotional: 0,
  isDeltaNeutral: false,
  isStraddle: false,
  platform: "idb",
  ...overrides,
});

const buildPoints = (values: number[]): SparklinePoint[] =>
  values.map((value, index) => ({
    timestamp: index,
    cumulativeValue: value,
    tradeIndex: index - 1,
    tradeValue: 0,
    tradeId: `t-${index}`,
  }));

const minute = 60 * 1000;

describe("quadrantSparkline.utils", () => {
  it("builds empty directional sparkline data", () => {
    expect(buildDirectionalSparklineData([])).toEqual([]);
  });

  it("builds directional sparkline data for a single payer trade", () => {
    const trades = [
      makeTrade({ executionTimestamp: 1000, signedNotional: 50_000_000 }),
    ];
    const points = buildDirectionalSparklineData(trades);
    expect(points).toHaveLength(2);
    expect(points[0].cumulativeValue).toBe(0);
    expect(points[0].timestamp).toBe(1000);
    expect(points[1].cumulativeValue).toBe(50_000_000);
  });

  it("builds directional sparkline data for a single receiver trade", () => {
    const trades = [
      makeTrade({ executionTimestamp: 2000, signedNotional: -50_000_000 }),
    ];
    const points = buildDirectionalSparklineData(trades);
    expect(points).toHaveLength(2);
    expect(points[0].cumulativeValue).toBe(0);
    expect(points[1].cumulativeValue).toBe(-50_000_000);
  });

  it("accumulates multiple directional trades in order", () => {
    const trades = [
      makeTrade({ executionTimestamp: 1000, signedNotional: -50_000_000 }),
      makeTrade({ executionTimestamp: 2000, signedNotional: -25_000_000 }),
      makeTrade({ executionTimestamp: 3000, signedNotional: 50_000_000 }),
    ];
    const points = buildDirectionalSparklineData(trades);
    expect(points.map((point) => point.cumulativeValue)).toEqual([
      0,
      -50_000_000,
      -75_000_000,
      -25_000_000,
    ]);
  });

  it("sorts directional trades by timestamp before computing cumulative", () => {
    const trades = [
      makeTrade({ executionTimestamp: 3000, signedNotional: 10 }),
      makeTrade({ executionTimestamp: 1000, signedNotional: 20 }),
      makeTrade({ executionTimestamp: 2000, signedNotional: -5 }),
    ];
    const points = buildDirectionalSparklineData(trades);
    expect(points.slice(1).map((point) => point.timestamp)).toEqual([
      1000,
      2000,
      3000,
    ]);
    expect(points.map((point) => point.cumulativeValue)).toEqual([0, 20, 15, 25]);
  });

  it("keeps stable order when timestamps match", () => {
    const trades = [
      makeTrade({ executionTimestamp: 1000, signedNotional: 10 }),
      makeTrade({ executionTimestamp: 1000, signedNotional: -5 }),
      makeTrade({ executionTimestamp: 1000, signedNotional: 20 }),
    ];
    const points = buildDirectionalSparklineData(trades);
    expect(points.slice(1).map((point) => point.cumulativeValue)).toEqual([
      10,
      5,
      25,
    ]);
  });

  it("finds peak imbalance when reversion is large", () => {
    const points = buildPoints([0, -100, -400, -300, -225]);
    const peak = findPeakImbalance(points);
    expect(peak?.cumulativeValue).toBe(-400);
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
    expect(peak?.cumulativeValue).toBe(500);
  });

  it("returns null when no points", () => {
    expect(findPeakImbalance([])).toBeNull();
  });

  it("computes directional domain with padding", () => {
    const negativeDomain = computeDirectionalDomain(
      buildPoints([-200, -100, -50]),
    );
    expect(negativeDomain[0]).toBeCloseTo(-220, 5);
    expect(negativeDomain[1]).toBeCloseTo(55, 5);

    const positiveDomain = computeDirectionalDomain(buildPoints([50, 100, 300]));
    expect(positiveDomain[0]).toBeCloseTo(-82.5, 5);
    expect(positiveDomain[1]).toBeCloseTo(330, 5);

    expect(computeDirectionalDomain(buildPoints([-100, 200]))).toEqual([
      -110,
      220,
    ]);
  });

  it("returns safe domain for empty or zero", () => {
    expect(computeDirectionalDomain(buildPoints([0]))).toEqual([-1, 1]);
    expect(computeDirectionalDomain([])).toEqual([-1, 1]);
  });

  it("classifies empty and single trade", () => {
    expect(classifyDirectionalShape([])).toBe("empty");
    expect(classifyDirectionalShape(buildPoints([0, -50]))).toBe("single_trade");
  });

  it("classifies monotonic receiver and payer", () => {
    expect(
      classifyDirectionalShape(buildPoints([0, -50, -100, -200, -300])),
    ).toBe("monotonic_receiver");
    expect(classifyDirectionalShape(buildPoints([0, 50, 100, 200]))).toBe(
      "monotonic_payer",
    );
  });

  it("classifies burst then flat", () => {
    expect(
      classifyDirectionalShape(buildPoints([0, -300, -310, -305, -300])),
    ).toBe("burst_then_flat");
  });

  it("classifies oscillating", () => {
    expect(
      classifyDirectionalShape(buildPoints([0, 50, -30, 40, -10])),
    ).toBe("oscillating");
  });

  it("classifies reversal", () => {
    expect(
      classifyDirectionalShape(buildPoints([0, -400, -350, -200])),
    ).toBe("reversal");
  });

  it("builds empty vol flow sparkline data", () => {
    expect(buildVolFlowSparklineData([])).toEqual([]);
  });

  it("builds vol flow data for a single outright", () => {
    const trades = [
      makeTrade({ executionTimestamp: 1000, economicNotional: 100_000_000 }),
    ];
    const points = buildVolFlowSparklineData(trades);
    expect(points).toHaveLength(2);
    expect(points[0].cumulativeValue).toBe(0);
    expect(points[1].cumulativeValue).toBe(100_000_000);
  });

  it("builds vol flow data for a single straddle", () => {
    const trades = [
      makeTrade({
        executionTimestamp: 1000,
        packageType: "STRADDLE",
        economicNotional: 360_000_000,
      }),
    ];
    const points = buildVolFlowSparklineData(trades);
    expect(points[1].cumulativeValue).toBe(360_000_000);
  });

  it("accumulates mixed vol flow trades", () => {
    const trades = [
      makeTrade({ executionTimestamp: 1000, economicNotional: 100_000_000 }),
      makeTrade({
        executionTimestamp: 2000,
        packageType: "STRADDLE",
        economicNotional: 360_000_000,
      }),
    ];
    const points = buildVolFlowSparklineData(trades);
    expect(points.map((point) => point.cumulativeValue)).toEqual([
      0,
      100_000_000,
      460_000_000,
    ]);
  });

  it("keeps vol flow cumulative monotonic", () => {
    const trades = Array.from({ length: 5 }, (_, index) =>
      makeTrade({
        packageId: `pkg-${index}`,
        executionTimestamp: index * 1000,
        economicNotional: 50_000_000,
      }),
    );
    const points = buildVolFlowSparklineData(trades);
    for (let i = 1; i < points.length; i += 1) {
      expect(points[i].cumulativeValue).toBeGreaterThanOrEqual(
        points[i - 1].cumulativeValue,
      );
    }
  });

  it("sorts vol flow trades by timestamp", () => {
    const trades = [
      makeTrade({ executionTimestamp: 3000, economicNotional: 10 }),
      makeTrade({ executionTimestamp: 1000, economicNotional: 20 }),
      makeTrade({ executionTimestamp: 2000, economicNotional: 5 }),
    ];
    const points = buildVolFlowSparklineData(trades);
    expect(points.slice(1).map((point) => point.timestamp)).toEqual([
      1000,
      2000,
      3000,
    ]);
    expect(points.map((point) => point.cumulativeValue)).toEqual([0, 20, 25, 35]);
  });

  it("computes economic notional by package type", () => {
    expect(getEconomicNotional(360_000_000, "OUTRIGHT")).toBe(360_000_000);
    expect(getEconomicNotional(720_000_000, "STRADDLE")).toBe(360_000_000);
    expect(getEconomicNotional(400_000_000, "RISK_REVERSAL")).toBe(200_000_000);
    expect(getEconomicNotional(400_000_000, "VERTICAL_SPREAD_1X1")).toBe(
      200_000_000,
    );
    expect(getEconomicNotional(600_000_000, "VERTICAL_SPREAD_1X2")).toBe(
      200_000_000,
    );
    expect(getEconomicNotional(500_000_000, "EXOTIC_THING")).toBe(500_000_000);
    expect(getEconomicNotional(0, "STRADDLE")).toBe(0);
  });

  it("computes straddle share", () => {
    const allStraddles = [
      makeTrade({ economicNotional: 300, isDeltaNeutral: true }),
      makeTrade({ economicNotional: 600, isDeltaNeutral: true }),
    ];
    expect(computeStraddleShare(allStraddles)).toBeCloseTo(1, 5);

    const none = [
      makeTrade({ economicNotional: 300, isDeltaNeutral: false }),
      makeTrade({ economicNotional: 200, isDeltaNeutral: false }),
    ];
    expect(computeStraddleShare(none)).toBeCloseTo(0, 5);

    const mixed = [
      makeTrade({ economicNotional: 600, isDeltaNeutral: true }),
      makeTrade({ economicNotional: 400, isDeltaNeutral: false }),
    ];
    expect(computeStraddleShare(mixed)).toBeCloseTo(0.6, 5);
  });

  it("finds steepest segment when there is a burst", () => {
    const points = buildPoints([0, 50, 50, 50, 400, 450, 500]);
    const segment = findSteepestSegment(points);
    expect(segment).not.toBeNull();
    expect(segment?.shareOfTotal).toBeGreaterThanOrEqual(0.7);
  });

  it("returns null for uniform pace segments", () => {
    const points = buildPoints([0, 100, 200, 300, 400, 500]);
    expect(findSteepestSegment(points)).toBeNull();
  });

  it("returns null for too few trades", () => {
    const points = buildPoints([0, 500]);
    expect(findSteepestSegment(points)).toBeNull();
  });

  it("returns null for empty points", () => {
    expect(findSteepestSegment([])).toBeNull();
  });

  it("classifies empty vol flow", () => {
    expect(classifyVolFlowShape([])).toBe("empty");
  });

  it("classifies single burst vol flow", () => {
    const trades = [makeTrade({ executionTimestamp: 0, economicNotional: 500 })];
    const points = buildVolFlowSparklineData(trades);
    expect(classifyVolFlowShape(points)).toBe("single_burst");
  });

  it("classifies sparse vol flow", () => {
    const trades = [
      makeTrade({ executionTimestamp: 0, economicNotional: 100 }),
      makeTrade({ executionTimestamp: 90 * minute, economicNotional: 100 }),
      makeTrade({ executionTimestamp: 180 * minute, economicNotional: 100 }),
    ];
    const points = buildVolFlowSparklineData(trades);
    expect(classifyVolFlowShape(points)).toBe("sparse");
  });

  it("classifies front-loaded vol flow", () => {
    const trades = [
      makeTrade({ executionTimestamp: 0, economicNotional: 400 }),
      makeTrade({ executionTimestamp: 10 * minute, economicNotional: 300 }),
      makeTrade({ executionTimestamp: 45 * minute, economicNotional: 100 }),
      makeTrade({ executionTimestamp: 70 * minute, economicNotional: 100 }),
      makeTrade({ executionTimestamp: 90 * minute, economicNotional: 100 }),
    ];
    const points = buildVolFlowSparklineData(trades);
    expect(classifyVolFlowShape(points)).toBe("front_loaded");
  });

  it("classifies back-loaded vol flow", () => {
    const trades = [
      makeTrade({ executionTimestamp: 0, economicNotional: 100 }),
      makeTrade({ executionTimestamp: 20 * minute, economicNotional: 100 }),
      makeTrade({ executionTimestamp: 50 * minute, economicNotional: 100 }),
      makeTrade({ executionTimestamp: 80 * minute, economicNotional: 300 }),
      makeTrade({ executionTimestamp: 90 * minute, economicNotional: 400 }),
    ];
    const points = buildVolFlowSparklineData(trades);
    expect(classifyVolFlowShape(points)).toBe("back_loaded");
  });

  it("classifies midday burst vol flow", () => {
    const trades = [
      makeTrade({ executionTimestamp: 0, economicNotional: 100 }),
      makeTrade({ executionTimestamp: 30 * minute, economicNotional: 50 }),
      makeTrade({ executionTimestamp: 60 * minute, economicNotional: 300 }),
      makeTrade({ executionTimestamp: 70 * minute, economicNotional: 300 }),
      makeTrade({ executionTimestamp: 120 * minute, economicNotional: 50 }),
    ];
    const points = buildVolFlowSparklineData(trades);
    expect(classifyVolFlowShape(points)).toBe("midday_burst");
  });

  it("classifies steady vol flow", () => {
    const trades = [
      makeTrade({ executionTimestamp: 0, economicNotional: 100 }),
      makeTrade({ executionTimestamp: 30 * minute, economicNotional: 100 }),
      makeTrade({ executionTimestamp: 60 * minute, economicNotional: 100 }),
      makeTrade({ executionTimestamp: 90 * minute, economicNotional: 100 }),
      makeTrade({ executionTimestamp: 120 * minute, economicNotional: 100 }),
    ];
    const points = buildVolFlowSparklineData(trades);
    expect(classifyVolFlowShape(points)).toBe("steady");
  });

  it("detects delta neutral package types", () => {
    expect(isDeltaNeutral("STRADDLE")).toBe(true);
    expect(isDeltaNeutral("RISK_REVERSAL")).toBe(true);
    expect(isDeltaNeutral("CUSTY_RR_STRANGLE")).toBe(true);
    expect(isDeltaNeutral("OUTRIGHT")).toBe(false);
    expect(isDeltaNeutral("VERTICAL_SPREAD_1X1")).toBe(false);
    expect(isDeltaNeutral("VERTICAL_SPREAD_1X2")).toBe(false);
    expect(isDeltaNeutral("RECEIVER_LADDER")).toBe(false);
    expect(isDeltaNeutral("SOMETHING_NEW")).toBe(false);
  });
});
