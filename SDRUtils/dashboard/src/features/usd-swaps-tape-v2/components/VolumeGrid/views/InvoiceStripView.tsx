'use client'

import type { JSX } from 'react'
import { useCallback, useMemo, useState } from 'react'
import { VolumeGrid } from '../VolumeGrid'
import { useVolumeGrid } from '../../../hooks/useVolumeGrid'
import type {
  VolumeGridColorMode,
  VolumeGridViewMode,
} from '../../../types/volume-grid.types'
import type { CellId, ViewProps } from '../../../types/volume-grid-views.types'
import type { BucketDef } from '@/lib/usd-swaps-tape-v2/volumeGridBuckets'
import type { PackageTypeGroupId } from '@/lib/usd-swaps-tape-v2/volumeGridBuckets'

const INVOICE_TENORS: BucketDef[] = [
  { id: '2y',     label: '2Y',       lo: 1.5,   hi: 3.0 },
  { id: '5y',     label: '5Y',       lo: 3.0,   hi: 6.0 },
  { id: '7y',     label: '~7Y',      lo: 6.0,   hi: 8.0 },
  { id: '10y',    label: '10Y',      lo: 8.0,   hi: 12.0 },
  { id: '20y',    label: '20Y',      lo: 15.0,  hi: 22.0 },
  { id: '30y',    label: '30Y+',     lo: 22.0,  hi: 35.0 },
]

const INVOICE_FORWARD: BucketDef[] = [
  { id: 'front',  label: 'Front',  lo: null,  hi: 0.25 },
  { id: 'back',   label: 'Back',   lo: 0.25,  hi: 0.75 },
]

type InvoiceFilter = 'invoice_all' | 'invoice' | 'invoice_calendar' | 'invoice_switch'

const INVOICE_FILTER_OPTIONS: ReadonlyArray<{ id: InvoiceFilter; label: string }> = [
  { id: 'invoice_all',      label: 'All' },
  { id: 'invoice',          label: 'Outright' },
  { id: 'invoice_calendar', label: 'Calendar' },
  { id: 'invoice_switch',   label: 'Switch' },
]

export function InvoiceStripView(props: ViewProps): JSX.Element {
  const [viewMode, setViewMode] = useState<VolumeGridViewMode>('volume')
  const [colorMode, setColorMode] = useState<VolumeGridColorMode>('activity')
  const [invoiceFilter, setInvoiceFilter] = useState<InvoiceFilter>('invoice_all')

  const grid = useVolumeGrid({
    metric: props.metric,
    period: props.period,
    lookbackDays: props.lookbackDays,
    forwardSchema: 'custom',
    tenorSchema: 'custom',
    packageType: invoiceFilter as PackageTypeGroupId,
    viewMode,
    textFilter: props.textFilter,
    collapsed: false,
    customForwardBuckets: INVOICE_FORWARD,
    customTenorBuckets: INVOICE_TENORS,
  })

  const handleCellClick = useCallback(
    (id: { fwd: string; tenor: string }) => {
      props.onCellClick({ kind: 'matrix', fwd: id.fwd, tenor: id.tenor }, {
        packageType: invoiceFilter as PackageTypeGroupId,
        forwardSchema: 'custom',
        tenorSchema: 'custom',
        customForwardBuckets: INVOICE_FORWARD,
        customTenorBuckets: INVOICE_TENORS,
        viewLabel: 'Invoice Swaps',
      })
    },
    [props.onCellClick, invoiceFilter],
  )

  return (
    <div className="px-3 pb-3">
      <div className="flex flex-wrap items-center gap-2 pb-2">
        <Toggle
          options={INVOICE_FILTER_OPTIONS}
          value={invoiceFilter}
          onChange={setInvoiceFilter}
        />
        <Toggle
          options={[
            { id: 'activity' as const, label: 'Activity' },
            { id: 'grid' as const, label: 'Grid' },
          ]}
          value={colorMode}
          onChange={setColorMode}
        />
        <Toggle
          options={[
            { id: 'volume' as const, label: 'Volume' },
            { id: 'idb_custy' as const, label: 'IDB / CUSTY' },
          ]}
          value={viewMode}
          onChange={setViewMode}
        />
      </div>
      {grid.data ? (
        <VolumeGrid
          data={grid.data}
          metric={props.metric}
          period={props.period}
          viewMode={viewMode}
          colorMode={colorMode}
          packageType={invoiceFilter as PackageTypeGroupId}
          onCellClick={handleCellClick}
        />
      ) : (
        <div className="grid h-12 animate-pulse grid-cols-6 gap-px">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="rounded-sm bg-slate-800/40" />
          ))}
        </div>
      )}
    </div>
  )
}

function Toggle<T extends string>({
  options, value, onChange,
}: { options: ReadonlyArray<{ id: T; label: string }>; value: T; onChange: (v: T) => void }): JSX.Element {
  return (
    <div className="flex items-center rounded border border-slate-700 p-[1px]">
      {options.map((o) => (
        <button key={o.id} type="button" onClick={() => onChange(o.id)}
          className={`px-2 py-[1px] font-mono text-[10.5px] ${value === o.id ? 'bg-indigo-500/25 text-indigo-100' : 'text-slate-300 hover:bg-slate-800'}`}
        >{o.label}</button>
      ))}
    </div>
  )
}
