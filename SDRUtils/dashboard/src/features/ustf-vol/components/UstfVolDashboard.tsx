'use client'

import { useState } from 'react'

import { ComparisonSnapshotTable } from './ComparisonSnapshotTable'
import { DashboardSection } from './DashboardSection'
import { SmileModule } from './SmileModule'
import { TermStructureModule } from './TermStructureModule'
import { TimeseriesModule } from './TimeseriesModule'

type ModuleKey = 'timeseries' | 'termStructure' | 'smile'

const DEFAULT_EXPANDED_STATE: Record<ModuleKey, boolean> = {
  timeseries: true,
  termStructure: true,
  smile: true,
}

export default function UstfVolDashboard() {
  const [expanded, setExpanded] = useState<Record<ModuleKey, boolean>>(DEFAULT_EXPANDED_STATE)

  const toggleSection = (key: ModuleKey) => {
    setExpanded((current) => ({
      ...current,
      [key]: !current[key],
    }))
  }

  return (
    <div className="space-y-4 rounded-2xl border border-slate-800/80 bg-[radial-gradient(circle_at_top_left,rgba(51,65,85,0.2),transparent_28%),linear-gradient(180deg,rgba(15,23,42,0.94),rgba(2,6,23,0.98))] p-4 shadow-[0_24px_60px_rgba(2,6,23,0.22)]">
      <ComparisonSnapshotTable />

      <DashboardSection
        code="TS"
        title="Timeseries monitor"
        subtitle="Relative value tracking"
        expanded={expanded.timeseries}
        onToggle={() => toggleSection('timeseries')}
      >
        <TimeseriesModule />
      </DashboardSection>

      <DashboardSection
        code="TERM"
        title="Term structure"
        subtitle="Cross-section by product or tail"
        expanded={expanded.termStructure}
        onToggle={() => toggleSection('termStructure')}
      >
        <TermStructureModule />
      </DashboardSection>

      <DashboardSection
        code="SMILE"
        title="Vol smile"
        subtitle="Surface shape and SABR fit"
        expanded={expanded.smile}
        onToggle={() => toggleSection('smile')}
      >
        <SmileModule />
      </DashboardSection>
    </div>
  )
}
