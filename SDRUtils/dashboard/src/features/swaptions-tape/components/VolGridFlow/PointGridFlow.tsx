import { useMemo, useState } from "react";
import { usePointGridFlow } from "./pointGridFlow.hooks";
import type {
  PointGridPlatform,
  PointRow,
  PointSignal,
} from "./pointGridFlow.types";
import {
  POINT_GRID_EXPIRY_NODES,
  POINT_GRID_TENOR_NODES,
  signalToneClasses,
} from "./pointGridFlow.utils";

export type PointGridFlowFormatters = {
  formatNotional: (value: number | null | undefined) => string;
  formatRate: (value: number | null | undefined, decimals?: number) => string;
  formatCount: (value: number | null | undefined) => string;
};

type PointGridFlowProps = {
  platform: PointGridPlatform;
  excludeLargeCustyNotional: boolean;
  formatters: PointGridFlowFormatters;
  asOfDate?: string;
};

type SortKey =
  | "pointKey"
  | "daysSinceLastTrade"
  | "reportBpvol"
  | "reportPremium"
  | "bpvol1dChange"
  | "avgPremium1dChange"
  | "reportGross"
  | "avg5Gross"
  | "grossVs5SessionAvg"
  | "signal";

function signalRank(signal: PointSignal): number {
  if (signal === "positive") return 3;
  if (signal === "neutral") return 2;
  return 1;
}

function formatDateOrDash(value: string | null | undefined): string {
  if (!value) return "--";
  return value;
}

function formatRatio(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return "--";
  }
  return `${value.toFixed(2)}x`;
}

function formatSignedRate(
  value: number | null | undefined,
  formatRate: (input: number, decimals?: number) => string,
  decimals = 2,
): string {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return "--";
  }
  const numeric = Number(value);
  const sign = numeric > 0 ? "+" : numeric < 0 ? "-" : "";
  return `${sign}${formatRate(Math.abs(numeric), decimals)}`;
}

function formatSignedNotional(
  value: number | null | undefined,
  formatNotional: (input: number) => string,
): string {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return "--";
  }
  const numeric = Number(value);
  const sign = numeric > 0 ? "+" : numeric < 0 ? "-" : "";
  return `${sign}${formatNotional(Math.abs(numeric))}`;
}

function deltaToneClass(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return "text-slate-500";
  }
  if (value > 0) return "text-emerald-300";
  if (value < 0) return "text-rose-300";
  return "text-slate-300";
}

export function PointGridFlow({
  platform,
  excludeLargeCustyNotional,
  formatters,
  asOfDate,
}: PointGridFlowProps) {
  const { data, isLoading, error } = usePointGridFlow({
    platform,
    asOfDate,
    excludeLargeCustyNotional,
  });
  const [selectedPointKey, setSelectedPointKey] = useState<string | null>(null);
  const [sortKey, setSortKey] = useState<SortKey>("grossVs5SessionAvg");
  const [sortDirection, setSortDirection] = useState<"asc" | "desc">("desc");

  const rowByPointKey = useMemo(() => {
    const map = new Map<string, PointRow>();
    (data?.rows || []).forEach((row) => map.set(row.pointKey, row));
    return map;
  }, [data?.rows]);

  const sortedRows = useMemo(() => {
    const rows = [...(data?.rows || [])];
    rows.sort((left, right) => {
      const dir = sortDirection === "asc" ? 1 : -1;
      if (sortKey === "pointKey") {
        return left.pointKey.localeCompare(right.pointKey) * dir;
      }
      if (sortKey === "daysSinceLastTrade") {
        const leftValue = left.daysSinceLastTrade ?? Number.POSITIVE_INFINITY;
        const rightValue = right.daysSinceLastTrade ?? Number.POSITIVE_INFINITY;
        return (leftValue - rightValue) * dir;
      }
      if (sortKey === "reportBpvol") {
        const leftValue = left.reportDate.avgBpvolYr ?? Number.NEGATIVE_INFINITY;
        const rightValue = right.reportDate.avgBpvolYr ?? Number.NEGATIVE_INFINITY;
        return (leftValue - rightValue) * dir;
      }
      if (sortKey === "reportPremium") {
        const leftValue = left.reportDate.avgPremium ?? Number.NEGATIVE_INFINITY;
        const rightValue = right.reportDate.avgPremium ?? Number.NEGATIVE_INFINITY;
        return (leftValue - rightValue) * dir;
      }
      if (sortKey === "bpvol1dChange") {
        const leftValue = left.bpvol1dChange ?? Number.NEGATIVE_INFINITY;
        const rightValue = right.bpvol1dChange ?? Number.NEGATIVE_INFINITY;
        return (leftValue - rightValue) * dir;
      }
      if (sortKey === "avgPremium1dChange") {
        const leftValue = left.avgPremium1dChange ?? Number.NEGATIVE_INFINITY;
        const rightValue = right.avgPremium1dChange ?? Number.NEGATIVE_INFINITY;
        return (leftValue - rightValue) * dir;
      }
      if (sortKey === "reportGross") {
        return (left.reportDate.grossNotional - right.reportDate.grossNotional) * dir;
      }
      if (sortKey === "avg5Gross") {
        return (left.avg5Sessions.grossNotional - right.avg5Sessions.grossNotional) * dir;
      }
      if (sortKey === "grossVs5SessionAvg") {
        const leftValue = left.grossVs5SessionAvg ?? Number.NEGATIVE_INFINITY;
        const rightValue = right.grossVs5SessionAvg ?? Number.NEGATIVE_INFINITY;
        return (leftValue - rightValue) * dir;
      }
      const leftRank = signalRank(left.signal);
      const rightRank = signalRank(right.signal);
      return (leftRank - rightRank) * dir;
    });
    return rows;
  }, [data?.rows, sortDirection, sortKey]);

  const setSort = (nextSortKey: SortKey) => {
    if (sortKey === nextSortKey) {
      setSortDirection((prev) => (prev === "asc" ? "desc" : "asc"));
      return;
    }
    setSortKey(nextSortKey);
    setSortDirection(nextSortKey === "pointKey" ? "asc" : "desc");
  };

  const summary = data?.summary;
  const diagnostics = data?.diagnostics;
  const meta = data?.meta;
  const selectedRow =
    selectedPointKey !== null ? rowByPointKey.get(selectedPointKey) ?? null : null;

  return (
    <div className="mt-3 rounded border border-slate-800 bg-slate-950/40 p-3 text-[11px] text-slate-200">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="text-[11px] uppercase tracking-wide text-slate-400">
          Grid Points ({platform.toUpperCase()})
        </div>
        {meta && (
          <div className="text-[10px] text-slate-500">
            As-of {meta.asOfDate} ET {"\u00b7"} Baseline {meta.baselineSessionsUsed}/
            {meta.avgSessions} sessions
          </div>
        )}
      </div>

      {isLoading && !data && (
        <div className="mt-3 text-xs text-slate-400">Loading point-level flow...</div>
      )}
      {error && (
        <div className="mt-3 rounded border border-amber-700/50 bg-amber-900/20 p-2 text-xs text-amber-200">
          {error.message || "Failed to load point-level flow."}
        </div>
      )}
      {!isLoading && !error && data && !data.rows.length && (
        <div className="mt-3 text-xs text-slate-400">No point-level rows available.</div>
      )}

      {data && data.rows.length > 0 && (
        <>
          <div className="mt-3 grid gap-2 md:grid-cols-3 lg:grid-cols-6">
            <div className="rounded border border-emerald-700/40 bg-emerald-900/20 p-2">
              <div className="text-[10px] uppercase tracking-wide text-emerald-200/80">
                Positive
              </div>
              <div className="mt-1 font-mono text-sm text-emerald-100">
                {formatters.formatCount(summary?.positiveCount)}
              </div>
            </div>
            <div className="rounded border border-rose-700/40 bg-rose-900/20 p-2">
              <div className="text-[10px] uppercase tracking-wide text-rose-200/80">
                Negative
              </div>
              <div className="mt-1 font-mono text-sm text-rose-100">
                {formatters.formatCount(summary?.negativeCount)}
              </div>
            </div>
            <div className="rounded border border-slate-700 bg-slate-900/40 p-2">
              <div className="text-[10px] uppercase tracking-wide text-slate-400">
                Neutral
              </div>
              <div className="mt-1 font-mono text-sm text-slate-200">
                {formatters.formatCount(summary?.neutralCount)}
              </div>
            </div>
            <div className="rounded border border-slate-700 bg-slate-900/40 p-2">
              <div className="text-[10px] uppercase tracking-wide text-slate-400">
                Top Gross
              </div>
              <div className="mt-1 font-mono text-sm text-slate-100">
                {summary?.topGrossPoint || "--"}
              </div>
            </div>
            <div className="rounded border border-slate-700 bg-slate-900/40 p-2">
              <div className="text-[10px] uppercase tracking-wide text-slate-400">
                Top Surge
              </div>
              <div className="mt-1 font-mono text-sm text-slate-100">
                {summary?.topSurgePoint || "--"}
              </div>
            </div>
            <div className="rounded border border-slate-700 bg-slate-900/40 p-2">
              <div className="text-[10px] uppercase tracking-wide text-slate-400">
                Stalest
              </div>
              <div className="mt-1 font-mono text-sm text-slate-100">
                {summary?.stalestPoint || "--"}
              </div>
            </div>
          </div>

          <div className="mt-2 rounded border border-slate-800 bg-slate-900/35 px-2 py-1 text-[10px] text-slate-400">
            Cell metrics: current avg bpvol, current avg straddle premium, and 1d
            deltas vs previous ET session (
            {formatDateOrDash(diagnostics?.previousSessionDate)}).
          </div>

          {selectedRow && (
            <div className="mt-2 rounded border border-sky-700/50 bg-sky-900/15 p-2">
              <div className="text-[10px] uppercase tracking-wide text-sky-200/90">
                Selected {selectedRow.pointKey}
              </div>
              <div className="mt-1 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
                <div className="rounded border border-slate-700 bg-slate-950/50 px-2 py-1">
                  <div className="text-[9px] uppercase tracking-wide text-slate-500">
                    Current bpvol
                  </div>
                  <div className="font-mono text-slate-100">
                    {formatters.formatRate(selectedRow.reportDate.avgBpvolYr, 2)}
                  </div>
                </div>
                <div className="rounded border border-slate-700 bg-slate-950/50 px-2 py-1">
                  <div className="text-[9px] uppercase tracking-wide text-slate-500">
                    Current Straddle Prem
                  </div>
                  <div className="font-mono text-slate-100">
                    {formatters.formatNotional(selectedRow.reportDate.avgPremium)}
                  </div>
                </div>
                <div className="rounded border border-slate-700 bg-slate-950/50 px-2 py-1">
                  <div className="text-[9px] uppercase tracking-wide text-slate-500">
                    1D Change Vol
                  </div>
                  <div
                    className={`font-mono ${deltaToneClass(selectedRow.bpvol1dChange)}`}
                  >
                    {formatSignedRate(
                      selectedRow.bpvol1dChange,
                      formatters.formatRate,
                      2,
                    )}
                  </div>
                </div>
                <div className="rounded border border-slate-700 bg-slate-950/50 px-2 py-1">
                  <div className="text-[9px] uppercase tracking-wide text-slate-500">
                    1D Change Prem
                  </div>
                  <div
                    className={`font-mono ${deltaToneClass(
                      selectedRow.avgPremium1dChange,
                    )}`}
                  >
                    {formatSignedNotional(
                      selectedRow.avgPremium1dChange,
                      formatters.formatNotional,
                    )}
                  </div>
                </div>
              </div>
            </div>
          )}

          <div className="mt-2 text-[10px] text-slate-500">
            Report date {formatDateOrDash(diagnostics?.reportDate)} {"\u00b7"} Baseline
            dates{" "}
            {diagnostics?.baselineDates?.length
              ? diagnostics.baselineDates.join(", ")
              : "--"}{" "}
            {"\u00b7"} Lookback rows {formatters.formatCount(diagnostics?.lookbackTradeCount)}{" "}
            {"\u00b7"} Unmapped {formatters.formatCount(diagnostics?.unmappedTradeCount)}
          </div>

          <div className="mt-3 overflow-x-auto">
            <div
              className="inline-grid min-w-full gap-px rounded border border-slate-800 bg-slate-800 p-px"
              style={{
                gridTemplateColumns: `80px repeat(${POINT_GRID_TENOR_NODES.length}, minmax(128px, 1fr))`,
              }}
            >
              <div className="bg-slate-950/80 p-2 text-[10px] uppercase tracking-wide text-slate-500">
                Expiry \ Tenor
              </div>
              {POINT_GRID_TENOR_NODES.map((tenorNode) => (
                <div
                  key={tenorNode.label}
                  className="bg-slate-950/80 p-2 text-center text-[10px] font-semibold uppercase tracking-wide text-slate-300"
                >
                  {tenorNode.label}
                </div>
              ))}
              {POINT_GRID_EXPIRY_NODES.map((expiryNode) => (
                <div key={expiryNode.label} className="contents">
                  <div className="bg-slate-950/80 p-2 text-[10px] font-semibold uppercase tracking-wide text-slate-300">
                    {expiryNode.label}
                  </div>
                  {POINT_GRID_TENOR_NODES.map((tenorNode) => {
                    const pointKey = `${expiryNode.label}x${tenorNode.label}`;
                    const row = rowByPointKey.get(pointKey) ?? null;
                    const selected = selectedPointKey === pointKey;
                    const toneClass = row
                      ? signalToneClasses(row.signal, selected)
                      : "bg-slate-950/70 border-slate-800 text-slate-500";
                    return (
                      <button
                        key={pointKey}
                        type="button"
                        onClick={() =>
                          setSelectedPointKey((current) =>
                            current === pointKey ? null : pointKey,
                          )
                        }
                        className={`min-h-[76px] border px-2 py-1 text-left transition hover:border-slate-500 ${toneClass}`}
                        title={row?.signalReason || `${pointKey} has no mapped activity.`}
                      >
                        <div className="text-[10px] font-semibold">{pointKey}</div>
                        <div className="mt-0.5 grid grid-cols-2 gap-x-1 gap-y-0.5 text-[9px]">
                          <span className="text-slate-400/90">vol</span>
                          <span className="font-mono text-right">
                            {formatters.formatRate(row?.reportDate.avgBpvolYr, 2)}
                          </span>
                          <span className="text-slate-400/90">prem</span>
                          <span className="font-mono text-right">
                            {formatters.formatNotional(row?.reportDate.avgPremium)}
                          </span>
                        </div>
                        <div className="mt-0.5 grid grid-cols-2 gap-x-1 text-[9px]">
                          <span className={deltaToneClass(row?.bpvol1dChange)}>
                            dV{" "}
                            {formatSignedRate(
                              row?.bpvol1dChange,
                              formatters.formatRate,
                              2,
                            )}
                          </span>
                          <span
                            className={`text-right ${deltaToneClass(
                              row?.avgPremium1dChange,
                            )}`}
                          >
                            dP{" "}
                            {formatSignedNotional(
                              row?.avgPremium1dChange,
                              formatters.formatNotional,
                            )}
                          </span>
                        </div>
                      </button>
                    );
                  })}
                </div>
              ))}
            </div>
          </div>

          <div className="mt-3 overflow-x-auto">
            <table className="min-w-full border-collapse text-[11px]">
              <thead>
                <tr className="text-left text-[10px] uppercase tracking-wide text-slate-400">
                  <th className="border-b border-slate-800 px-2 py-1">
                    <button type="button" onClick={() => setSort("pointKey")}>
                      Point
                    </button>
                  </th>
                  <th className="border-b border-slate-800 px-2 py-1">Last Trade</th>
                  <th className="border-b border-slate-800 px-2 py-1">
                    <button type="button" onClick={() => setSort("daysSinceLastTrade")}>
                      Days Since
                    </button>
                  </th>
                  <th className="border-b border-slate-800 px-2 py-1">
                    <button type="button" onClick={() => setSort("reportBpvol")}>
                      Current bpvol
                    </button>
                  </th>
                  <th className="border-b border-slate-800 px-2 py-1">
                    <button type="button" onClick={() => setSort("reportPremium")}>
                      Current Straddle Prem
                    </button>
                  </th>
                  <th className="border-b border-slate-800 px-2 py-1">
                    <button type="button" onClick={() => setSort("bpvol1dChange")}>
                      1D Vol
                    </button>
                  </th>
                  <th className="border-b border-slate-800 px-2 py-1">
                    <button type="button" onClick={() => setSort("avgPremium1dChange")}>
                      1D Prem
                    </button>
                  </th>
                  <th className="border-b border-slate-800 px-2 py-1">
                    <button type="button" onClick={() => setSort("reportGross")}>
                      Report Gross
                    </button>
                  </th>
                  <th className="border-b border-slate-800 px-2 py-1">
                    <button type="button" onClick={() => setSort("avg5Gross")}>
                      5-Session Avg Gross
                    </button>
                  </th>
                  <th className="border-b border-slate-800 px-2 py-1">
                    <button type="button" onClick={() => setSort("grossVs5SessionAvg")}>
                      Gross vs Avg
                    </button>
                  </th>
                  <th className="border-b border-slate-800 px-2 py-1">
                    <button type="button" onClick={() => setSort("signal")}>
                      Signal
                    </button>
                  </th>
                  <th className="border-b border-slate-800 px-2 py-1">Reason</th>
                </tr>
              </thead>
              <tbody>
                {sortedRows.map((row) => {
                  const selected = row.pointKey === selectedPointKey;
                  return (
                    <tr
                      key={row.pointKey}
                      onClick={() =>
                        setSelectedPointKey((current) =>
                          current === row.pointKey ? null : row.pointKey,
                        )
                      }
                      className={`cursor-pointer border-b border-slate-900 ${
                        selected ? "bg-sky-900/15" : "hover:bg-slate-900/50"
                      }`}
                    >
                      <td className="px-2 py-1 font-mono text-slate-100">{row.pointKey}</td>
                      <td className="px-2 py-1 font-mono text-slate-300">
                        {formatDateOrDash(row.lastTradeDate)}
                      </td>
                      <td className="px-2 py-1 font-mono text-slate-300">
                        {row.daysSinceLastTrade === null
                          ? "--"
                          : formatters.formatCount(row.daysSinceLastTrade)}
                      </td>
                      <td className="px-2 py-1 font-mono text-slate-100">
                        {formatters.formatRate(row.reportDate.avgBpvolYr, 2)}
                      </td>
                      <td className="px-2 py-1 font-mono text-slate-100">
                        {formatters.formatNotional(row.reportDate.avgPremium)}
                      </td>
                      <td
                        className={`px-2 py-1 font-mono ${deltaToneClass(
                          row.bpvol1dChange,
                        )}`}
                      >
                        {formatSignedRate(row.bpvol1dChange, formatters.formatRate, 2)}
                      </td>
                      <td
                        className={`px-2 py-1 font-mono ${deltaToneClass(
                          row.avgPremium1dChange,
                        )}`}
                      >
                        {formatSignedNotional(
                          row.avgPremium1dChange,
                          formatters.formatNotional,
                        )}
                      </td>
                      <td className="px-2 py-1 font-mono text-slate-300">
                        {formatters.formatNotional(row.reportDate.grossNotional)}
                      </td>
                      <td className="px-2 py-1 font-mono text-slate-300">
                        {formatters.formatNotional(row.avg5Sessions.grossNotional)}
                      </td>
                      <td className="px-2 py-1 font-mono text-slate-100">
                        {formatRatio(row.grossVs5SessionAvg)}
                      </td>
                      <td className="px-2 py-1">
                        <span
                          className={`rounded border px-1.5 py-0.5 text-[10px] uppercase tracking-wide ${
                            row.signal === "positive"
                              ? "border-emerald-600/60 bg-emerald-900/30 text-emerald-100"
                              : row.signal === "negative"
                                ? "border-rose-600/60 bg-rose-900/30 text-rose-100"
                                : "border-slate-700 bg-slate-900 text-slate-200"
                          }`}
                        >
                          {row.signal}
                        </span>
                      </td>
                      <td className="px-2 py-1 text-slate-300">{row.signalReason}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
