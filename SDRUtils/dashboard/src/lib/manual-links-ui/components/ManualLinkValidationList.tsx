// ABOUTME: Inline validation-result list. Rendered inside the manual-link
// create / edit modal. One row per ManualLinkValidationItem with severity
// icon (ok / warn / error) and label + message text. Empty state is the
// "results will appear after refresh" placeholder, matching swaptions.

import * as React from 'react';
import { AlertTriangle, CheckCircle2, XCircle } from 'lucide-react';
import type { ManualLinkValidationItem } from '../types';

export interface ManualLinkValidationListProps {
  items: ManualLinkValidationItem[];
  emptyText?: string;
}

const DEFAULT_EMPTY = 'Validation results will appear after refresh.';

function statusIcon(status: ManualLinkValidationItem['status']): React.ReactElement {
  if (status === 'ok') {
    return <CheckCircle2 className="mt-0.5 h-4 w-4 text-emerald-400" />;
  }
  if (status === 'error') {
    return <XCircle className="mt-0.5 h-4 w-4 text-rose-400" />;
  }
  return <AlertTriangle className="mt-0.5 h-4 w-4 text-amber-300" />;
}

export function ManualLinkValidationList(
  props: ManualLinkValidationListProps,
): React.ReactElement {
  const { items, emptyText = DEFAULT_EMPTY } = props;
  if (!items.length) {
    return <div className="text-[11px] text-slate-400">{emptyText}</div>;
  }
  return (
    <div className="space-y-2">
      {items.map((item) => (
        <div key={item.key} className="flex items-start gap-2 text-xs">
          {statusIcon(item.status)}
          <div>
            <div className="font-semibold text-slate-200">{item.label}</div>
            <div className="text-[11px] text-slate-400">{item.message}</div>
          </div>
        </div>
      ))}
    </div>
  );
}
