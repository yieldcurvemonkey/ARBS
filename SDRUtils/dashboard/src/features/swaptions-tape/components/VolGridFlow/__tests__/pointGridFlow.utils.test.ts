import { describe, expect, it } from "@jest/globals";
import {
  assignNearestPoint,
  buildPointSignal,
  computeWeightedLogDistance,
  computeZeroFilledAverage,
} from "../pointGridFlow.utils";

describe("pointGridFlow.utils", () => {
  it("assignNearestPoint resolves exact node hits", () => {
    const assigned = assignNearestPoint(10, 10);
    expect(assigned?.pointKey).toBe("10Yx10Y");
  });

  it("assignNearestPoint resolves between-node values to nearest point", () => {
    const assigned = assignNearestPoint(7, 7, [
      {
        pointKey: "1Yx1Y",
        expiryLabel: "1Y",
        tenorLabel: "1Y",
        expiryYears: 1,
        tenorYears: 1,
      },
      {
        pointKey: "5Yx5Y",
        expiryLabel: "5Y",
        tenorLabel: "5Y",
        expiryYears: 5,
        tenorYears: 5,
      },
      {
        pointKey: "10Yx10Y",
        expiryLabel: "10Y",
        tenorLabel: "10Y",
        expiryYears: 10,
        tenorYears: 10,
      },
    ]);
    expect(assigned?.pointKey).toBe("5Yx5Y");
  });

  it("computeWeightedLogDistance applies tenor-weight damping", () => {
    const tenorMove = computeWeightedLogDistance(10, 10, 10, 20);
    const expiryMove = computeWeightedLogDistance(10, 10, 5, 10);
    expect(tenorMove).toBeGreaterThan(0);
    expect(expiryMove).toBeGreaterThan(0);
    expect(tenorMove).toBeLessThan(expiryMove);
  });

  it("computeZeroFilledAverage zero-fills missing sessions", () => {
    const average = computeZeroFilledAverage([100, null, 50], 5);
    expect(average).toBe(30);
  });

  it("buildPointSignal classifies positive/negative/neutral", () => {
    const positive = buildPointSignal({
      reportTradeCount: 3,
      grossVs5SessionAvg: 1.8,
      daysSinceLastTrade: 1,
    });
    expect(positive.signal).toBe("positive");

    const negative = buildPointSignal({
      reportTradeCount: 1,
      grossVs5SessionAvg: 0.4,
      daysSinceLastTrade: 2,
    });
    expect(negative.signal).toBe("negative");

    const neutral = buildPointSignal({
      reportTradeCount: 1,
      grossVs5SessionAvg: 1.1,
      daysSinceLastTrade: 3,
    });
    expect(neutral.signal).toBe("neutral");
  });
});
