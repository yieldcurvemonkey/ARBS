import { describe, expect, it } from "@jest/globals";
import {
  buildDiagnosticsFromRows,
  computeDaysBetweenDateKeys,
  parsePointGridFlowParams,
  toEasternDateKey,
} from "./point-grid-flow.logic";

describe("point-grid-flow route helpers", () => {
  it("parses platform filter behavior and rejects invalid platform", () => {
    const idbParams = parsePointGridFlowParams(
      new URLSearchParams("platform=idb"),
      new Date("2026-02-26T14:00:00Z"),
    );
    expect(idbParams.ok).toBe(true);
    if (idbParams.ok) {
      expect(idbParams.value.platform).toBe("idb");
    }

    const invalidParams = parsePointGridFlowParams(
      new URLSearchParams("platform=desk"),
      new Date("2026-02-26T14:00:00Z"),
    );
    expect(invalidParams.ok).toBe(false);
  });

  it("uses ET date bucketing around UTC midnight boundaries", () => {
    expect(toEasternDateKey(new Date("2026-02-26T03:30:00Z"))).toBe("2026-02-25");
    expect(toEasternDateKey(new Date("2026-02-26T05:30:00Z"))).toBe("2026-02-26");
  });

  it("applies default lookback and computes recency days", () => {
    const parsed = parsePointGridFlowParams(
      new URLSearchParams(),
      new Date("2026-02-26T14:00:00Z"),
    );
    expect(parsed.ok).toBe(true);
    if (!parsed.ok) return;
    expect(parsed.value.asOfDate).toBe("2026-02-25");
    expect(parsed.value.lookbackStartDate).toBe("2025-02-25");
    expect(computeDaysBetweenDateKeys("2026-02-25", "2026-02-15")).toBe(10);
  });

  it("builds diagnostics payload from query rows", () => {
    const diagnostics = buildDiagnosticsFromRows([
      {
        report_date: "2026-02-25",
        previous_session_date: "2026-02-24",
        baseline_dates: ["2026-02-24", "2026-02-21"],
        baseline_sessions_used: "2",
        lookback_trade_count: "42",
        unmapped_trade_count: "7",
      },
    ] as any);
    expect(diagnostics.reportDate).toBe("2026-02-25");
    expect(diagnostics.previousSessionDate).toBe("2026-02-24");
    expect(diagnostics.baselineDates).toEqual(["2026-02-24", "2026-02-21"]);
    expect(diagnostics.baselineSessionsUsed).toBe(2);
    expect(diagnostics.lookbackTradeCount).toBe(42);
    expect(diagnostics.unmappedTradeCount).toBe(7);
  });
});
