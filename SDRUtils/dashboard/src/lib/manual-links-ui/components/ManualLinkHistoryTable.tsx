// ABOUTME: Renders a manual link's audit-trail history. One row per
// ManualLinkHistoryItem with action label + changed_by + changed_at,
// plus the optional change_details / previous_state diff as JSON.

import * as React from 'react';
import type { ManualLinkHistoryItem } from '../types';

export interface ManualLinkHistoryTableProps {
  history: ManualLinkHistoryItem[];
  emptyText?: string;
  formatTimestamp?: (iso: string) => string;
}

const DEFAULT_EMPTY = 'No history entries yet.';

function defaultTimestamp(iso: string): string {
  if (!iso) return '--';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toISOString().replace('T', ' ').replace(/\.\d+Z$/, 'Z');
}

export function ManualLinkHistoryTable(
  props: ManualLinkHistoryTableProps,
): React.ReactElement {
  const { history, emptyText = DEFAULT_EMPTY, formatTimestamp = defaultTimestamp } = props;
  if (!history.length) {
    return <div className="text-[11px] text-slate-400">{emptyText}</div>;
  }
  return (
    <div className="space-y-2">
      {history.map((item) => (
        <div
          key={item.history_id}
          className="rounded border border-slate-800/70 bg-slate-900/60 px-2 py-1"
        >
          <div className="flex items-center justify-between text-[11px] text-slate-200">
            <span className="font-semibold">{item.action}</span>
            <span className="text-slate-500">
              {formatTimestamp(item.changed_at)}
            </span>
          </div>
          <div className="text-[10px] text-slate-400">{item.changed_by}</div>
          {item.change_details && Object.keys(item.change_details).length > 0 ? (
            <pre className="mt-1 whitespace-pre-wrap rounded border border-slate-800 bg-slate-950/60 px-2 py-1 text-[10px] text-slate-400">
              {JSON.stringify(item.change_details, null, 2)}
            </pre>
          ) : null}
        </div>
      ))}
    </div>
  );
}
