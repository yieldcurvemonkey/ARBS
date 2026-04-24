'use client'
// Always-visible one-line badge row above every analytics chart/table.
// Directly fulfills the trader ask: assumptions should never require a
// hover to discover.
import type { JSX, ReactNode } from 'react'
import { Fragment } from 'react'

export type AssumptionItem = {
  label: string
  value: string
  dim?: boolean
  trailing?: ReactNode
}

export function AssumptionsStrip(props: {
  items: AssumptionItem[]
  source?: string
}): JSX.Element {
  return (
    <div className="flex flex-wrap items-center gap-x-2 gap-y-1 rounded border border-slate-800 bg-slate-900/60 px-2.5 py-1.5 text-[10.5px] font-mono">
      {props.items.map((it, i) => (
        <Fragment key={it.label}>
          <span>
            <span className="mr-1.5 text-[9.5px] uppercase tracking-wide text-slate-500">
              {it.label}
            </span>
            <span className={it.dim ? 'text-slate-300' : 'text-slate-100'}>{it.value}</span>
            {it.trailing}
          </span>
          {i < props.items.length - 1 ? <span className="text-slate-700">·</span> : null}
        </Fragment>
      ))}
      {props.source ? (
        <span className="ml-auto text-[9.5px] text-slate-500">
          source <span className="text-slate-400">{props.source}</span>
        </span>
      ) : null}
    </div>
  )
}
