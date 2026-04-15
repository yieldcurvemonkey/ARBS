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

type ColumnConfig = {
  selection: boolean
  expanderBody?: (row: UsdSwapTapeRow) => JSX.Element
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

function displayType(row: UsdSwapTapeRow): string {
  return row.trade_type ?? firstLeg(row)?.trade_type ?? row.package_type ?? EMPTY_VALUE
}

export function getColumns(
  config: ColumnConfig = { selection: true },
): JSX.Element[] {
  const cols: JSX.Element[] = []
  if (config.selection) {
    cols.push(
      <Column key="select" selectionMode="multiple" headerStyle={{ width: 40 }} />,
    )
  }
  if (config.expanderBody) {
    cols.push(
      <Column key="expand" body={config.expanderBody as any} style={{ width: 48 }} />,
    )
  }
  cols.push(
    <Column
      key="time"
      header={renderHeader('Time')}
      body={(row: UsdSwapTapeRow) => (
        <span className="text-xs text-gray-300">
          {formatExecutionWindow(row.execution_start, row.execution_end)}
        </span>
      )}
      style={{ width: 190 }}
    />,
    <Column
      key="action"
      header={renderHeader('Action')}
      body={(row: UsdSwapTapeRow) => <LifecyclePills row={row} />}
      style={{ width: 132 }}
    />,
    <Column
      key="platform"
      header={renderHeader('Platform')}
      body={(row: UsdSwapTapeRow) => (
        <span className="text-xs text-gray-300 truncate">
          {displayPlatform(row)}
        </span>
      )}
      style={{ width: 120 }}
    />,
    <Column
      key="tape_label"
      header={renderHeader('Tape Label')}
      body={(row: UsdSwapTapeRow) => <TapeLabelCell row={row} />}
      style={{ width: 700 }}
    />,
    <Column
      key="trade_type"
      header={renderHeader('Type')}
      body={(row: UsdSwapTapeRow) => (
        <span className="text-xs text-gray-300">{displayType(row)}</span>
      )}
      style={{ width: 120 }}
    />,
    <Column
      key="dv01"
      header={renderHeader('DV01')}
      body={(row: UsdSwapTapeRow) => (
        <span className="font-mono text-xs text-gray-200">
          {formatDv01(row.total_risk ?? null, { signed: true })}
        </span>
      )}
      style={{ width: 96 }}
    />,
    <Column
      key="notional"
      header={renderHeader('Notional')}
      body={(row: UsdSwapTapeRow) => (
        <span className="font-mono text-xs text-gray-200">
          {formatNotional(row.total_notional ?? null, { compact: true })}
        </span>
      )}
      style={{ width: 110 }}
    />,
    <Column
      key="rate"
      header={renderHeader('Rate')}
      body={(row: UsdSwapTapeRow) => (
        <span className="font-mono text-xs text-gray-200">
          {formatRate(row.weighted_fixed_rate ?? null)}
        </span>
      )}
      style={{ width: 84 }}
    />,
  )
  return cols
}
