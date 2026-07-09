// ABOUTME: Tape-local marker chip for a manual override (GROUP/SPLIT/DETACH).
// Mirrors ManualLinkBadge's idioms but is intentionally NOT the shared component
// (swaptions must not inherit tape override semantics). GROUP reuses the amber
// language + a deterministic dot; SPLIT/DETACH use scissors / unlink icons.
import * as React from 'react'
import { Layers, Scissors, Unlink } from 'lucide-react'
import type { OverrideType } from '../../types/override.types'

export interface OverrideBadgeProps {
  overrideType: OverrideType
  manualPackageId?: string | null
  overrideId?: string | null
  onClick?: (overrideId: string) => void
  className?: string
}

const CONFIG: Record<
  OverrideType,
  { label: string; Icon: React.ComponentType<{ className?: string }>; tone: string }
> = {
  GROUP: { label: 'REGROUPED', Icon: Layers, tone: 'border-amber-500/60 bg-amber-900/40 text-amber-200' },
  SPLIT: { label: 'SPLIT', Icon: Scissors, tone: 'border-sky-500/60 bg-sky-900/40 text-sky-200' },
  DETACH: { label: 'DETACHED', Icon: Unlink, tone: 'border-rose-500/60 bg-rose-900/40 text-rose-200' },
}

// Local deterministic colour (self-contained; does not import shared color.ts).
function overrideColor(seed?: string | null): string | null {
  if (!seed) return null
  let hash = 0
  for (let i = 0; i < seed.length; i += 1) hash = (hash * 31 + seed.charCodeAt(i)) % 360
  return `hsl(${hash}, 65%, 52%)`
}

export function OverrideBadge(props: OverrideBadgeProps): React.ReactElement {
  const { overrideType, manualPackageId, overrideId, onClick, className } = props
  const cfg = CONFIG[overrideType]
  const Icon = cfg.Icon
  const dot = overrideColor(overrideId ?? manualPackageId)
  const base =
    `inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] uppercase tracking-wide ${cfg.tone} ${className ?? ''}`
      .trim()

  const inner = (
    <>
      {overrideType === 'GROUP' && dot ? (
        <span
          data-testid="override-dot"
          className="h-2 w-2 rounded-full"
          style={{ backgroundColor: dot }}
        />
      ) : (
        <Icon className="h-3 w-3" />
      )}
      <span>{cfg.label}</span>
      {manualPackageId ? (
        <span className="normal-case tracking-normal text-slate-400">{manualPackageId}</span>
      ) : null}
    </>
  )

  if (onClick && overrideId) {
    return (
      <button
        type="button"
        data-testid="override-badge"
        aria-label={`${cfg.label} override ${overrideId}`}
        className={`${base} hover:brightness-110`}
        onClick={(e) => {
          e.stopPropagation()
          onClick(overrideId)
        }}
      >
        {inner}
      </button>
    )
  }
  return (
    <span data-testid="override-badge" className={base} aria-label={`${cfg.label} override`}>
      {inner}
    </span>
  )
}
