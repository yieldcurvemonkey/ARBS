'use client'

import { useEffect, useMemo, useState } from 'react'
import { ALL_LISTED_VOL_PRODUCTS, PRODUCT_CLASS_LABELS, STIR_PRODUCTS, UST_PRODUCTS } from '../constants'
import { useListedVolComparison } from '../hooks/useListedVolComparison'
import { useListedVolGrid } from '../hooks/useListedVolGrid'
import type {
  ListedVolDisplayMode,
  ListedVolGridCell,
  ListedVolProduct,
  ListedVolProductClass
} from '../types'
import { DisplayModeSelector } from './DisplayModeSelector'
import { ListedVolGrid } from './ListedVolGrid'
import { ProductSelector } from './ProductSelector'
import { RealizedVolPanel } from './RealizedVolPanel'
import { SwaptionComparisonView } from './SwaptionComparisonView'
import { CellTimeseriesModal } from './CellTimeseriesModal'

type DashboardTab = 'grid' | 'comparison' | 'realized'

export default function ListedVolDashboard() {
  const [activeTab, setActiveTab] = useState<DashboardTab>('grid')
  const [selectedDate, setSelectedDate] = useState('')
  const [productClass, setProductClass] = useState<ListedVolProductClass>('ALL')
  const [displayMode, setDisplayMode] = useState<ListedVolDisplayMode>('vol')
  const [selectedProduct, setSelectedProduct] = useState<ListedVolProduct>('TY')
  const [selectedCell, setSelectedCell] = useState<ListedVolGridCell | null>(null)

  const grid = useListedVolGrid({
    date: selectedDate || undefined,
    productClass
  })

  const comparison = useListedVolComparison(selectedDate || undefined, selectedProduct)
  const gridReload = grid.reload
  const comparisonReload = comparison.reload

  const comparisonProducts = useMemo(() => {
    if (productClass === 'UST') return UST_PRODUCTS
    if (productClass === 'STIR') return STIR_PRODUCTS
    return ALL_LISTED_VOL_PRODUCTS
  }, [productClass])

  useEffect(() => {
    if (!comparisonProducts.includes(selectedProduct)) {
      setSelectedProduct(comparisonProducts[0] ?? 'TY')
    }
  }, [comparisonProducts, selectedProduct])

  useEffect(() => {
    if (selectedDate) return
    const interval = setInterval(() => {
      gridReload()
      comparisonReload()
    }, 5000)
    return () => clearInterval(interval)
  }, [comparisonReload, gridReload, selectedDate])

  const statusText = grid.data
    ? `Showing ${grid.data.asOfDate}${selectedDate ? ` (requested ${selectedDate})` : ''}`
    : 'Loading...'

  return (
    <div className="space-y-5">
      <section className="rounded-3xl border border-slate-800 bg-slate-950/70 p-5">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <div className="text-xs font-semibold uppercase tracking-[0.22em] text-sky-300/80">
              USD Rates Vol Analytics
            </div>
            <h1 className="mt-2 text-2xl font-semibold text-white">Listed Option vs OTC Vol</h1>
            <p className="mt-2 text-sm text-slate-400">{statusText}</p>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <input
              type="date"
              value={selectedDate}
              onChange={(event) => setSelectedDate(event.target.value)}
              className="rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-200"
            />
            <button
              type="button"
              onClick={() => setSelectedDate('')}
              className="rounded-xl border border-slate-700 bg-slate-900/70 px-3 py-2 text-sm text-slate-300 hover:text-white"
            >
              Latest
            </button>
            <DisplayModeSelector value={displayMode} onChange={setDisplayMode} />
          </div>
        </div>

        <div className="mt-5 flex flex-wrap items-center gap-3">
          {(['ALL', 'UST', 'STIR'] as ListedVolProductClass[]).map((value) => (
            <button
              key={value}
              type="button"
              onClick={() => setProductClass(value)}
              className={`rounded-full border px-3 py-1.5 text-sm font-semibold transition ${
                productClass === value
                  ? 'border-emerald-400 bg-emerald-500/15 text-emerald-100'
                  : 'border-slate-700 bg-slate-900/70 text-slate-300 hover:text-white'
              }`}
            >
              {PRODUCT_CLASS_LABELS[value]}
            </button>
          ))}
        </div>

        <div className="mt-5 flex flex-wrap gap-2">
          {([
            ['grid', 'Listed Vol Grid'],
            ['comparison', 'Swaption vs Listed'],
            ['realized', 'Realized Vol']
          ] as Array<[DashboardTab, string]>).map(([tab, label]) => (
            <button
              key={tab}
              type="button"
              onClick={() => setActiveTab(tab)}
              className={`rounded-full border px-4 py-2 text-sm font-semibold transition ${
                activeTab === tab
                  ? 'border-slate-100 bg-slate-100 text-slate-950'
                  : 'border-slate-700 bg-slate-900/70 text-slate-300 hover:text-white'
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </section>

      {grid.error ? (
        <div className="rounded-2xl border border-rose-500/40 bg-rose-500/10 px-4 py-3 text-sm text-rose-200">
          {grid.error}
        </div>
      ) : null}

      {activeTab === 'grid' ? (
        <ListedVolGrid
          products={grid.data?.products ?? comparisonProducts}
          cells={grid.data?.cells ?? []}
          mode={displayMode}
          onCellClick={(cell) => setSelectedCell(cell)}
        />
      ) : null}

      {activeTab === 'comparison' ? (
        <section className="space-y-4">
          <ProductSelector
            products={comparisonProducts}
            selectedProduct={selectedProduct}
            onSelect={setSelectedProduct}
          />
          {comparison.error ? (
            <div className="rounded-2xl border border-rose-500/40 bg-rose-500/10 px-4 py-3 text-sm text-rose-200">
              {comparison.error}
            </div>
          ) : (
            <SwaptionComparisonView rows={comparison.data?.rows ?? []} />
          )}
        </section>
      ) : null}

      {activeTab === 'realized' ? (
        <RealizedVolPanel
          rows={grid.data?.realizedRows ?? []}
          productClass={productClass}
        />
      ) : null}

      <CellTimeseriesModal
        date={selectedDate || grid.data?.asOfDate}
        cell={selectedCell}
        open={selectedCell !== null}
        onClose={() => setSelectedCell(null)}
      />
    </div>
  )
}
