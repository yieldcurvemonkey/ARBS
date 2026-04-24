'use client'
// Low-level primitives used by every analytics tab: Pill, SegGroup,
// PlatformDot, ToggleSwitch, NumberInput, Tabs.
import type { JSX, ReactNode } from 'react'
import { ANALYTICS_COLORS } from './analytics-format'
import type { PlatformKind } from './analytics-types'

type Accent = 'amber' | 'sky' | 'cyan' | 'emerald' | 'fuchsia' | 'slate'

export function Pill(props: {
  active: boolean
  onClick: () => void
  children: ReactNode
  accent?: Accent
  compact?: boolean
  title?: string
  className?: string
}): JSX.Element {
  const { active, onClick, children, accent, compact, title, className = '' } = props
  let activeCls = 'bg-slate-700 text-slate-100'
  if (accent === 'amber') activeCls = 'bg-amber-500/20 text-amber-100 ring-1 ring-amber-500/40'
  if (accent === 'sky') activeCls = 'bg-sky-500/20 text-sky-100 ring-1 ring-sky-500/40'
  if (accent === 'cyan') activeCls = 'bg-cyan-500/20 text-cyan-100 ring-1 ring-cyan-500/40'
  if (accent === 'emerald') activeCls = 'bg-emerald-500/20 text-emerald-100 ring-1 ring-emerald-500/40'
  if (accent === 'fuchsia') activeCls = 'bg-fuchsia-500/20 text-fuchsia-100 ring-1 ring-fuchsia-500/40'
  const inactiveCls = 'text-slate-300 hover:bg-slate-800'
  const size = compact ? 'px-2 py-[3px] text-[10.5px]' : 'px-2.5 py-1 text-[11px]'
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      className={`rounded border border-slate-700 ${size} font-mono whitespace-nowrap transition-colors ${
        active ? activeCls : inactiveCls
      } ${className}`}
    >
      {children}
    </button>
  )
}

export function SegGroup<K extends string>(props: {
  label?: string
  options: Array<{ key: K; label: string; title?: string }>
  value: K
  onChange: (v: K) => void
  accent?: Accent
  compact?: boolean
}): JSX.Element {
  return (
    <div className="flex flex-col gap-1">
      {props.label ? (
        <div className="text-[10px] uppercase tracking-wide text-slate-500">
          {props.label}
        </div>
      ) : null}
      <div className="flex gap-1">
        {props.options.map((o) => (
          <Pill
            key={o.key}
            active={props.value === o.key}
            onClick={() => props.onChange(o.key)}
            accent={props.accent}
            compact={props.compact}
            title={o.title}
          >
            {o.label}
          </Pill>
        ))}
      </div>
    </div>
  )
}

export function PlatformDot(props: { platform: PlatformKind; size?: number }): JSX.Element {
  const color = props.platform === 'CUSTY' ? ANALYTICS_COLORS.custy : ANALYTICS_COLORS.idb
  const s = props.size ?? 8
  return (
    <span
      aria-hidden
      className="inline-block rounded-full align-middle"
      style={{ width: s, height: s, backgroundColor: color }}
    />
  )
}

export function ToggleSwitch(props: {
  label: string
  on: boolean
  onChange: (v: boolean) => void
  accent?: 'amber' | 'sky' | 'emerald' | 'cyan'
  hint?: string
}): JSX.Element {
  const { label, on, onChange, accent = 'cyan', hint } = props
  const accentBg =
    accent === 'amber' ? 'bg-amber-500'
    : accent === 'sky' ? 'bg-sky-500'
    : accent === 'emerald' ? 'bg-emerald-500'
    : 'bg-cyan-500'
  return (
    <button
      type="button"
      onClick={() => onChange(!on)}
      title={hint}
      className="flex items-center gap-2 rounded border border-slate-800 bg-slate-900/60 px-2 py-1 text-[10.5px] font-mono text-slate-300 hover:bg-slate-900"
    >
      <span
        className={`relative inline-flex h-3.5 w-7 rounded-full transition-colors ${
          on ? accentBg : 'bg-slate-700'
        }`}
      >
        <span
          className={`absolute top-[2px] h-2.5 w-2.5 rounded-full bg-slate-100 transition-all ${
            on ? 'left-[16px]' : 'left-[2px]'
          }`}
        />
      </span>
      <span className={on ? 'text-slate-100' : 'text-slate-400'}>{label}</span>
    </button>
  )
}

export function NumberInput(props: {
  label: string
  value: string
  onChange: (v: string) => void
  placeholder?: string
  width?: number
}): JSX.Element {
  return (
    <label className="flex items-center gap-1 rounded border border-slate-800 bg-slate-900/60 px-1.5 py-[3px] text-[10.5px] font-mono text-slate-300">
      <span className="text-[10px] uppercase tracking-wide text-slate-500">{props.label}</span>
      <input
        type="text"
        value={props.value}
        onChange={(e) => props.onChange(e.target.value)}
        placeholder={props.placeholder}
        style={{ width: props.width ?? 56 }}
        className="bg-transparent text-slate-100 outline-none placeholder:text-slate-600"
      />
    </label>
  )
}

export function Tabs<K extends string>(props: {
  active: K
  onChange: (k: K) => void
  tabs: Array<{ key: K; label: string; icon?: string; badge?: string }>
}): JSX.Element {
  return (
    <div className="flex items-end gap-0.5 border-b border-slate-800">
      {props.tabs.map((t) => {
        const isActive = props.active === t.key
        return (
          <button
            key={t.key}
            type="button"
            onClick={() => props.onChange(t.key)}
            className={`group relative flex items-center gap-2 px-3 py-2 text-[11.5px] font-mono transition-colors ${
              isActive ? 'text-slate-100' : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            {t.icon ? <span className="text-slate-500">{t.icon}</span> : null}
            <span className="uppercase tracking-wide">{t.label}</span>
            {t.badge ? (
              <span className="rounded bg-slate-800 px-1.5 py-[1px] text-[9.5px] text-slate-300">
                {t.badge}
              </span>
            ) : null}
            <span
              className={`absolute inset-x-0 bottom-[-1px] h-[2px] ${
                isActive ? 'bg-indigo-400' : 'bg-transparent'
              }`}
            />
          </button>
        )
      })}
    </div>
  )
}
