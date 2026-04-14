'use client'
// ABOUTME: Column body templates for the main TradeTapeTable.
import type { JSX } from 'react'
import { Column } from 'primereact/column'
import type { UsdSwapTapeRow } from '../../types'
import {
  formatDv01,
  formatNotional,
  formatRate,
  formatTime,
} from '../../utils/format'
import { LifecyclePills, FlagBadges } from './RowBadges'
import { TapeLabelCell } from './TapeLabelCell'

export { rowClassName } from './columns.helpers'

type ColumnConfig = {
  expansion: boolean
  selection: boolean
}

export function getColumns(config: ColumnConfig = { expansion: true, selection: true }): JSX.Element[] {
  const cols: JSX.Element[] = []
  if (config.selection) {
    cols.push(
      <Column key="select" selectionMode="multiple" headerStyle={{ width: 40 }} />,
    )
  }
  if (config.expansion) {
    cols.push(<Column key="expand" expander style={{ width: 36 }} />)
  }
  cols.push(
    <Column
      key="time"
      header="Time"
      body={(row: UsdSwapTapeRow) => formatTime(row.execution_start)}
      style={{ width: 92 }}
    />,
    <Column
      key="lifecycle"
      header="Lifecycle"
      body={(row: UsdSwapTapeRow) => <LifecyclePills row={row} />}
      style={{ width: 100 }}
    />,
    <Column
      key="tape_label"
      header="Tape Label"
      body={(row: UsdSwapTapeRow) => <TapeLabelCell row={row} />}
      style={{ width: 420 }}
    />,
    <Column
      key="trade_type"
      header="Type"
      body={(row: UsdSwapTapeRow) => row.trade_type ?? row.package_type ?? '—'}
      style={{ width: 110 }}
    />,
    <Column
      key="structure"
      header="Structure"
      body={(row: UsdSwapTapeRow) => row.package_structure ?? row.package_type ?? '—'}
      style={{ width: 150 }}
    />,
    <Column
      key="tenor"
      header="Tenor"
      body={(row: UsdSwapTapeRow) =>
        row.legs_json?.[0]?.tenor_display ?? row.tenor_label ?? '—'
      }
      style={{ width: 72 }}
    />,
    <Column
      key="dv01"
      header="DV01"
      body={(row: UsdSwapTapeRow) =>
        formatDv01(row.total_risk ?? null, { signed: true })
      }
      style={{ width: 96 }}
    />,
    <Column
      key="notional"
      header="Notional"
      body={(row: UsdSwapTapeRow) =>
        formatNotional(row.total_notional ?? null, { compact: true })
      }
      style={{ width: 110 }}
    />,
    <Column
      key="rate"
      header="Rate"
      body={(row: UsdSwapTapeRow) => formatRate(row.weighted_fixed_rate ?? null)}
      style={{ width: 84 }}
    />,
    <Column
      key="venue"
      header="Venue"
      body={(row: UsdSwapTapeRow) => row.venue ?? '—'}
      style={{ width: 72 }}
    />,
    <Column
      key="ccp"
      header="CCP"
      body={(row: UsdSwapTapeRow) => row.ccp ?? '—'}
      style={{ width: 64 }}
    />,
    <Column
      key="session"
      header="Session"
      body={(row: UsdSwapTapeRow) => row.execution_session ?? '—'}
      style={{ width: 76 }}
    />,
    <Column
      key="flags"
      header="Flags"
      body={(row: UsdSwapTapeRow) => <FlagBadges row={row} />}
      style={{ width: 140 }}
    />,
  )
  return cols
}
