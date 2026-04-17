'use client'
// ABOUTME: Column body templates for the main TradeTapeTable.
import type { JSX } from 'react'
import { Column } from 'primereact/column'
import type { DataTableFilterMeta } from 'primereact/datatable'
import { EMPTY_VALUE } from '../../constants'
import type { UsdSwapTapeRow } from '../../types'
import {
  formatDv01,
  formatExecutionWindow,
  formatNotional,
  formatOtherLvl,
  formatRate,
} from '../../utils/format'
import { getFilterDisplayLabel } from './filter-utils'
import { LifecyclePills } from './RowBadges'
import { TapeLabelCell } from './TapeLabelCell'
import {
  packageIndicatorDisplay,
  packageTypeBadgeClassName,
  packageTypeDisplayLabel,
} from './columns.helpers'

export { rowClassName } from './columns.helpers'

export type MetricMode = 'dv01' | 'notional'

type ColumnConfig = {
  selection: boolean
  expanderBody?: (row: UsdSwapTapeRow) => JSX.Element
  metricMode?: MetricMode
  onToggleMetric?: () => void
  /**
   * Current per-column filter state. Used to render a subtle "preview" line
   * under each column title (e.g. `contains "Fed"`). Editing still happens in
   * the popup overlay (filterDisplay="menu") opened via the funnel icon.
   */
  activeFilters?: DataTableFilterMeta
}

function renderHeader(label: string, summary?: string | null): JSX.Element {
  return (
    <div className="flex flex-col leading-tight">
      <span className="text-[10px] uppercase tracking-wide text-gray-400">
        {label}
      </span>
      {summary ? (
        <span
          className="mt-0.5 truncate text-[9px] font-normal normal-case tracking-normal text-sky-300/70"
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

export function getColumns(
  config: ColumnConfig = { selection: true },
): JSX.Element[] {
  const cols: JSX.Element[] = []
  if (config.selection) {
    cols.push(
      <Column key="select" selectionMode="multiple" headerStyle={{ width: 30 }} />,
    )
  }
  if (config.expanderBody) {
    cols.push(
      <Column key="expand" body={config.expanderBody as any} style={{ width: 36 }} />,
    )
  }

  const mode: MetricMode = config.metricMode ?? 'dv01'
  const metricField = mode === 'dv01' ? 'total_risk' : 'total_notional'
  const metricSummary = summaryFor(metricField, config.activeFilters)
  const metricHeader = (
    <div className="flex flex-col leading-tight">
      <button
        type="button"
        onClick={config.onToggleMetric}
        className="flex flex-col text-left hover:text-sky-300"
        aria-label={`toggle metric (current: ${mode === 'dv01' ? 'DV01' : 'Notional'})`}
      >
        <span className="text-[10px] uppercase tracking-wide text-gray-400">
          {mode === 'dv01' ? 'DV01' : 'Notional'} ⇅
        </span>
      </button>
      {metricSummary ? (
        <span
          className="mt-0.5 truncate text-[9px] font-normal normal-case tracking-normal text-sky-300/70"
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
      header={renderHeader(
        'Time',
        summaryFor('execution_start', config.activeFilters),
      )}
      body={(row: UsdSwapTapeRow) => (
        <span className="whitespace-nowrap text-[12px] text-gray-300">
          {formatExecutionWindow(row.execution_start, row.execution_end)}
        </span>
      )}
      style={{ width: 102 }}
    />,
    <Column
      key="action"
      field="lifecycle_type"
      filterField="lifecycle_type"
      filter
      {...compactFilterMenuProps}
      header={renderHeader(
        'Action',
        summaryFor('lifecycle_type', config.activeFilters),
      )}
      body={(row: UsdSwapTapeRow) => <LifecyclePills row={row} />}
      style={{ width: 64 }}
    />,
    <Column
      key="platform"
      field="platform_identifier"
      filterField="platform_identifier"
      sortable
      filter
      {...compactFilterMenuProps}
      header={renderHeader(
        'Platform',
        summaryFor('platform_identifier', config.activeFilters),
      )}
      body={(row: UsdSwapTapeRow) => (
        <span className="truncate text-[12px] text-gray-300">
          {displayPlatform(row)}
        </span>
      )}
      style={{ width: 72 }}
    />,
    <Column
      key="pkg"
      field="package_type"
      filterField="package_type"
      filter
      {...compactFilterMenuProps}
      header={renderHeader(
        'Pkg',
        summaryFor('package_type', config.activeFilters),
      )}
      body={(row: UsdSwapTapeRow) => (
        <span
          className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-semibold ${packageTypeBadgeClassName(row.package_type)}`}
        >
          {packageTypeDisplayLabel(row.package_type)}
        </span>
      )}
      style={{ width: 92 }}
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
        <span className="font-mono text-[12px] text-gray-300">
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
      body={(row: UsdSwapTapeRow) => <TapeLabelCell row={row} />}
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
      body={(row: UsdSwapTapeRow) => (
        <span className="font-mono text-[13px] text-gray-200">
          {mode === 'dv01'
            ? formatDv01(row.total_risk ?? null, { signed: true })
            : formatNotional(row.total_notional ?? null, { compact: true })}
        </span>
      )}
      style={{ width: 82 }}
    />,
    <Column
      key="rate"
      field="weighted_fixed_rate"
      filterField="weighted_fixed_rate"
      sortable
      filter
      dataType="numeric"
      {...compactFilterMenuProps}
      header={renderHeader(
        'Reported LvL',
        summaryFor('weighted_fixed_rate', config.activeFilters),
      )}
      body={(row: UsdSwapTapeRow) => (
        <span className="font-mono text-[13px] text-gray-200">
          {formatRate(row.weighted_fixed_rate ?? null)}
        </span>
      )}
      style={{ width: 88 }}
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
        const legs = row.legs_json ?? []
        const lines = formatOtherLvl({
          legOpa: legs.map((l) => l.other_payment_amount ?? null),
          opaCurrency: legs.map((l) => l.other_payment_currency ?? null),
          ptp: row.package_transaction_price ?? null,
          ptpCurrency: row.package_transaction_price_currency ?? null,
        })
        return (
          <div
            data-testid="other-lvl-cell"
            className="flex flex-col font-mono text-[13px] text-gray-200"
          >
            <span>{lines.opaLine}</span>
            <span>{lines.ptpLine}</span>
          </div>
        )
      }}
      style={{ width: 110 }}
    />,
  )
  return cols
}
