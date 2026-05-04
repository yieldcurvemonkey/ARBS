// ABOUTME: Renders a manual link's stored metrics dictionary as a
// label/value list. Keys are humanised (underscores -> spaces); values
// pass through a formatter (default: number rounding + nullish handling).

import * as React from 'react';

export interface ManualLinkMetricsTableProps {
  metrics: Record<string, unknown> | null | undefined;
  emptyText?: string;
  formatValue?: (value: unknown) => string;
}

const DEFAULT_EMPTY = 'No metrics stored.';

function defaultFormat(value: unknown): string {
  if (value === null || value === undefined) return '--';
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) return '--';
    if (Math.abs(value) >= 1000) {
      return value.toLocaleString(undefined, {
        maximumFractionDigits: 2,
      });
    }
    return Number(value.toFixed(4)).toString();
  }
  if (typeof value === 'string') return value;
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function humaniseKey(key: string): string {
  return key.replace(/_/g, ' ');
}

export function ManualLinkMetricsTable(
  props: ManualLinkMetricsTableProps,
): React.ReactElement {
  const { metrics, emptyText = DEFAULT_EMPTY, formatValue = defaultFormat } = props;
  const entries = metrics ? Object.entries(metrics) : [];
  if (!entries.length) {
    return <div className="text-[11px] text-slate-400">{emptyText}</div>;
  }
  return (
    <div className="space-y-2">
      {entries.map(([key, value]) => (
        <div key={key} className="flex items-center justify-between">
          <span className="text-[11px] uppercase text-slate-400">
            {humaniseKey(key)}
          </span>
          <span className="font-mono">{formatValue(value)}</span>
        </div>
      ))}
    </div>
  );
}
