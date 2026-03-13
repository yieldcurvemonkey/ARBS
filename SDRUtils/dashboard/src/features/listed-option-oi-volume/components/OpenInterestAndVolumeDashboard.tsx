'use client'

import { useEffect, useMemo, useState } from 'react'

import { DashboardSection } from './DashboardSection'
import { SnapshotMatrix } from './SnapshotMatrix'
import { TimeseriesModule } from './TimeseriesModule'
import type {
  ListedOptionContractReferenceMode,
  ListedOptionLabelNamespace,
  ListedOptionMetricField,
  ListedOptionRowAxis,
  ListedOptionSeriesConfig,
  ListedOptionSnapshotResponse,
} from '../types'
import {
  buildSearchOptionsFromSnapshot,
  filterSnapshotRowsByAxisRange,
  getSeriesConfigKey,
  metricFieldLabel,
} from '../utils'

type ProductFamilyFilter = 'ALL' | 'UST' | 'STIR'

type PersistedState = {
  field: ListedOptionMetricField
  periodBusinessDays: number
  requestedDate: string
  productFamily: ProductFamilyFilter
  selectedRoots: string[]
  labelNamespace: ListedOptionLabelNamespace
  contractView: ListedOptionContractReferenceMode
  rowAxis: ListedOptionRowAxis
  topValue: string
  bottomValue: string
  selectedSeries: ListedOptionSeriesConfig[]
}

const STORAGE_KEY = 'listed-option-oi-volume-dashboard.v1'

const DEFAULT_STATE: PersistedState = {
  field: 'open_interest_change',
  periodBusinessDays: 1,
  requestedDate: '',
  productFamily: 'ALL',
  selectedRoots: [],
  labelNamespace: 'Globex',
  contractView: 'explicit',
  rowAxis: 'strike',
  topValue: '',
  bottomValue: '',
  selectedSeries: [],
}

export default function OpenInterestAndVolumeDashboard() {
  const [restored, setRestored] = useState(false)
  const [state, setState] = useState<PersistedState>(DEFAULT_STATE)
  const [snapshot, setSnapshot] = useState<ListedOptionSnapshotResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [expanded, setExpanded] = useState({
    matrix: true,
    chart: true,
  })

  useEffect(() => {
    try {
      const raw = localStorage.getItem(STORAGE_KEY)
      if (raw) {
        const parsed = JSON.parse(raw) as Partial<PersistedState>
        setState((current) => ({
          ...current,
          ...parsed,
          selectedSeries: Array.isArray(parsed.selectedSeries) ? parsed.selectedSeries : current.selectedSeries,
        }))
      }
    } catch {
      // no-op
    } finally {
      setRestored(true)
    }
  }, [])

  useEffect(() => {
    if (!restored) return
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state))
  }, [restored, state])

  useEffect(() => {
    if (!restored) return

    const params = new URLSearchParams({
      field: state.field,
      periodBusinessDays: String(state.periodBusinessDays),
      labelNamespace: state.labelNamespace,
      contractView: state.contractView,
      rowAxis: state.rowAxis,
    })
    if (state.requestedDate.trim()) {
      params.set('date', state.requestedDate.trim())
    }
    if (state.productFamily !== 'ALL') {
      params.set('productFamily', state.productFamily)
    }
    if (state.selectedRoots.length) {
      params.set('productRoots', state.selectedRoots.join(','))
    }

    setLoading(true)
    setError(null)

    fetch(`/api/listed-option-oi-volume/snapshot?${params.toString()}`)
      .then(async (response) => {
        const payload = await response.json()
        if (!response.ok) {
          throw new Error(payload?.error ?? `HTTP ${response.status}`)
        }
        setSnapshot(payload as ListedOptionSnapshotResponse)
      })
      .catch((fetchError: any) => {
        setError(fetchError?.message ?? 'Unable to load listed option snapshot')
        setSnapshot(null)
      })
      .finally(() => {
        setLoading(false)
      })
  }, [restored, state.contractView, state.field, state.labelNamespace, state.periodBusinessDays, state.productFamily, state.requestedDate, state.rowAxis, state.selectedRoots])

  const availableRoots = useMemo(
    () =>
      (snapshot?.availableRoots ?? []).filter(
        (root) => state.productFamily === 'ALL' || root.productFamily === state.productFamily
      ),
    [snapshot?.availableRoots, state.productFamily]
  )

  const filteredRows = useMemo(() => {
    if (!snapshot) return []
    return filterSnapshotRowsByAxisRange(snapshot.rows, state.topValue, state.bottomValue)
  }, [snapshot, state.bottomValue, state.topValue])

  const searchOptions = useMemo(
    () => buildSearchOptionsFromSnapshot(snapshot),
    [snapshot]
  )

  const toggleRoot = (productRoot: string) => {
    setState((current) => ({
      ...current,
      selectedRoots: current.selectedRoots.includes(productRoot)
        ? current.selectedRoots.filter((root) => root !== productRoot)
        : [...current.selectedRoots, productRoot],
    }))
  }

  const addSeriesFromCell = (config: ListedOptionSeriesConfig) => {
    setState((current) => ({
      ...current,
      selectedSeries: Array.from(
        new Map(
          [...current.selectedSeries, config].map((series) => [
            getSeriesConfigKey(series),
            series,
          ])
        ).values()
      ),
    }))
    setExpanded((current) => ({ ...current, chart: true }))
  }

  return (
    <div className="space-y-4 rounded-2xl border border-slate-800/80 bg-[radial-gradient(circle_at_top_left,rgba(51,65,85,0.2),transparent_28%),linear-gradient(180deg,rgba(15,23,42,0.94),rgba(2,6,23,0.98))] p-4 shadow-[0_24px_60px_rgba(2,6,23,0.22)]">
      <section className="rounded-xl border border-slate-800/80 bg-slate-950/70 p-4">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight text-white">
              Open Interest and Volume Dashboard
            </h1>
            <p className="mt-1 max-w-[72rem] text-sm text-slate-400">
              Spreadsheet-style listed options matrix across UST and STIR roots with linked
              historical charting, rolling constant-maturity views, delta aliases, and ATMF
              offset aliases.
            </p>
          </div>
          <div className="rounded-lg border border-slate-700/80 bg-slate-900/70 px-3 py-2 text-[11px] uppercase tracking-[0.16em] text-slate-400">
            {snapshot?.asOfDate ? `As of ${snapshot.asOfDate}` : 'Awaiting snapshot'}
          </div>
        </div>

        <div className="mt-4 grid gap-3 xl:grid-cols-[repeat(6,minmax(0,1fr))]">
          <label className="text-[10px] text-slate-400">
            Field
            <select
              value={state.field}
              onChange={(event) =>
                setState((current) => ({ ...current, field: event.target.value as ListedOptionMetricField }))
              }
              className="mt-1 h-9 w-full rounded-md border border-slate-700/80 bg-slate-950/80 px-2.5 text-[12px] text-slate-100"
            >
              <option value="open_interest_change">Open interest change</option>
              <option value="volume_change">Volume change</option>
              <option value="open_interest">Open interest</option>
              <option value="volume">Volume</option>
            </select>
          </label>
          <label className="text-[10px] text-slate-400">
            Period
            <input
              type="number"
              min={1}
              value={state.periodBusinessDays}
              onChange={(event) =>
                setState((current) => ({
                  ...current,
                  periodBusinessDays: Math.max(1, Number(event.target.value) || 1),
                }))
              }
              className="mt-1 h-9 w-full rounded-md border border-slate-700/80 bg-slate-950/80 px-2.5 text-[12px] text-slate-100"
            />
          </label>
          <label className="text-[10px] text-slate-400">
            Date
            <input
              type="date"
              value={state.requestedDate}
              onChange={(event) => setState((current) => ({ ...current, requestedDate: event.target.value }))}
              className="mt-1 h-9 w-full rounded-md border border-slate-700/80 bg-slate-950/80 px-2.5 text-[12px] text-slate-100"
            />
          </label>
          <label className="text-[10px] text-slate-400">
            Namespace
            <select
              value={state.labelNamespace}
              onChange={(event) =>
                setState((current) => ({ ...current, labelNamespace: event.target.value as ListedOptionLabelNamespace }))
              }
              className="mt-1 h-9 w-full rounded-md border border-slate-700/80 bg-slate-950/80 px-2.5 text-[12px] text-slate-100"
            >
              <option value="BBG">BBG</option>
              <option value="Globex">Globex</option>
              <option value="Barchart">Barchart</option>
            </select>
          </label>
          <label className="text-[10px] text-slate-400">
            Contract View
            <select
              value={state.contractView}
              onChange={(event) =>
                setState((current) => ({
                  ...current,
                  contractView: event.target.value as ListedOptionContractReferenceMode,
                }))
              }
              className="mt-1 h-9 w-full rounded-md border border-slate-700/80 bg-slate-950/80 px-2.5 text-[12px] text-slate-100"
            >
              <option value="explicit">Explicit</option>
              <option value="constant_maturity">Constant maturity</option>
            </select>
          </label>
          <label className="text-[10px] text-slate-400">
            Row Axis
            <select
              value={state.rowAxis}
              onChange={(event) =>
                setState((current) => ({ ...current, rowAxis: event.target.value as ListedOptionRowAxis }))
              }
              className="mt-1 h-9 w-full rounded-md border border-slate-700/80 bg-slate-950/80 px-2.5 text-[12px] text-slate-100"
            >
              <option value="strike">Strike</option>
              <option value="delta">Delta</option>
              <option value="bps_offset">Bps offset</option>
            </select>
          </label>
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-2">
          {(['ALL', 'UST', 'STIR'] as ProductFamilyFilter[]).map((family) => (
            <button
              key={family}
              type="button"
              onClick={() =>
                setState((current) => ({
                  ...current,
                  productFamily: family,
                  selectedRoots:
                    family === 'ALL'
                      ? current.selectedRoots
                      : current.selectedRoots.filter((root) =>
                          (snapshot?.availableRoots ?? []).some(
                            (option) => option.productFamily === family && option.productRoot === root
                          )
                        ),
                }))
              }
              className={`rounded-full border px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.14em] transition ${
                state.productFamily === family
                  ? 'border-sky-400/60 bg-sky-400/10 text-sky-100'
                  : 'border-slate-700/80 bg-slate-950/70 text-slate-300 hover:border-slate-500 hover:text-white'
              }`}
            >
              {family}
            </button>
          ))}
        </div>

        <div className="mt-3 flex flex-wrap gap-2">
          {availableRoots.map((root) => (
            <button
              key={`${root.productFamily}:${root.productRoot}`}
              type="button"
              onClick={() => toggleRoot(root.productRoot)}
              className={`rounded-full border px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.14em] transition ${
                state.selectedRoots.includes(root.productRoot)
                  ? 'border-emerald-400/60 bg-emerald-400/10 text-emerald-100'
                  : 'border-slate-700/80 bg-slate-950/70 text-slate-300 hover:border-slate-500 hover:text-white'
              }`}
            >
              {root.productRoot}
            </button>
          ))}
          {availableRoots.length === 0 ? (
            <div className="text-[11px] text-slate-500">No roots available for the current filter.</div>
          ) : null}
        </div>

        <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          <label className="text-[10px] text-slate-400">
            Top {state.rowAxis === 'strike' ? 'strike' : 'row value'}
            <input
              type="number"
              value={state.topValue}
              onChange={(event) => setState((current) => ({ ...current, topValue: event.target.value }))}
              className="mt-1 h-9 w-full rounded-md border border-slate-700/80 bg-slate-950/80 px-2.5 text-[12px] text-slate-100"
            />
          </label>
          <label className="text-[10px] text-slate-400">
            Bottom {state.rowAxis === 'strike' ? 'strike' : 'row value'}
            <input
              type="number"
              value={state.bottomValue}
              onChange={(event) => setState((current) => ({ ...current, bottomValue: event.target.value }))}
              className="mt-1 h-9 w-full rounded-md border border-slate-700/80 bg-slate-950/80 px-2.5 text-[12px] text-slate-100"
            />
          </label>
          <div className="rounded-xl border border-slate-800/80 bg-slate-950/70 px-3 py-2 text-[11px] text-slate-400">
            <div className="font-semibold uppercase tracking-[0.14em] text-slate-500">Matrix Field</div>
            <div className="mt-1 text-slate-200">{metricFieldLabel(state.field)}</div>
          </div>
          <div className="rounded-xl border border-slate-800/80 bg-slate-950/70 px-3 py-2 text-[11px] text-slate-400">
            <div className="font-semibold uppercase tracking-[0.14em] text-slate-500">Displayed Rows</div>
            <div className="mt-1 text-slate-200">{filteredRows.length}</div>
          </div>
        </div>
      </section>

      <DashboardSection
        code="GRID"
        title="Spreadsheet Matrix"
        subtitle="Heatmapped call / put matrix with grouped contracts"
        expanded={expanded.matrix}
        onToggle={() => setExpanded((current) => ({ ...current, matrix: !current.matrix }))}
      >
        {loading ? (
          <div className="flex h-[760px] items-center justify-center text-sm text-slate-400">
            Loading snapshot...
          </div>
        ) : snapshot ? (
          <div className="space-y-3">
            {snapshot.warnings.length ? (
              <div className="rounded-lg border border-amber-900/50 bg-amber-950/30 px-4 py-3 text-xs text-amber-200">
                {snapshot.warnings.map((warning) => (
                  <div key={warning}>{warning}</div>
                ))}
              </div>
            ) : null}
            <SnapshotMatrix
              snapshot={snapshot}
              rows={filteredRows}
              onSelectSeries={addSeriesFromCell}
            />
          </div>
        ) : (
          <div className="flex h-[760px] items-center justify-center text-sm text-slate-500">
            No snapshot available.
          </div>
        )}
      </DashboardSection>

      <DashboardSection
        code="TS"
        title="Linked Timeseries"
        subtitle="Click matrix cells or use the command bar to chart history"
        expanded={expanded.chart}
        onToggle={() => setExpanded((current) => ({ ...current, chart: !current.chart }))}
      >
        <TimeseriesModule
          searchOptions={searchOptions}
          selectedSeries={state.selectedSeries}
          onSelectedSeriesChange={(selectedSeries) =>
            setState((current) => ({ ...current, selectedSeries }))
          }
          periodBusinessDays={state.periodBusinessDays}
        />
      </DashboardSection>

      {error ? (
        <div className="rounded-lg border border-rose-900/50 bg-rose-950/35 px-4 py-3 text-sm text-rose-200">
          {error}
        </div>
      ) : null}
    </div>
  )
}
