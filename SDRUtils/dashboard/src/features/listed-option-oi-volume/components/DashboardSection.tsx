'use client'

import type { ReactNode } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'

type DashboardSectionProps = {
  code: string
  title: string
  subtitle: string
  expanded: boolean
  onToggle: () => void
  children: ReactNode
}

export function DashboardSection({
  code,
  title,
  subtitle,
  expanded,
  onToggle,
  children,
}: DashboardSectionProps) {
  return (
    <section className="overflow-hidden rounded-xl border border-slate-700/80 bg-[linear-gradient(180deg,rgba(15,23,42,0.9),rgba(2,6,23,0.94))] shadow-[0_16px_38px_rgba(2,6,23,0.24)]">
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-center justify-between gap-4 border-b border-slate-700/80 bg-slate-900/95 px-4 py-3 text-left transition hover:bg-slate-900"
      >
        <div className="flex min-w-0 items-center gap-3">
          <div className="rounded-md border border-slate-700 bg-slate-950 px-2 py-1 font-mono text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-300">
            {code}
          </div>
          <div className="min-w-0">
            <div className="truncate text-sm font-semibold text-slate-100">{title}</div>
            <div className="truncate text-[11px] uppercase tracking-[0.16em] text-slate-500">
              {subtitle}
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500">
          <span>{expanded ? 'Collapse' : 'Expand'}</span>
          {expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
        </div>
      </button>

      {expanded ? <div className="p-4 md:p-5">{children}</div> : null}
    </section>
  )
}
