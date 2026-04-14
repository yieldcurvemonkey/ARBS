'use client'
// ABOUTME: Right-side host for one of the three drawer sidecars.
import type { JSX } from 'react'
import { RiskConcentrationPanel } from './RiskConcentration/RiskConcentrationPanel'
import { PackageBrowserPanel } from './PackageBrowser/PackageBrowserPanel'
import { FomcClustersPanel } from './FomcClusters/FomcClustersPanel'

export type SidecarName = 'risk' | 'packages' | 'fomc' | null

export interface SidecarDrawerProps {
  active: SidecarName
  date: string
  clean?: boolean
  onChange: (n: SidecarName) => void
  onFilterByGroupValue?: (groupBy: string, value: string) => void
  onFilterByPackageId?: (packageId: string) => void
  onFilterByFomcMeeting?: (label: string) => void
}

const TABS: Array<{ key: Exclude<SidecarName, null>; label: string }> = [
  { key: 'risk', label: 'Risk' },
  { key: 'packages', label: 'Packages' },
  { key: 'fomc', label: 'FOMC' },
]

export function SidecarDrawer(props: SidecarDrawerProps): JSX.Element {
  return (
    <aside className="flex flex-col w-[360px] border-l border-slate-800 bg-slate-950 overflow-y-auto">
      <div className="flex items-center gap-1 px-2 py-1 border-b border-slate-800">
        {TABS.map((tab) => (
          <button
            key={tab.key}
            type="button"
            aria-pressed={props.active === tab.key}
            onClick={() => props.onChange(tab.key)}
            className={`text-xs px-2 py-1 rounded ${
              props.active === tab.key
                ? 'bg-slate-800 text-slate-100'
                : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            {tab.label}
          </button>
        ))}
        <div className="flex-1" />
        <button
          type="button"
          onClick={() => props.onChange(null)}
          className="text-xs px-2 py-1 rounded text-slate-400 hover:text-slate-200"
          aria-label="close sidecar"
        >
          ×
        </button>
      </div>
      <div className="flex-1">
        {props.active === 'risk' ? (
          <RiskConcentrationPanel
            date={props.date}
            clean={props.clean}
            onSelect={props.onFilterByGroupValue}
          />
        ) : null}
        {props.active === 'packages' ? (
          <PackageBrowserPanel
            date={props.date}
            onSelect={props.onFilterByPackageId}
          />
        ) : null}
        {props.active === 'fomc' ? (
          <FomcClustersPanel
            date={props.date}
            onSelect={props.onFilterByFomcMeeting}
          />
        ) : null}
      </div>
    </aside>
  )
}
