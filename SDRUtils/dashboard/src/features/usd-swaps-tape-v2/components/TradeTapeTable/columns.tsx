'use client'
// ABOUTME: Column body templates for the main TradeTapeTable.
import type { JSX } from 'react'
import { Column } from 'primereact/column'
import { EMPTY_VALUE } from '../../constants'
import type { UsdSwapTapeRow } from '../../types'
import {
  formatDv01,
  formatExecutionWindow,
  formatNotional,
  formatRate,
} from '../../utils/format'
import { LifecyclePills } from './RowBadges'
import { TapeLabelCell } from './TapeLabelCell'

export { rowClassName } from './columns.helpers'

export type MetricMode = 'dv01' | 'notional'

type ColumnConfig = {
  selection: boolean
  expanderBody?: (row: UsdSwapTapeRow) => JSX.Element
  metricMode?: MetricMode
  onToggleMetric?: () => void
}

function renderHeader(label: string): JSX.Element {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-[11px] uppercase tracking-wide text-gray-400">
        {label}
      </span>
    </div>
  )
}

function firstLeg(row: UsdSwapTapeRow) {
  return row.legs_json?.[0]
}

function displayPlatform(row: UsdSwapTapeRow): string {
  return row.platform_identifier ?? firstLeg(row)?.platform_identifier ?? EMPTY_VALUE
}

export function getColumns(
  config: ColumnConfig = { selection: true },
): JSX.Element[] {
  const cols: JSX.Element[] = []
  if (config.selection) {
    cols.push(
      <Column key="select" selectionMode="multiple" headerStyle={{ width: 34 }} />,
    )
  }
  if (config.expanderBody) {
    cols.push(
      <Column key="expand" body={config.expanderBody as any} style={{ width: 40 }} />,
    )
  }

  const mode: MetricMode = config.metricMode ?? 'dv01'
  const metricHeader = (
    <button
      type="button"
      onClick={config.onToggleMetric}
      className="flex flex-col gap-0.5 text-left hover:text-sky-300"
      aria-label={`toggle metric (current: ${mode === 'dv01' ? 'DV01' : 'Notional'})`}
    >
      <span className="text-[11px] uppercase tracking-wide text-gray-400">
        {mode === 'dv01' ? 'DV01' : 'Notional'} ⇅
      </span>
    </button>
  )

  cols.push(
    <Column
      key="time"
      field="execution_start"
      filterField="execution_start"
      sortable
      filter
      header={renderHeader('Time')}
      body={(row: UsdSwapTapeRow) => (
        <span className="whitespace-nowrap text-xs text-gray-300">
          {formatExecutionWindow(row.execution_start, row.execution_end)}
        </span>
      )}
      style={{ width: 108 }}
    />,
    <Column
      key="action"
      field="action_label"
      filterField="action_label"
      filter
      header={renderHeader('Action')}
      body={(row: UsdSwapTapeRow) => <LifecyclePills row={row} />}
      style={{ width: 68 }}
    />,
    <Column
      key="platform"
      field="platform_identifier"
      filterField="platform_identifier"
      sortable
      filter
      header={renderHeader('Platform')}
      body={(row: UsdSwapTapeRow) => (
        <span className="text-xs text-gray-300 truncate">
          {displayPlatform(row)}
        </span>
      )}
      style={{ width: 76 }}
    />,
    <Column
      key="tape_label"
      field="tape_label"
      filterField="tape_label"
      sortable
      filter
      header={renderHeader('Tape Label')}
      body={(row: UsdSwapTapeRow) => <TapeLabelCell row={row} />}
      style={{ width: 500 }}
    />,
    <Column
      key="metric"
      field={mode === 'dv01' ? 'total_risk' : 'total_notional'}
      filterField={mode === 'dv01' ? 'total_risk' : 'total_notional'}
      sortable
      filter
      dataType="numeric"
      header={metricHeader}
      body={(row: UsdSwapTapeRow) => (
        <span className="font-mono text-xs text-gray-200">
          {mode === 'dv01'
            ? formatDv01(row.total_risk ?? null, { signed: true })
            : formatNotional(row.total_notional ?? null, { compact: true })}
        </span>
      )}
      style={{ width: 86 }}
    />,
    <Column
      key="rate"
      field="weighted_fixed_rate"
      filterField="weighted_fixed_rate"
      sortable
      filter
      dataType="numeric"
      header={renderHeader('Reported LvL')}
      body={(row: UsdSwapTapeRow) => (
        <span className="font-mono text-xs text-gray-200">
          {formatRate(row.weighted_fixed_rate ?? null)}
        </span>
      )}
      style={{ width: 92 }}
    />,
  )
  return cols
}
