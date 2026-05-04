// ABOUTME: Row-level chip for manually-linked tape rows. Colour is derived
// deterministically from linkId so all rows in one link group share a
// colour. Click opens the detail modal via onClick(linkId). Renders as a
// <button> when onClick is provided and a static <span> otherwise (e.g. for
// rows with a manual_package_id but no individual link).
//
// Prop contract (kept stable across consumers - any breaking change here
// requires updating both swaptions-tape and usd-swaps-tape-v2 together):
//   linkId          - the manual link id (or '' when only a package is set)
//   manualPackageId - human-readable package id for the trailing label
//   sourceLabel     - "Manual" | "Hybrid" | other consumer label
//   onClick         - optional handler; receives linkId (defaults to a span)
//   showConnector   - when true, render the up/down hairlines used to
//                     anchor the badge between two grouped rows
//   className       - merged into the chip's own classes (consumer styling)
//   ariaLabel       - explicit aria-label override; otherwise falls back
//                     to "Manual link {linkId}" for screen-reader callers

import * as React from 'react';
import { manualLinkColor } from '../color';

export interface ManualLinkBadgeProps {
  linkId: string;
  manualPackageId?: string | null;
  sourceLabel?: string;
  onClick?: (linkId: string) => void;
  showConnector?: boolean;
  className?: string;
  ariaLabel?: string;
}

const FALLBACK_COLOUR = '#64748b';
const BASE_CLASS =
  'inline-flex items-center gap-2 rounded-full border border-slate-700 bg-slate-900/60 px-2 py-0.5 text-[10px] uppercase tracking-wide text-slate-200';

export function ManualLinkBadge(props: ManualLinkBadgeProps): React.ReactElement {
  const {
    linkId,
    manualPackageId,
    sourceLabel = 'Manual',
    onClick,
    showConnector = false,
    className,
    ariaLabel,
  } = props;
  const colour = manualLinkColor(linkId) ?? FALLBACK_COLOUR;
  const positionClass = showConnector ? 'relative z-10' : '';
  const positionStyle = showConnector
    ? ({ transform: 'translateY(50%)' } as React.CSSProperties)
    : undefined;
  const mergedClass = [
    BASE_CLASS,
    positionClass,
    onClick ? 'hover:border-slate-500' : '',
    className ?? '',
  ]
    .filter(Boolean)
    .join(' ');

  const inner = (
    <>
      {showConnector ? (
        <>
          <span
            className="pointer-events-none absolute left-1/2 -top-2 h-2 w-px -translate-x-1/2 bg-slate-300/70"
            aria-hidden="true"
          />
          <span
            className="pointer-events-none absolute left-1/2 -bottom-2 h-2 w-px -translate-x-1/2 bg-slate-300/70"
            aria-hidden="true"
          />
        </>
      ) : null}
      <span
        data-testid="manual-link-dot"
        className="h-2 w-2 rounded-full"
        style={{ backgroundColor: colour }}
      />
      <span>{sourceLabel}</span>
      {manualPackageId ? (
        <span className="text-slate-400">{manualPackageId}</span>
      ) : null}
    </>
  );

  if (onClick) {
    return (
      <button
        type="button"
        data-testid="manual-link-badge"
        aria-label={ariaLabel ?? `Manual link ${linkId}`}
        className={mergedClass}
        style={positionStyle}
        onClick={(event: React.MouseEvent<HTMLButtonElement>) => {
          event.stopPropagation();
          onClick(linkId);
        }}
      >
        {inner}
      </button>
    );
  }

  return (
    <span
      data-testid="manual-link-badge"
      className={mergedClass}
      style={positionStyle}
    >
      {inner}
    </span>
  );
}
