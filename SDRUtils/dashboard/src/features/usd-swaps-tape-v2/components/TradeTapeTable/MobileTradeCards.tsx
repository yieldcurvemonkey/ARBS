'use client'

import type { JSX } from 'react'
import { useCallback, useEffect, useMemo, useRef } from 'react'
import { ChevronDown, ChevronRight, RefreshCw } from 'lucide-react'
import type { UsdSwapTapeRow } from '../../types'
import {
  formatDv01,
  formatExecutionWindow,
  formatNotional,
  formatRate,
} from '../../utils/format'
import { EMPTY_VALUE } from '../../constants'
import { computePackageConfidence } from '../../utils/packageConfidence'
import { computePackageAdjustedDv01 } from '../../utils/packageAdjustedDv01'
import { perLegLabel } from './TapeLabelCell.helpers'
import type { DisplayRow } from '../../utils/applyOverrides'
import {
  packageTypeBadgeClassName,
  packageTypeDisplayLabel,
} from './columns.helpers'
import { LifecyclePills, EconomicClassBadge } from './RowBadges'
import type { MetricMode } from './columns'

// Row-identity key. applyOverrides can emit multiple display rows sharing one
// package_id (SPLIT explosion, DETACH remnant+legs), so package_id alone is
// not a safe React key or expand/collapse identity here. Mirrors the
// `rowKeyOf` helper in TradeTapeTable.tsx -- keep them in sync.
const rowKeyOf = (row: UsdSwapTapeRow) => (row as DisplayRow).__syntheticKey ?? row.package_id

export interface MobileTradeCardsProps {
  rows: UsdSwapTapeRow[]
  loading: boolean
  loadingMore?: boolean
  hasMore?: boolean
  onLoadMore?: () => void | Promise<void>
  expandedRows?: Record<string, boolean>
  onToggleRow?: (packageId: string) => void
  selected?: UsdSwapTapeRow[]
  onSelectionChange?: (e: { value: UsdSwapTapeRow[] }) => void
  focusedPackageId?: string | null
  onOpenManualLink?: (linkId: string) => void
  metricMode: MetricMode
}

export function MobileTradeCards(props: MobileTradeCardsProps): JSX.Element {
  const {
    rows,
    loading,
    loadingMore,
    hasMore,
    onLoadMore,
    expandedRows,
    onToggleRow,
    selected,
    onSelectionChange,
    focusedPackageId,
    onOpenManualLink,
    metricMode,
  } = props

  const selectedIds = useMemo(
    () => new Set((selected ?? []).map((r) => r.package_id)),
    [selected],
  )

  const sentinelRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    const sentinel = sentinelRef.current
    if (!sentinel || !hasMore || !onLoadMore) return
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting && !loadingMore) {
          void onLoadMore()
        }
      },
      { rootMargin: '300px' },
    )
    observer.observe(sentinel)
    return () => observer.disconnect()
  }, [hasMore, loadingMore, onLoadMore])

  const toggleSelection = useCallback(
    (row: UsdSwapTapeRow) => {
      if (!onSelectionChange || !selected) return
      const isSelected = selectedIds.has(row.package_id)
      const next = isSelected
        ? selected.filter((r) => r.package_id !== row.package_id)
        : [...selected, row]
      onSelectionChange({ value: next })
    },
    [onSelectionChange, selected, selectedIds],
  )

  if (loading && rows.length === 0) {
    return (
      <div className="flex flex-1 items-center justify-center p-8 text-slate-400">
        <RefreshCw className="mr-2 h-5 w-5 animate-spin" />
        <span className="font-mono text-sm">Loading trades…</span>
      </div>
    )
  }

  if (rows.length === 0) {
    return (
      <div className="flex flex-1 items-center justify-center p-8 font-mono text-sm text-slate-500">
        No trades match the current filters.
      </div>
    )
  }

  return (
    <div className="flex-1 space-y-2 overflow-auto px-2 pb-4 pt-2">
      {rows.map((row) => (
        <TradeCard
          key={rowKeyOf(row)}
          row={row}
          isExpanded={!!expandedRows?.[rowKeyOf(row)]}
          isSelected={selectedIds.has(row.package_id)}
          isFocused={focusedPackageId === row.package_id}
          onToggleExpand={() => onToggleRow?.(rowKeyOf(row))}
          onToggleSelect={() => toggleSelection(row)}
          onOpenManualLink={onOpenManualLink}
          metricMode={metricMode}
        />
      ))}
      <div ref={sentinelRef} className="h-px" />
      {loadingMore && (
        <div className="flex items-center justify-center gap-2 py-3 text-xs text-slate-400">
          <RefreshCw className="h-3 w-3 animate-spin" />
          Loading more…
        </div>
      )}
    </div>
  )
}

function firstLeg(row: UsdSwapTapeRow): Record<string, unknown> | undefined {
  return row.legs_json?.[0] as Record<string, unknown> | undefined
}

function TradeCard({
  row,
  isExpanded,
  isSelected,
  isFocused,
  onToggleExpand,
  onToggleSelect,
  onOpenManualLink,
  metricMode,
}: {
  row: UsdSwapTapeRow
  isExpanded: boolean
  isSelected: boolean
  isFocused: boolean
  onToggleExpand: () => void
  onToggleSelect: () => void
  onOpenManualLink?: (linkId: string) => void
  metricMode: MetricMode
}): JSX.Element {
  const leg0 = firstLeg(row)
  const venue = String(
    row.venue ?? leg0?.venue ?? '',
  ).toUpperCase()
  const isIdb = venue === 'D2D'
  const isCusty = venue === 'D2C'
  const platformText =
    row.platform_identifier ??
    (leg0?.platform_identifier as string | undefined) ??
    EMPTY_VALUE

  const conf = computePackageConfidence(row)
  const displayedType = conf.inferredType ?? row.package_type

  const manualLinkId = row.manual_link_id || row.manual_package_id || null
  const hasLegs = (row.legs_json ?? []).length > 0

  let metricValue: string
  let metricLabel: string
  if (metricMode === 'dv01') {
    metricValue = formatDv01(row.total_risk)
    metricLabel = 'DV01'
  } else if (metricMode === 'pa_dv01') {
    metricValue = formatDv01(computePackageAdjustedDv01(row))
    metricLabel = 'PA-DV01'
  } else {
    metricValue = formatNotional(row.total_notional, { compact: true })
    metricLabel = 'Notl'
  }

  const dotColor = isIdb
    ? '#38bdf8'
    : isCusty
      ? '#f59e0b'
      : '#64748b'
  const platformTone = isIdb
    ? 'text-sky-200'
    : isCusty
      ? 'text-amber-200'
      : 'text-slate-400'

  return (
    <div
      className={[
        'rounded-lg border p-3 transition-colors',
        isFocused
          ? 'border-indigo-500/60 bg-indigo-950/30 ring-1 ring-indigo-500/30'
          : isSelected
            ? 'border-sky-500/40 bg-sky-950/20'
            : manualLinkId
              ? 'border-amber-500/30 bg-amber-950/10'
              : 'border-slate-800 bg-slate-900/80',
      ].join(' ')}
    >
      {/* Row 1: Time + Platform + Lifecycle */}
      <div className="flex items-center gap-2">
        <span className="shrink-0 font-mono text-xs text-slate-300">
          {formatExecutionWindow(row.execution_start, row.execution_end)}
        </span>
        <span className="inline-flex shrink-0 items-center gap-1 font-mono text-xs">
          <span
            className="inline-block h-1.5 w-1.5 rounded-full"
            style={{ backgroundColor: dotColor }}
          />
          <span className={platformTone}>{platformText}</span>
        </span>
        <div className="flex-1" />
        <LifecyclePills row={row} />
      </div>

      {/* Row 2: Tape label */}
      <div className="mt-1.5 truncate font-mono text-sm font-medium leading-snug text-slate-100">
        {row.tape_label ?? EMPTY_VALUE}
      </div>

      {/* Row 3: Metrics */}
      <div className="mt-1.5 flex items-center gap-3 font-mono text-xs">
        <span className="text-slate-200">
          <span className="text-slate-500">{metricLabel} </span>
          {metricValue}
        </span>
        <span className="text-slate-200">
          <span className="text-slate-500">Rate </span>
          {formatRate(row.weighted_fixed_rate)}
        </span>
        <EconomicClassBadge row={row} />
      </div>

      {/* Row 4: Badges + Actions */}
      <div className="mt-2 flex items-center justify-between">
        <div className="flex min-w-0 items-center gap-1.5">
          <span
            className={`inline-flex shrink-0 items-center rounded-full border px-2 py-0.5 text-[10px] font-semibold ${packageTypeBadgeClassName(displayedType)}`}
          >
            {packageTypeDisplayLabel(displayedType)}
          </span>
          {manualLinkId && onOpenManualLink && (
            <button
              type="button"
              onClick={() => onOpenManualLink(manualLinkId)}
              className="min-h-[44px] shrink-0 rounded border border-amber-600/50 bg-amber-900/30 px-2 py-1 text-[10px] text-amber-200 active:bg-amber-800/40"
            >
              Linked
            </button>
          )}
        </div>
        <div className="flex items-center gap-2">
          {hasLegs && (
            <button
              type="button"
              onClick={onToggleExpand}
              className="inline-flex h-11 w-11 items-center justify-center rounded-lg border border-slate-700 text-slate-300 active:bg-slate-700"
              aria-label={isExpanded ? 'Collapse legs' : 'Expand legs'}
            >
              {isExpanded ? (
                <ChevronDown className="h-5 w-5" />
              ) : (
                <ChevronRight className="h-5 w-5" />
              )}
            </button>
          )}
          <button
            type="button"
            onClick={onToggleSelect}
            className={[
              'inline-flex h-11 w-11 items-center justify-center rounded-lg border text-sm',
              isSelected
                ? 'border-sky-500 bg-sky-900/40 text-sky-200'
                : 'border-slate-700 text-slate-400 active:bg-slate-700',
            ].join(' ')}
            aria-label={isSelected ? 'Deselect trade' : 'Select trade'}
          >
            {isSelected ? '✓' : '○'}
          </button>
        </div>
      </div>

      {/* Expanded: Leg details */}
      {isExpanded && hasLegs && (
        <div className="mt-2 space-y-1.5 border-t border-slate-800 pt-2">
          {(row.legs_json ?? []).map((rawLeg, i) => {
            const leg = rawLeg as Record<string, unknown>
            return (
              <div
                key={String(leg.trade_id ?? i)}
                className="rounded bg-slate-950/60 p-2"
              >
                <div className="font-mono text-xs text-slate-200">
                  {perLegLabel(leg) || `Leg ${i + 1}`}
                </div>
                <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 font-mono text-[11px] text-slate-400">
                  <span>
                    Rate:{' '}
                    {formatRate(leg.fixed_rate as number | null | undefined)}
                  </span>
                  <span>
                    Not:{' '}
                    {formatNotional(
                      leg.notional_amount as number | null | undefined,
                      { compact: true },
                    )}
                  </span>
                  {leg.dv01 != null && (
                    <span>DV01: {formatDv01(leg.dv01 as number)}</span>
                  )}
                  {leg.ccp != null && (
                    <span>CCP: {String(leg.ccp)}</span>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
