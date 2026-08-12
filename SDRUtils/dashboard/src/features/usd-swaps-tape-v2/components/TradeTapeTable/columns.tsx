'use client'
// ABOUTME: Column body templates for the main TradeTapeTable.
import type { JSX } from 'react'
import { Column } from 'primereact/column'
import type { DataTableFilterMeta } from 'primereact/datatable'
import { StickyNote } from 'lucide-react'
import { EMPTY_VALUE, PACKAGE_CONFIDENCE_TONES, RISK_HIGHLIGHT_ABS } from '../../constants'
import type { NoteTarget, UsdSwapTapeRow } from '../../types'
import {
  formatDv01,
  formatExecutionWindow,
  formatTimestampDelta,
  formatNotional,
  formatOtherLvl,
  formatRate,
  formatReportedLvl,
} from '../../utils/format'
import { computePackageConfidence } from '../../utils/packageConfidence'
import {
  BAND_WIDTH,
  DIRECTION_TONES,
  directionView,
} from '../../utils/dealerDirection'
import {
  canonicalDisplayLabel,
  canonicalSourceVariants,
} from '../../utils/canonicalDisplay'
import { computePackageAdjustedDv01 } from '../../utils/packageAdjustedDv01'
import { computeLegSummary } from './LegsSubTable.helpers'
import { derivedSpreadBp, ptsInBp, formatBp } from '../../utils/ptsScale'
import { sortLegsForDisplay } from '../../utils/legSort'
import { detectCcpSwitch } from '../../utils/ccpSwitchDetector'
import { FilterMatchMode } from 'primereact/api'
import { getFilterDisplayLabel } from './filter-utils'
import { ActionClassBadge, TapeTags } from './RowBadges'
import { tapeTagBadgesFor, qualityBadgesFor } from './RowBadges.helpers'
import { TapeLabelCell } from './TapeLabelCell'
import {
  packageIndicatorDisplay,
  packageTypeBadgeClassName,
  packageTypeDisplayLabel,
} from './columns.helpers'
import { ManualLinkBadge } from '@/lib/manual-links-ui/components/ManualLinkBadge'
import { isManualPackage } from '@/lib/manual-links-ui/predicates'
import { OverrideBadge } from './OverrideBadge'

export { rowClassName } from './columns.helpers'

// OPA sign-confidence badge color map — mirrors the Python enum EXACT > TIGHT > LOOSE > UNRESOLVED.
const CONFIDENCE_COLORS: Record<string, string> = {
  EXACT: 'bg-emerald-500/20 text-emerald-400',
  TIGHT: 'bg-emerald-500/10 text-emerald-300',
  LOOSE: 'bg-amber-500/20 text-amber-400',
  UNRESOLVED: 'bg-zinc-500/20 text-zinc-400',
}

// pg returns NUMERIC columns as strings; coerce like the format helpers do
// instead of trusting the row type's `number | null`. True-bp values can be
// tiny (a near-exact tieout is ~0.0003bp) — show 4 decimals below 0.01bp.
function spreadBpsDisplay(v: number | string | null | undefined): string | null {
  if (v == null) return null
  const n = Number(v)
  if (!Number.isFinite(n)) return null
  const digits = Math.abs(n) >= 0.01 ? 2 : 4
  return `${n.toFixed(digits)}bp`
}

// Phase 4 (Clarus design-doc §3.1 / §5.1): `pa_dv01` is the
// package-adjusted DV01 — Σ|risk| / leg-count denominator. Toggling
// rotates dv01 → pa_dv01 → notional → dv01 so traders can sanity-check
// the broker-fee-equivalent metric without cluttering the rail.
export type MetricMode = 'dv01' | 'pa_dv01' | 'notional'

type ColumnConfig = {
  selection: boolean
  /**
   * Custom body for the leading select column. When supplied, the select
   * column renders this instead of PrimeReact's built-in
   * `selectionMode="multiple"` checkbox — used by the tape to render the
   * tri-state package checkbox that drives leg-level `useTradeSelection`.
   */
  selectionBody?: (row: UsdSwapTapeRow) => JSX.Element
  expanderBody?: (row: UsdSwapTapeRow) => JSX.Element
  metricMode?: MetricMode
  onToggleMetric?: () => void
  /**
   * Current per-column filter state. Used to render a subtle "preview" line
   * under each column title (e.g. `contains "Fed"`). Editing still happens in
   * the popup overlay (filterDisplay="menu") opened via the funnel icon.
   */
  activeFilters?: DataTableFilterMeta
  /**
   * Optional click handler for the manual-link badge in the Pkg column.
   * Receives the row's manual_link_id (or manual_package_id when only the
   * package id is set). Caller (UsdSwapsTradeTape) opens the
   * ManualLinkDetailModal in response.
   */
  onOpenManualLink?: (linkId: string) => void
  /**
   * Optional click handler for the OverrideBadge in the Pkg column (manual
   * GROUP/SPLIT/DETACH override rows). Receives the row's first
   * override_map value (an override_id). Caller opens the override detail
   * view / audit panel. Wired in Task 19.
   */
  onOpenOverride?: (overrideId: string) => void
  /**
   * Optional click handler for the per-package note affordance in the Pkg
   * column. Receives a PACKAGE-scoped NoteTarget so the caller can open the
   * notes panel/modal for the row's manual package (or raw package_id when
   * no manual regrouping is active). Wired in Task 19.
   */
  onOpenNote?: (target: NoteTarget) => void
  onToggleMmsFilter?: () => void
}

function isMmsFilterActive(filters?: DataTableFilterMeta): boolean {
  if (!filters) return false
  const f = filters.package_type
  if (!f || !('value' in f)) return false
  return typeof f.value === 'string' && f.value.includes('MATCHED_MATURITY')
}

function renderHeader(label: string, summary?: string | null): JSX.Element {
  return (
    <div className="flex flex-col leading-tight">
      <span className="font-mono text-[9.5px] uppercase tracking-wider text-slate-500">
        {label}
      </span>
      {summary ? (
        <span
          className="mt-0.5 truncate font-mono text-[10px] font-normal normal-case tracking-normal text-sky-300/70"
          title={summary}
        >
          {summary}
        </span>
      ) : null}
    </div>
  )
}

function summaryFor(
  field: string,
  active: DataTableFilterMeta | undefined,
): string | null {
  if (!active) return null
  const meta = (active as Record<string, unknown>)[field]
  if (!meta) return null
  const label = getFilterDisplayLabel(meta)
  return label || null
}

function firstLeg(row: UsdSwapTapeRow) {
  return row.legs_json?.[0]
}

function displayPlatform(row: UsdSwapTapeRow): string {
  return row.platform_identifier ?? firstLeg(row)?.platform_identifier ?? EMPTY_VALUE
}

const compactFilterMenuProps = {
  filterMenuClassName: 'usd-swaps-tape-filter-menu',
  filterMenuStyle: { width: '10rem' },
  // Keep the menu compact, but allow traders to stack native PrimeReact
  // AND/OR rules within a single column filter.
  showFilterOperator: true,
  showAddButton: true,
  maxConstraints: 4,
} as const

// Match mode options for the execution_start (Time) column — includes the
// standard text modes plus date-level "after" / "before" operators so traders
// can filter to e.g. "all trades after 05/14/2026".
const TIME_FILTER_MATCH_MODE_OPTIONS = [
  { label: 'Contains', value: FilterMatchMode.CONTAINS },
  { label: 'Equals', value: FilterMatchMode.EQUALS },
  { label: 'Not equals', value: FilterMatchMode.NOT_EQUALS },
  { label: 'After (date)', value: 'dateAfter' },
  { label: 'Before (date)', value: 'dateBefore' },
] as const

export function getColumns(
  config: ColumnConfig = { selection: true },
): JSX.Element[] {
  const cols: JSX.Element[] = []
  if (config.selection) {
    cols.push(
      config.selectionBody ? (
        <Column
          key="select"
          body={config.selectionBody as any}
          headerStyle={{ width: 30 }}
          style={{ width: 30 }}
        />
      ) : (
        <Column key="select" selectionMode="multiple" headerStyle={{ width: 30 }} />
      ),
    )
  }
  if (config.expanderBody) {
    cols.push(
      <Column key="expand" body={config.expanderBody as any} style={{ width: 36 }} />,
    )
  }

  const mode: MetricMode = config.metricMode ?? 'dv01'
  const metricField =
    mode === 'dv01'
      ? 'total_risk'
      : mode === 'pa_dv01'
        ? 'package_adjusted_dv01'
        : 'total_notional'
  const metricLabel =
    mode === 'dv01' ? 'Risk' : mode === 'pa_dv01' ? 'PA-DV01' : 'Notional'
  const metricSummary = summaryFor(metricField, config.activeFilters)
  const metricHeader = (
    <div className="flex flex-col leading-tight">
      <button
        type="button"
        onClick={config.onToggleMetric}
        className="flex flex-col text-left hover:text-sky-300"
        aria-label={`toggle metric (current: ${metricLabel})`}
      >
        <span className="font-mono text-[9.5px] uppercase tracking-wider text-slate-500">
          {metricLabel} ⇅
        </span>
      </button>
      {metricSummary ? (
        <span
          className="mt-0.5 truncate font-mono text-[10px] font-normal normal-case tracking-normal text-sky-300/70"
          title={metricSummary}
        >
          {metricSummary}
        </span>
      ) : null}
    </div>
  )

  cols.push(
    <Column
      key="time"
      field="execution_start"
      filterField="execution_start"
      sortable
      filter
      {...compactFilterMenuProps}
      filterMatchModeOptions={TIME_FILTER_MATCH_MODE_OPTIONS as any}
      header={renderHeader(
        'Time',
        summaryFor('execution_start', config.activeFilters),
      )}
      body={(row: UsdSwapTapeRow) => (
        <span className="whitespace-nowrap font-mono text-[12px] text-slate-200">
          {formatExecutionWindow(row.execution_start, row.execution_end)}
        </span>
      )}
      style={{ width: 102 }}
    />,
    <Column
      key="event_time"
      field="event_start"
      filterField="event_start"
      sortable
      filter
      {...compactFilterMenuProps}
      filterMatchModeOptions={TIME_FILTER_MATCH_MODE_OPTIONS as any}
      header={renderHeader(
        'Event',
        summaryFor('event_start', config.activeFilters),
      )}
      body={(row: UsdSwapTapeRow) => {
        // Report/dissemination lag: Event timestamp (#30) − Execution (#96).
        const delta = formatTimestampDelta(row.execution_start, row.event_start)
        const muted = delta === 'live' || delta === '0s' || delta === 'unknown'
        return (
          <span className="whitespace-nowrap font-mono text-[12px] text-slate-200">
            {formatExecutionWindow(row.event_start, row.event_end)}
            <span
              className={`ml-1 rounded px-1 text-[10px] ${
                row.late_report
                  ? 'bg-amber-900/60 text-amber-300'
                  : muted
                    ? 'bg-slate-700/60 text-slate-400'
                    : 'bg-slate-700/60 text-sky-300'
              }`}
              title={`Report lag (Event − Execution): ${delta}`}
            >
              {delta}
            </span>
          </span>
        )
      }}
      style={{ width: 118 }}
    />,
    <Column
      key="action_class"
      field="economic_class_primary"
      filterField="economic_class_primary"
      filter
      sortable
      {...compactFilterMenuProps}
      header={renderHeader(
        'Action',
        summaryFor('economic_class_primary', config.activeFilters),
      )}
      body={(row: UsdSwapTapeRow) => <ActionClassBadge row={row} />}
      style={{ width: 96 }}
    />,
    <Column
      key="platform"
      field="platform_identifier"
      filterField="platform_identifier"
      filter
      {...compactFilterMenuProps}
      header={renderHeader(
        'Platform',
        summaryFor('platform_identifier', config.activeFilters),
      )}
      body={(row: UsdSwapTapeRow) => {
        const venue = String(row.venue ?? firstLeg(row)?.venue ?? '').toUpperCase()
        const platformText = displayPlatform(row)
        const isIdb = venue === 'D2D'
        const isCusty = venue === 'D2C'
        const dotColor = isIdb
          ? '#38bdf8' /* sky-400 → IDB */
          : isCusty
            ? '#f59e0b' /* amber-500 → CUSTY */
            : '#64748b' /* slate-500 fallback */
        const textTone = isIdb
          ? 'text-sky-200'
          : isCusty
            ? 'text-amber-200'
            : 'text-slate-300'
        return (
          <span
            className="inline-flex items-center gap-1.5 font-mono text-[11px]"
            title={
              isIdb
                ? 'D2D / Inter-dealer broker (IDB)'
                : isCusty
                  ? 'D2C / Customer (CUSTY)'
                  : 'Venue unknown'
            }
          >
            <span
              aria-hidden
              className="inline-block rounded-full"
              style={{ width: 6, height: 6, backgroundColor: dotColor }}
            />
            <span className={`truncate ${textTone}`}>{platformText}</span>
          </span>
        )
      }}
      style={{ width: 56 }}
    />,
    <Column
      key="pkg"
      field="package_type"
      filterField="package_type"
      filter
      {...compactFilterMenuProps}
      header={
        <div className="flex items-center gap-1">
          {renderHeader('Pkg', summaryFor('package_type', config.activeFilters))}
          <button
            type="button"
            className={`ml-0.5 rounded px-1 py-0.5 text-[9px] font-semibold leading-none transition-colors ${
              isMmsFilterActive(config.activeFilters)
                ? 'bg-teal-500/60 text-teal-100 ring-1 ring-teal-400/50'
                : 'bg-slate-700/50 text-slate-400 hover:bg-teal-900/40 hover:text-teal-300'
            }`}
            onClick={(e) => {
              e.stopPropagation()
              config.onToggleMmsFilter?.()
            }}
            title="Toggle MMS filter"
          >
            MMS
          </button>
        </div>
      }
      body={(row: UsdSwapTapeRow) => {
        const conf = computePackageConfidence(row)
        const displayedType = conf.inferredType ?? row.package_type
        const toneClass = PACKAGE_CONFIDENCE_TONES[conf.tone]
        const tooltip = conf.signals
          .map((s) => `${s.passed ? '✓' : '✗'} ${s.label}: ${s.detail}`)
          .join('\n')
        const ccpSwitch = detectCcpSwitch(row)
        const manualLinkId = row.manual_link_id || row.manual_package_id || null
        const sourceLabel =
          row.package_source?.toUpperCase?.() === 'HYBRID' ? 'Hybrid' : 'Manual'
        const firstOverrideId = row.override_map
          ? Object.values(row.override_map)[0] ?? null
          : null
        const hasNotes = !!row.has_notes || (row.notes_count ?? 0) > 0
        return (
          <div className="flex items-center gap-1">
            <span
              className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-semibold ${packageTypeBadgeClassName(displayedType)}`}
              title={
                conf.inferredType
                  ? `Original classifier tag: ${row.package_type ?? EMPTY_VALUE}\n${conf.inferredTypeReason ?? ''}`
                  : undefined
              }
            >
              {packageTypeDisplayLabel(displayedType)}
            </span>
            <span
              className={`inline-flex items-center rounded px-1 py-0.5 font-mono text-[10px] ${toneClass}`}
              data-testid={`pkg-confidence-${row.package_id}`}
              title={tooltip}
            >
              {conf.score}/{conf.total}
            </span>
            {ccpSwitch.isCcpSwitch ? (
              <span
                title={`CCP switch detected: ${ccpSwitch.fromCcp} → ${ccpSwitch.toCcp} at ${ccpSwitch.tenorYears}Y`}
                data-testid={`ccp-switch-${row.package_id}`}
                className="rounded border border-purple-500/60 bg-purple-900/40 px-1 text-[9.5px] font-semibold text-purple-200"
              >
                CCP↔
              </span>
            ) : null}
            {!row.override_type && isManualPackage(row) && manualLinkId ? (
              <ManualLinkBadge
                linkId={manualLinkId}
                manualPackageId={row.manual_package_id}
                sourceLabel={sourceLabel}
                onClick={
                  // Only wire onClick when a real manual_link_id exists,
                  // since the detail modal needs an id to fetch.
                  row.manual_link_id && config.onOpenManualLink
                    ? config.onOpenManualLink
                    : undefined
                }
              />
            ) : null}
            {row.override_type ? (
              <OverrideBadge
                overrideType={row.override_type}
                manualPackageId={row.manual_package_id}
                overrideId={firstOverrideId}
                onClick={config.onOpenOverride}
              />
            ) : null}
            {hasNotes && config.onOpenNote ? (
              <button
                type="button"
                aria-label={`notes for package ${row.package_id}`}
                title="View / add package notes"
                data-testid={`pkg-note-${row.package_id}`}
                className="inline-flex items-center rounded p-0.5 text-amber-300 hover:text-amber-200"
                onClick={(e) => {
                  e.stopPropagation()
                  config.onOpenNote?.({
                    target_type: 'PACKAGE',
                    target_id: row.manual_package_id ?? row.package_id,
                  })
                }}
              >
                <StickyNote className="h-3 w-3" />
              </button>
            ) : null}
          </div>
        )
      }}
      style={{ width: 160 }}
    />,
    <Column
      key="pkg_ind"
      field="package_indicator"
      filterField="package_indicator"
      filter
      {...compactFilterMenuProps}
      header={renderHeader(
        'Pkg Ind',
        summaryFor('package_indicator', config.activeFilters),
      )}
      body={(row: UsdSwapTapeRow) => (
        <span className="font-mono text-[11px] text-slate-300">
          {packageIndicatorDisplay(row.package_indicator)}
        </span>
      )}
      style={{ width: 74 }}
    />,
    <Column
      key="tape_label"
      field="tape_label"
      filterField="tape_label"
      sortable
      filter
      {...compactFilterMenuProps}
      header={renderHeader(
        'Tape Label',
        summaryFor('tape_label', config.activeFilters),
      )}
      body={(row: UsdSwapTapeRow) => {
        const canonicalKey =
          row.canonical_underlier_key ?? firstLeg(row)?.canonical_underlier_key ?? null
        if (!canonicalKey) {
          return <TapeLabelCell row={row} />
        }
        const label = canonicalDisplayLabel(canonicalKey)
        const variants = canonicalSourceVariants(canonicalKey)
        const tooltip =
          variants.length > 0
            ? `Canonical: ${canonicalKey} (${label})\nMatches SDR strings:\n  ${variants.join('\n  ')}`
            : `Canonical: ${canonicalKey} (${label})`
        return (
          <span
            data-canonical-key={canonicalKey}
            data-testid={`canonical-${row.package_id ?? 'row'}`}
            className="inline-block"
          >
            <TapeLabelCell row={row} />
          </span>
        )
      }}
      style={{ width: 470 }}
    />,
    <Column
      key="metric"
      field={metricField}
      filterField={metricField}
      sortable
      filter
      dataType="numeric"
      {...compactFilterMenuProps}
      header={metricHeader}
      body={(row: UsdSwapTapeRow) => {
        const display =
          mode === 'dv01'
            ? formatDv01(row.total_risk ?? null, { signNegativeOnly: true })
            : mode === 'pa_dv01'
              ? formatDv01(
                  row.package_adjusted_dv01 ?? computePackageAdjustedDv01(row),
                  { signNegativeOnly: true },
                )
              : formatNotional(row.total_notional ?? null, { compact: true })
        // Highlight large risk prints (|Risk| >= 200k, DV01 mode only) so the
        // desk's biggest tickets jump off the tape.
        const bigRisk =
          mode === 'dv01' &&
          Math.abs(row.total_risk ?? 0) >= RISK_HIGHLIGHT_ABS
        return (
          <span
            className={`block text-right font-mono text-[14px] font-bold tracking-tight ${
              bigRisk ? 'text-amber-300' : 'text-slate-50'
            }`}
          >
            {display}
          </span>
        )
      }}
      style={{ width: 76 }}
    />,
    <Column
      key="rate"
      field="weighted_fixed_rate"
      filterField="weighted_fixed_rate"
      filter
      dataType="numeric"
      {...compactFilterMenuProps}
      header={renderHeader(
        'Reported LvL',
        summaryFor('weighted_fixed_rate', config.activeFilters),
      )}
      body={(row: UsdSwapTapeRow) => (
        <span className="block text-right font-mono text-[14px] font-bold tracking-tight text-slate-50">
          {formatReportedLvl(row)}
        </span>
      )}
      style={{ width: 64 }}
    />,
    // Inferred dealer direction. Sits immediately after the reported level
    // because that is what it is inferred FROM: the printed price against a
    // repriced mid.
    //
    // RCVD (emerald) = dealer received fixed = dealer long duration.
    // PAID (rose)    = dealer paid fixed     = dealer short duration.
    // n/a  (slate)   = we declined, and the tooltip says why.
    //
    // The bar under the badge is |2p-1|, the ladder's own weight — not p.
    // At p = 0.5 it is zero, which is what a coin flip is worth.
    <Column
      key="dealer_direction"
      field="dd_dealer_direction"
      filterField="dd_dealer_direction"
      filter
      {...compactFilterMenuProps}
      header={renderHeader(
        'Dealer',
        summaryFor('dd_dealer_direction', config.activeFilters),
      )}
      body={(row: UsdSwapTapeRow) => {
        const v = directionView(row)
        return (
          <div className="flex flex-col items-center gap-0.5" title={v.title}>
            <span
              className={`inline-flex items-center rounded px-1 py-0.5 font-mono text-[10px] ${DIRECTION_TONES[v.tone]}`}
              data-testid={`dd-direction-${row.package_id}`}
              data-direction={v.known ? (v.reason ? 'ABSTAINED' : v.label) : 'UNKNOWN'}
            >
              {v.label}
            </span>
            {v.conviction != null ? (
              <span className="block h-[2px] w-8 rounded-full bg-slate-800">
                <span
                  className={`block h-[2px] rounded-full ${BAND_WIDTH[v.band]} ${
                    v.tone === 'received' ? 'bg-sky-400/70' : 'bg-amber-400/70'
                  }`}
                />
              </span>
            ) : v.reasonPhrase ? (
              <span className="max-w-[64px] truncate text-[8.5px] leading-none text-slate-500">
                {v.reason}
              </span>
            ) : null}
          </div>
        )
      }}
      style={{ width: 62 }}
    />,
    <Column
      key="other_lvl"
      field="other_lvl_reported"
      filterField="other_lvl_reported"
      filter
      {...compactFilterMenuProps}
      header={renderHeader(
        'Other Lvl',
        summaryFor('other_lvl_reported', config.activeFilters),
      )}
      body={(row: UsdSwapTapeRow) => {
        // Structure-aware ordering so per-leg OPA / PTP / PTS render
        // front-to-back (front leg / belly / back leg), matching the
        // Reported LvL column and the expanded legs table.
        const legs = sortLegsForDisplay(row.legs_json ?? [])
        // For composite CURVE / FLY (SPREADOVER_CURVE, MATCHED_MATURITY_FLY…)
        // each leg carries its own broker-reported PTP / PTS. The backend
        // persists per-leg values when present; render them when at least
        // one leg has a non-null value, otherwise fall through to the
        // package-level scalar.
        const kind = String(row.package_type ?? row.trade_type ?? '').toUpperCase()
        const isMultiLeg =
          kind === 'CURVE' ||
          kind === 'FLY' ||
          kind.endsWith('_CURVE') ||
          kind.endsWith('_FLY')
        const legPtp = isMultiLeg
          ? legs.map((l) => (l as any).package_transaction_price ?? null)
          : undefined
        const legPts = isMultiLeg
          ? legs.map((l) => (l as any).package_transaction_spread ?? null)
          : undefined
        // Enhancement 1b: render the package PTS in bps in the Other Lvl cell
        // (scale inferred by tying it to the derived rate spread). Per-leg raw
        // PTS stays in the expanded legs table.
        const _summary = computeLegSummary(row)
        const _dBp = derivedSpreadBp(row, _summary.rate)
        const _ptsBp = ptsInBp(
          row.package_transaction_spread ?? _summary.pts,
          _dBp,
        )
        const lines = formatOtherLvl({
          // Signed per-leg OPA when the sign solver resolved it, so the
          // line reads "-406k / 542k / 102k" consistently with the
          // expanded leg table and ties visually to the PTP.
          legOpa: legs.map((l) =>
            l.other_payment_amount != null && l.opa_sign != null
              ? l.opa_sign * l.other_payment_amount
              : l.other_payment_amount ?? null,
          ),
          opaCurrency: legs.map((l) => l.other_payment_currency ?? null),
          ptp: row.package_transaction_price ?? null,
          ptpCurrency: row.package_transaction_price_currency ?? null,
          pts: row.package_transaction_spread ?? null,
          legPtp,
          legPts,
        })
        return (
          <div
            data-testid="other-lvl-cell"
            className="flex flex-col items-end font-mono text-[12px] font-semibold leading-tight text-slate-100"
          >
            <span>{lines.opaLine}</span>
            <span>{lines.ptpLine}</span>
            <span>{_ptsBp !== null ? `PTS: ${formatBp(_ptsBp)}` : lines.ptsLine}</span>
          </div>
        )
      }}
      style={{ width: 118 }}
    />,
    <Column
      key="tape_tags"
      field="tape_tags"
      filterField="tape_tags"
      sortable
      filter
      {...compactFilterMenuProps}
      header={renderHeader(
        'Tags',
        summaryFor('tape_tags', config.activeFilters),
      )}
      body={(row: UsdSwapTapeRow) => {
        const tags = tapeTagBadgesFor(row)
        const quality = qualityBadgesFor(row)
        if (tags.length === 0 && quality.length === 0) {
          return <span className="text-slate-600 text-[10px]">·</span>
        }
        return (
          <div className="flex flex-wrap items-center gap-1" data-testid="tape-tags">
            {tags.map((b) => (
              <span
                key={b.key}
                className={`px-1 py-0.5 rounded text-[10px] font-semibold ${b.className}`}
              >
                {b.label}
              </span>
            ))}
            {quality.map((b) => (
              <span
                key={b.key}
                className={`px-1 py-0.5 rounded text-[10px] font-semibold ${b.className}`}
                title={b.title}
              >
                {b.label}
              </span>
            ))}
          </div>
        )
      }}
      style={{ width: 220 }}
    />,
    /* Bug 8: 'Spread (bp)' and 'OPA Conf' columns removed */
  )
  return cols
}
