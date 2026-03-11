'use client'

import { useState } from 'react'

import type { DashboardTab } from '../types'
import { SmileModule } from './SmileModule'
import { TermStructureModule } from './TermStructureModule'
import { TimeseriesModule } from './TimeseriesModule'

const TABS: Array<{ key: DashboardTab; label: string }> = [
  { key: 'timeseries', label: 'Timeseries' },
  { key: 'term-structure', label: 'Term Structure' },
  { key: 'smile', label: 'Smile' },
]

export default function UstfVolDashboard() {
  const [activeTab, setActiveTab] = useState<DashboardTab>('timeseries')

  return (
    <div className="space-y-5">
      {/* Header */}
      <section className="rounded-3xl border border-slate-800 bg-slate-950/70 p-5">
        <div className="text-[11px] font-semibold uppercase tracking-[0.22em] text-sky-300/80">
          USTF vs OTC
        </div>
        <h1 className="mt-2 text-2xl font-semibold text-white">
          Listed vs OTC Vol (UST Futures)
        </h1>
        <p className="mt-2 text-sm text-slate-400">
          Compare UST futures option ATM normal vol against matched OTC swaption ATMF normal vol.
          View timeseries, term structures, and vol smiles for both asset classes.
        </p>
      </section>

      {/* Tabs */}
      <div className="flex gap-2">
        {TABS.map(({ key, label }) => (
          <button
            key={key}
            onClick={() => setActiveTab(key)}
            className={`rounded-full border px-4 py-2 text-sm font-semibold transition ${
              activeTab === key
                ? 'border-slate-100 bg-slate-100 text-slate-950'
                : 'border-slate-700 bg-slate-900/70 text-slate-300 hover:border-sky-400/50 hover:text-white'
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <section className="rounded-3xl border border-slate-800 bg-slate-950/70 p-5">
        {activeTab === 'timeseries' && <TimeseriesModule />}
        {activeTab === 'term-structure' && <TermStructureModule />}
        {activeTab === 'smile' && <SmileModule />}
      </section>
    </div>
  )
}
