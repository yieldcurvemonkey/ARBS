'use client'
// ABOUTME: Chip-based custom schema builder for the volume grid. Users
// toggle tenor and forward-start chips to build bucket axes, with an
// inline input for adding arbitrary custom tenors. Boundaries are
// auto-computed from standard ±tolerance windows.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { JSX, KeyboardEvent } from 'react'
import { Dialog } from 'primereact/dialog'
import type { BucketDef, PackageTypeGroupId } from '@/lib/usd-swaps-tape-v2/volumeGridBuckets'
import {
  PACKAGE_TYPE_GROUP_IDS,
  PACKAGE_TYPE_GROUP_LABELS,
} from '@/lib/usd-swaps-tape-v2/volumeGridBuckets'

export interface CustomSchema {
  name: string
  tenorBuckets: BucketDef[]
  forwardBuckets: BucketDef[]
  packageType: PackageTypeGroupId
}

export interface CustomSchemaBuilderModalProps {
  open: boolean
  onClose: () => void
  onApply: (schema: CustomSchema) => void
  initialSchema?: CustomSchema
}

interface ChipDef {
  id: string
  label: string
  years: number
  custom?: boolean
}

const TENOR_CHIPS: ChipDef[] = [
  { id: '1y',  label: '1Y',  years: 1 },
  { id: '2y',  label: '2Y',  years: 2 },
  { id: '3y',  label: '3Y',  years: 3 },
  { id: '4y',  label: '4Y',  years: 4 },
  { id: '5y',  label: '5Y',  years: 5 },
  { id: '7y',  label: '7Y',  years: 7 },
  { id: '10y', label: '10Y', years: 10 },
  { id: '12y', label: '12Y', years: 12 },
  { id: '15y', label: '15Y', years: 15 },
  { id: '20y', label: '20Y', years: 20 },
  { id: '25y', label: '25Y', years: 25 },
  { id: '30y', label: '30Y', years: 30 },
]

const FORWARD_CHIPS: ChipDef[] = [
  { id: 'spot', label: 'Spot', years: 0 },
  { id: '3m',   label: '3M',   years: 0.25 },
  { id: '6m',   label: '6M',   years: 0.5 },
  { id: '1y',   label: '1Y',   years: 1 },
  { id: '2y',   label: '2Y',   years: 2 },
  { id: '3y',   label: '3Y',   years: 3 },
  { id: '5y',   label: '5Y',   years: 5 },
  { id: '7y',   label: '7Y',   years: 7 },
  { id: '10y',  label: '10Y',  years: 10 },
]

const TENOR_PRESETS: { label: string; ids: string[] }[] = [
  { label: 'Benchmarks', ids: ['2y', '3y', '5y', '7y', '10y', '20y', '30y'] },
  { label: 'Front End',  ids: ['1y', '2y', '3y', '4y', '5y'] },
  { label: 'Back End',   ids: ['10y', '15y', '20y', '25y', '30y'] },
  { label: 'All',        ids: TENOR_CHIPS.map(c => c.id) },
]

const FORWARD_PRESETS: { label: string; ids: string[] }[] = [
  { label: 'Spot Only', ids: ['spot'] },
  { label: 'Spot + 1Y', ids: ['spot', '1y'] },
  { label: 'Gaps',      ids: ['spot', '1y', '2y', '3y', '5y'] },
  { label: 'All',       ids: FORWARD_CHIPS.map(c => c.id) },
]

function chipToBucket(chip: ChipDef, isForward: boolean): BucketDef {
  if (isForward && chip.years === 0) {
    return { id: chip.id, label: chip.label, lo: null, hi: 0.0192 }
  }
  const tolerance = chip.years <= 1 ? 0.125 : chip.years <= 5 ? 0.5 : 1.0
  return {
    id: chip.id,
    label: chip.label,
    lo: Math.max(0, chip.years - tolerance),
    hi: chip.years + tolerance,
  }
}

function makeCustomChip(years: number, isForward: boolean): ChipDef {
  const label = years < 1
    ? `${Math.round(years * 12)}M`
    : Number.isInteger(years) ? `${years}Y` : `${years}Y`
  const id = label.toLowerCase()
  return { id, label, years, custom: true }
}

function bucketsToChips(buckets: BucketDef[], defaultChips: ChipDef[]): ChipDef[] {
  const chips: ChipDef[] = []
  const defaultMap = new Map(defaultChips.map(c => [c.id, c]))
  for (const b of buckets) {
    const match = defaultMap.get(b.id)
    if (match) {
      chips.push(match)
    } else {
      const years = b.lo != null && b.hi != null ? (b.lo + b.hi) / 2 : b.lo ?? b.hi ?? 0
      chips.push({ id: b.id, label: b.label, years, custom: true })
    }
  }
  return chips
}

export function CustomSchemaBuilderModal({
  open,
  onClose,
  onApply,
  initialSchema,
}: CustomSchemaBuilderModalProps): JSX.Element {
  const [name, setName] = useState('')
  const [tenorChips, setTenorChips] = useState<ChipDef[]>(TENOR_CHIPS)
  const [forwardChips, setForwardChips] = useState<ChipDef[]>(FORWARD_CHIPS)
  const [selectedTenors, setSelectedTenors] = useState<Set<string>>(new Set())
  const [selectedForwards, setSelectedForwards] = useState<Set<string>>(new Set())
  const [packageType, setPackageType] = useState<PackageTypeGroupId>('all')
  const [errors, setErrors] = useState<string[]>([])

  useEffect(() => {
    if (!open) return
    if (initialSchema) {
      setName(initialSchema.name)
      const tChips = bucketsToChips(initialSchema.tenorBuckets, TENOR_CHIPS)
      const fChips = bucketsToChips(initialSchema.forwardBuckets, FORWARD_CHIPS)
      const mergedTenors = mergeChips(TENOR_CHIPS, tChips)
      const mergedForwards = mergeChips(FORWARD_CHIPS, fChips)
      setTenorChips(mergedTenors)
      setForwardChips(mergedForwards)
      setSelectedTenors(new Set(tChips.map(c => c.id)))
      setSelectedForwards(new Set(fChips.map(c => c.id)))
      setPackageType(initialSchema.packageType)
    } else {
      setTenorChips(TENOR_CHIPS)
      setForwardChips(FORWARD_CHIPS)
      setSelectedTenors(new Set())
      setSelectedForwards(new Set())
      setPackageType('all')
    }
    setErrors([])
  }, [open, initialSchema])

  const toggleChip = useCallback((set: Set<string>, setFn: (s: Set<string>) => void, id: string) => {
    const next = new Set(set)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    setFn(next)
  }, [])

  const addCustomChip = useCallback((
    chips: ChipDef[],
    setChips: (c: ChipDef[]) => void,
    selected: Set<string>,
    setSelected: (s: Set<string>) => void,
    years: number,
    isForward: boolean,
  ) => {
    const chip = makeCustomChip(years, isForward)
    if (chips.some(c => c.id === chip.id)) {
      const next = new Set(selected)
      next.add(chip.id)
      setSelected(next)
      return
    }
    const merged = [...chips, chip].sort((a, b) => a.years - b.years)
    setChips(merged)
    const next = new Set(selected)
    next.add(chip.id)
    setSelected(next)
  }, [])

  const removeCustomChip = useCallback((
    chips: ChipDef[],
    setChips: (c: ChipDef[]) => void,
    selected: Set<string>,
    setSelected: (s: Set<string>) => void,
    id: string,
  ) => {
    setChips(chips.filter(c => c.id !== id))
    const next = new Set(selected)
    next.delete(id)
    setSelected(next)
  }, [])

  const applyPreset = useCallback((
    setChips: (c: ChipDef[]) => void,
    defaultChips: ChipDef[],
    setSelected: (s: Set<string>) => void,
    ids: string[],
  ) => {
    setChips(defaultChips)
    setSelected(new Set(ids))
  }, [])

  const tenorBuckets = useMemo(() =>
    tenorChips.filter(c => selectedTenors.has(c.id)).map(c => chipToBucket(c, false)),
    [tenorChips, selectedTenors],
  )
  const forwardBuckets = useMemo(() =>
    forwardChips.filter(c => selectedForwards.has(c.id)).map(c => chipToBucket(c, true)),
    [forwardChips, selectedForwards],
  )

  const handleApply = useCallback(() => {
    const errs: string[] = []
    if (!name.trim()) errs.push('Name is required.')
    if (selectedTenors.size === 0) errs.push('Select at least one tenor.')
    if (selectedForwards.size === 0) errs.push('Select at least one forward start.')
    if (errs.length > 0) { setErrors(errs); return }
    setErrors([])
    onApply({ name: name.trim(), tenorBuckets, forwardBuckets, packageType })
  }, [name, selectedTenors, selectedForwards, tenorBuckets, forwardBuckets, packageType, onApply])

  return (
    <Dialog
      header="Custom Schema Builder"
      visible={open}
      onHide={onClose}
      style={{ width: '56vw', maxWidth: 720 }}
      modal
    >
      <div className="flex flex-col gap-4 text-slate-200">
        <div className="flex flex-wrap items-end gap-3">
          <label className="flex flex-col gap-1">
            <span className="font-mono text-[10px] uppercase tracking-wider text-slate-400">Name</span>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. 1y fwd gap"
              className="w-48 rounded border border-slate-700 bg-slate-900 px-2 py-[3px] font-mono text-[10.5px] text-slate-200 placeholder:text-slate-600"
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="font-mono text-[10px] uppercase tracking-wider text-slate-400">Package Type</span>
            <select
              value={packageType}
              onChange={(e) => setPackageType(e.target.value as PackageTypeGroupId)}
              className="rounded border border-slate-700 bg-slate-900 px-2 py-[3px] font-mono text-[10.5px] text-slate-200 hover:bg-slate-800"
            >
              {PACKAGE_TYPE_GROUP_IDS.map((id) => (
                <option key={id} value={id}>{PACKAGE_TYPE_GROUP_LABELS[id]}</option>
              ))}
            </select>
          </label>
        </div>

        <ChipSection
          title="Tenor Axis"
          chips={tenorChips}
          selected={selectedTenors}
          onToggle={(id) => toggleChip(selectedTenors, setSelectedTenors, id)}
          onAddCustom={(years) => addCustomChip(tenorChips, setTenorChips, selectedTenors, setSelectedTenors, years, false)}
          onRemoveCustom={(id) => removeCustomChip(tenorChips, setTenorChips, selectedTenors, setSelectedTenors, id)}
          presets={TENOR_PRESETS}
          onPreset={(ids) => applyPreset(setTenorChips, TENOR_CHIPS, setSelectedTenors, ids)}
          placeholder="e.g. 8 or 4.5"
        />

        <ChipSection
          title="Forward Axis"
          chips={forwardChips}
          selected={selectedForwards}
          onToggle={(id) => toggleChip(selectedForwards, setSelectedForwards, id)}
          onAddCustom={(years) => addCustomChip(forwardChips, setForwardChips, selectedForwards, setSelectedForwards, years, true)}
          onRemoveCustom={(id) => removeCustomChip(forwardChips, setForwardChips, selectedForwards, setSelectedForwards, id)}
          presets={FORWARD_PRESETS}
          onPreset={(ids) => applyPreset(setForwardChips, FORWARD_CHIPS, setSelectedForwards, ids)}
          placeholder="e.g. 1.5 or 4"
        />

        {errors.length > 0 && (
          <div className="rounded border border-rose-500/30 bg-rose-500/10 px-3 py-2 font-mono text-[10.5px] text-rose-300">
            {errors.map((e, i) => <div key={i}>{e}</div>)}
          </div>
        )}

        <div className="flex items-center justify-between pt-1">
          <div className="font-mono text-[9.5px] text-slate-500">
            {selectedTenors.size} tenors × {selectedForwards.size} forwards = {selectedTenors.size * selectedForwards.size} cells
          </div>
          <div className="flex items-center gap-2">
            <button type="button" onClick={onClose}
              className="rounded border border-slate-700 px-3 py-[3px] font-mono text-[10.5px] text-slate-300 hover:bg-slate-800"
            >Cancel</button>
            <button type="button" onClick={handleApply}
              className="rounded border border-indigo-500/40 bg-indigo-500/25 px-3 py-[3px] font-mono text-[10.5px] text-indigo-100 hover:bg-indigo-500/35"
            >Apply</button>
          </div>
        </div>
      </div>
    </Dialog>
  )
}

function mergeChips(defaults: ChipDef[], active: ChipDef[]): ChipDef[] {
  const seen = new Set(defaults.map(c => c.id))
  const extras = active.filter(c => !seen.has(c.id))
  return [...defaults, ...extras].sort((a, b) => a.years - b.years)
}

function ChipSection({
  title,
  chips,
  selected,
  onToggle,
  onAddCustom,
  onRemoveCustom,
  presets,
  onPreset,
  placeholder,
}: {
  title: string
  chips: ChipDef[]
  selected: Set<string>
  onToggle: (id: string) => void
  onAddCustom: (years: number) => void
  onRemoveCustom: (id: string) => void
  presets: { label: string; ids: string[] }[]
  onPreset: (ids: string[]) => void
  placeholder: string
}): JSX.Element {
  const inputRef = useRef<HTMLInputElement>(null)

  const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key !== 'Enter') return
    const val = Number(inputRef.current?.value)
    if (!Number.isFinite(val) || val < 0) return
    onAddCustom(val)
    if (inputRef.current) inputRef.current.value = ''
  }

  return (
    <div>
      <div className="mb-1.5 flex items-center gap-2">
        <span className="font-mono text-[10px] uppercase tracking-wider text-slate-400">{title}</span>
        <div className="flex items-center gap-1">
          {presets.map((p) => (
            <button key={p.label} type="button" onClick={() => onPreset(p.ids)}
              className="rounded border border-slate-700/60 px-1.5 py-[0px] font-mono text-[9px] text-slate-500 hover:bg-slate-800 hover:text-slate-300"
            >{p.label}</button>
          ))}
          <button type="button" onClick={() => onPreset([])}
            className="rounded border border-slate-700/60 px-1.5 py-[0px] font-mono text-[9px] text-slate-500 hover:bg-slate-800 hover:text-slate-300"
          >Clear</button>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-1">
        {chips.map((chip) => {
          const active = selected.has(chip.id)
          return (
            <div key={chip.id} className="group relative">
              <button
                type="button"
                onClick={() => onToggle(chip.id)}
                className={`rounded border px-2.5 py-[3px] font-mono text-[11px] transition-colors ${
                  active
                    ? 'border-indigo-400/50 bg-indigo-500/30 text-indigo-100'
                    : 'border-slate-700 text-slate-400 hover:border-slate-600 hover:text-slate-200'
                }`}
              >
                {chip.label}
              </button>
              {chip.custom && (
                <button
                  type="button"
                  onClick={(e) => { e.stopPropagation(); onRemoveCustom(chip.id) }}
                  className="absolute -right-1 -top-1 hidden h-3.5 w-3.5 items-center justify-center rounded-full bg-slate-700 text-[8px] text-slate-300 hover:bg-rose-600 group-hover:flex"
                >×</button>
              )}
            </div>
          )
        })}
        <input
          ref={inputRef}
          type="text"
          placeholder={placeholder}
          onKeyDown={handleKeyDown}
          className="w-20 rounded border border-dashed border-slate-600 bg-transparent px-1.5 py-[3px] font-mono text-[10px] text-slate-300 placeholder:text-slate-600 focus:border-indigo-500/50 focus:outline-none"
        />
      </div>
    </div>
  )
}
