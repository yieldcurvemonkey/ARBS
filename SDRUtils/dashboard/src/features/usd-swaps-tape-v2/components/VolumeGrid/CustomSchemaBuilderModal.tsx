'use client'
// ABOUTME: Custom schema builder supporting Grid mode (axis cross-product)
// and Strip mode (specific forward×tenor combos). Chip-based selection
// with IMM/FOMC forward support and custom tenor input.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { JSX, KeyboardEvent } from 'react'
import { Dialog } from 'primereact/dialog'
import type { BucketDef, PackageTypeGroupId } from '@/lib/usd-swaps-tape-v2/volumeGridBuckets'
import {
  computeImmDates,
  PACKAGE_TYPE_GROUP_IDS,
  PACKAGE_TYPE_GROUP_LABELS,
} from '@/lib/usd-swaps-tape-v2/volumeGridBuckets'

export type SchemaMode = 'grid' | 'strip'

export interface CustomSchema {
  name: string
  mode: SchemaMode
  tenorBuckets: BucketDef[]
  forwardBuckets: BucketDef[]
  packageType: PackageTypeGroupId
  stripCombos?: string[]
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

const ONE_DAY_MS = 86_400_000

function buildImmForwardChips(now: Date = new Date()): ChipDef[] {
  const imms = computeImmDates(now, 4)
  const fmt = new Intl.DateTimeFormat('en-US', { timeZone: 'UTC', month: 'short', year: '2-digit' })
  return imms.map((imm, i) => ({
    id: `imm${i + 1}`,
    label: `IMM${i + 1} (${fmt.format(imm).replace(' ', '')})`,
    years: (imm.getTime() - now.getTime()) / (365.25 * ONE_DAY_MS),
  }))
}

const FOMC_MONTHS: ReadonlyArray<[number, number]> = [
  [2025, 0], [2025, 2], [2025, 4], [2025, 6], [2025, 8], [2025, 11],
  [2026, 0], [2026, 2], [2026, 4], [2026, 5], [2026, 8], [2026, 10],
  [2027, 0], [2027, 2], [2027, 4], [2027, 5], [2027, 8], [2027, 10],
]
const MONTH_LABELS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']

function buildFomcForwardChips(now: Date = new Date()): ChipDef[] {
  return FOMC_MONTHS
    .map(([y, m]) => ({
      date: new Date(Date.UTC(y, m, 15)),
      label: `FOMC ${MONTH_LABELS[m]}${String(y % 100).padStart(2, '0')}`,
      id: `fomc_${MONTH_LABELS[m].toLowerCase()}${String(y % 100).padStart(2, '0')}`,
    }))
    .filter(x => x.date.getTime() > now.getTime())
    .slice(0, 6)
    .map(x => ({
      id: x.id,
      label: x.label,
      years: (x.date.getTime() - now.getTime()) / (365.25 * ONE_DAY_MS),
    }))
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

function buildForwardChips(): ChipDef[] {
  const base: ChipDef[] = [
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
  const imm = buildImmForwardChips()
  const fomc = buildFomcForwardChips()
  return [...base, ...imm, ...fomc].sort((a, b) => a.years - b.years)
}

const TENOR_PRESETS: { label: string; ids: string[] }[] = [
  { label: 'Benchmarks', ids: ['2y', '3y', '5y', '7y', '10y', '20y', '30y'] },
  { label: 'Front End',  ids: ['1y', '2y', '3y', '4y', '5y'] },
  { label: 'Back End',   ids: ['10y', '15y', '20y', '25y', '30y'] },
  { label: 'All',        ids: TENOR_CHIPS.map(c => c.id) },
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

function makeCustomChip(years: number): ChipDef {
  const label = years < 1
    ? `${Math.round(years * 12)}M`
    : Number.isInteger(years) ? `${years}Y` : `${years}Y`
  return { id: label.toLowerCase(), label, years, custom: true }
}

function mergeChips(defaults: ChipDef[], extras: ChipDef[]): ChipDef[] {
  const seen = new Set(defaults.map(c => c.id))
  const novel = extras.filter(c => !seen.has(c.id))
  return [...defaults, ...novel].sort((a, b) => a.years - b.years)
}

function bucketsToChips(buckets: BucketDef[], defaultChips: ChipDef[]): ChipDef[] {
  const defaultMap = new Map(defaultChips.map(c => [c.id, c]))
  return buckets.map(b => {
    const match = defaultMap.get(b.id)
    if (match) return match
    const years = b.lo != null && b.hi != null ? (b.lo + b.hi) / 2 : b.lo ?? b.hi ?? 0
    return { id: b.id, label: b.label, years, custom: true }
  })
}

function comboKey(fwdId: string, tenorId: string): string { return `${fwdId}|${tenorId}` }

export function CustomSchemaBuilderModal({
  open, onClose, onApply, initialSchema,
}: CustomSchemaBuilderModalProps): JSX.Element {
  const defaultForwardChips = useMemo(() => buildForwardChips(), [])
  const [mode, setMode] = useState<SchemaMode>('grid')
  const [name, setName] = useState('')
  const [tenorChips, setTenorChips] = useState<ChipDef[]>(TENOR_CHIPS)
  const [forwardChips, setForwardChips] = useState<ChipDef[]>(defaultForwardChips)
  const [selectedTenors, setSelectedTenors] = useState<Set<string>>(new Set())
  const [selectedForwards, setSelectedForwards] = useState<Set<string>>(new Set())
  const [selectedCombos, setSelectedCombos] = useState<Set<string>>(new Set())
  const [packageType, setPackageType] = useState<PackageTypeGroupId>('all')
  const [errors, setErrors] = useState<string[]>([])

  useEffect(() => {
    if (!open) return
    if (initialSchema) {
      setMode(initialSchema.mode ?? 'grid')
      setName(initialSchema.name)
      const tChips = bucketsToChips(initialSchema.tenorBuckets, TENOR_CHIPS)
      const fChips = bucketsToChips(initialSchema.forwardBuckets, defaultForwardChips)
      setTenorChips(mergeChips(TENOR_CHIPS, tChips))
      setForwardChips(mergeChips(defaultForwardChips, fChips))
      setSelectedTenors(new Set(tChips.map(c => c.id)))
      setSelectedForwards(new Set(fChips.map(c => c.id)))
      setSelectedCombos(new Set(initialSchema.stripCombos ?? []))
      setPackageType(initialSchema.packageType)
    } else {
      setMode('grid')
      setName('')
      setTenorChips(TENOR_CHIPS)
      setForwardChips(defaultForwardChips)
      setSelectedTenors(new Set())
      setSelectedForwards(new Set())
      setSelectedCombos(new Set())
      setPackageType('all')
    }
    setErrors([])
  }, [open, initialSchema, defaultForwardChips])

  const toggleChip = useCallback((set: Set<string>, setFn: (s: Set<string>) => void, id: string) => {
    const next = new Set(set)
    if (next.has(id)) next.delete(id); else next.add(id)
    setFn(next)
  }, [])

  const addCustomChip = useCallback((
    chips: ChipDef[], setChips: (c: ChipDef[]) => void,
    selected: Set<string>, setSelected: (s: Set<string>) => void,
    years: number,
  ) => {
    const chip = makeCustomChip(years)
    if (chips.some(c => c.id === chip.id)) {
      const next = new Set(selected); next.add(chip.id); setSelected(next)
      return
    }
    setChips([...chips, chip].sort((a, b) => a.years - b.years))
    const next = new Set(selected); next.add(chip.id); setSelected(next)
  }, [])

  const removeCustomChip = useCallback((
    chips: ChipDef[], setChips: (c: ChipDef[]) => void,
    selected: Set<string>, setSelected: (s: Set<string>) => void,
    id: string,
  ) => {
    setChips(chips.filter(c => c.id !== id))
    const next = new Set(selected); next.delete(id); setSelected(next)
    setSelectedCombos(prev => {
      const n = new Set(prev)
      for (const k of n) { if (k.startsWith(id + '|') || k.endsWith('|' + id)) n.delete(k) }
      return n
    })
  }, [])

  const toggleCombo = useCallback((fwd: string, tenor: string) => {
    const key = comboKey(fwd, tenor)
    setSelectedCombos(prev => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key); else next.add(key)
      return next
    })
  }, [])

  const stripForwards = useMemo(() => forwardChips.filter(c => {
    for (const k of selectedCombos) { if (k.startsWith(c.id + '|')) return true }
    return false
  }), [forwardChips, selectedCombos])

  const stripTenors = useMemo(() => tenorChips.filter(c => {
    for (const k of selectedCombos) { if (k.endsWith('|' + c.id)) return true }
    return false
  }), [tenorChips, selectedCombos])

  const handleApply = useCallback(() => {
    const errs: string[] = []
    if (!name.trim()) errs.push('Name is required.')
    if (mode === 'grid') {
      if (selectedTenors.size === 0) errs.push('Select at least one tenor.')
      if (selectedForwards.size === 0) errs.push('Select at least one forward start.')
    } else {
      if (selectedCombos.size === 0) errs.push('Select at least one forward×tenor combo.')
    }
    if (errs.length > 0) { setErrors(errs); return }
    setErrors([])

    let tenorBuckets: BucketDef[]
    let forwardBuckets: BucketDef[]
    if (mode === 'grid') {
      tenorBuckets = tenorChips.filter(c => selectedTenors.has(c.id)).map(c => chipToBucket(c, false))
      forwardBuckets = forwardChips.filter(c => selectedForwards.has(c.id)).map(c => chipToBucket(c, true))
    } else {
      forwardBuckets = stripForwards.map(c => chipToBucket(c, true))
      tenorBuckets = stripTenors.map(c => chipToBucket(c, false))
    }
    onApply({
      name: name.trim(), mode, tenorBuckets, forwardBuckets, packageType,
      stripCombos: mode === 'strip' ? [...selectedCombos] : undefined,
    })
  }, [name, mode, selectedTenors, selectedForwards, selectedCombos, tenorChips, forwardChips, stripForwards, stripTenors, packageType, onApply])

  const cellCount = mode === 'grid'
    ? selectedTenors.size * selectedForwards.size
    : selectedCombos.size

  return (
    <Dialog header="Custom Schema Builder" visible={open} onHide={onClose}
      style={{ width: '70vw', maxWidth: 880 }} modal>
      <div className="flex flex-col gap-4 text-slate-200">
        {/* Header row */}
        <div className="flex flex-wrap items-end gap-3">
          <label className="flex flex-col gap-1">
            <span className="font-mono text-[10px] uppercase tracking-wider text-slate-400">Name</span>
            <input type="text" value={name} onChange={(e) => setName(e.target.value)}
              placeholder="e.g. 1y fwd gap"
              className="w-48 rounded border border-slate-700 bg-slate-900 px-2 py-[3px] font-mono text-[10.5px] text-slate-200 placeholder:text-slate-600" />
          </label>
          <label className="flex flex-col gap-1">
            <span className="font-mono text-[10px] uppercase tracking-wider text-slate-400">Format</span>
            <div className="flex items-center rounded border border-slate-700 p-[1px]">
              {(['grid', 'strip'] as const).map(m => (
                <button key={m} type="button" onClick={() => setMode(m)}
                  className={`px-2.5 py-[2px] font-mono text-[10.5px] capitalize ${mode === m ? 'bg-indigo-500/25 text-indigo-100' : 'text-slate-400 hover:text-slate-200'}`}
                >{m}</button>
              ))}
            </div>
          </label>
          <label className="flex flex-col gap-1">
            <span className="font-mono text-[10px] uppercase tracking-wider text-slate-400">Package Type</span>
            <select value={packageType} onChange={(e) => setPackageType(e.target.value as PackageTypeGroupId)}
              className="rounded border border-slate-700 bg-slate-900 px-2 py-[3px] font-mono text-[10.5px] text-slate-200 hover:bg-slate-800">
              {PACKAGE_TYPE_GROUP_IDS.map(id => (
                <option key={id} value={id}>{PACKAGE_TYPE_GROUP_LABELS[id]}</option>
              ))}
            </select>
          </label>
        </div>

        {mode === 'grid' ? (
          <>
            <ChipSection title="Tenor Axis" chips={tenorChips} selected={selectedTenors}
              onToggle={(id) => toggleChip(selectedTenors, setSelectedTenors, id)}
              onAddCustom={(y) => addCustomChip(tenorChips, setTenorChips, selectedTenors, setSelectedTenors, y)}
              onRemoveCustom={(id) => removeCustomChip(tenorChips, setTenorChips, selectedTenors, setSelectedTenors, id)}
              presets={TENOR_PRESETS}
              onPreset={(ids) => { setTenorChips(TENOR_CHIPS); setSelectedTenors(new Set(ids)) }}
              placeholder="e.g. 8 or 4.5" />
            <ChipSection title="Forward Axis" chips={forwardChips} selected={selectedForwards}
              onToggle={(id) => toggleChip(selectedForwards, setSelectedForwards, id)}
              onAddCustom={(y) => addCustomChip(forwardChips, setForwardChips, selectedForwards, setSelectedForwards, y)}
              onRemoveCustom={(id) => removeCustomChip(forwardChips, setForwardChips, selectedForwards, setSelectedForwards, id)}
              presets={[]}
              onPreset={() => {}}
              placeholder="e.g. 1.5 or 4" />
          </>
        ) : (
          <ComboMatrix
            forwardChips={forwardChips}
            tenorChips={tenorChips}
            selectedCombos={selectedCombos}
            onToggle={toggleCombo}
            onAddCustomTenor={(y) => addCustomChip(tenorChips, setTenorChips, new Set(), () => {}, y)}
            onAddCustomForward={(y) => addCustomChip(forwardChips, setForwardChips, new Set(), () => {}, y)}
          />
        )}

        {errors.length > 0 && (
          <div className="rounded border border-rose-500/30 bg-rose-500/10 px-3 py-2 font-mono text-[10.5px] text-rose-300">
            {errors.map((e, i) => <div key={i}>{e}</div>)}
          </div>
        )}

        <div className="flex items-center justify-between pt-1">
          <div className="font-mono text-[9.5px] text-slate-500">
            {cellCount} cell{cellCount !== 1 ? 's' : ''} selected
          </div>
          <div className="flex items-center gap-2">
            <button type="button" onClick={onClose}
              className="rounded border border-slate-700 px-3 py-[3px] font-mono text-[10.5px] text-slate-300 hover:bg-slate-800">Cancel</button>
            <button type="button" onClick={handleApply}
              className="rounded border border-indigo-500/40 bg-indigo-500/25 px-3 py-[3px] font-mono text-[10.5px] text-indigo-100 hover:bg-indigo-500/35">Apply</button>
          </div>
        </div>
      </div>
    </Dialog>
  )
}

function ComboMatrix({ forwardChips, tenorChips, selectedCombos, onToggle, onAddCustomTenor, onAddCustomForward }: {
  forwardChips: ChipDef[]
  tenorChips: ChipDef[]
  selectedCombos: Set<string>
  onToggle: (fwd: string, tenor: string) => void
  onAddCustomTenor: (years: number) => void
  onAddCustomForward: (years: number) => void
}): JSX.Element {
  const tenorInputRef = useRef<HTMLInputElement>(null)
  const fwdInputRef = useRef<HTMLInputElement>(null)

  const selectRow = (fwdId: string) => {
    const allSelected = tenorChips.every(t => selectedCombos.has(comboKey(fwdId, t.id)))
    tenorChips.forEach(t => {
      const key = comboKey(fwdId, t.id)
      if (allSelected ? selectedCombos.has(key) : !selectedCombos.has(key)) onToggle(fwdId, t.id)
    })
  }
  const selectCol = (tenorId: string) => {
    const allSelected = forwardChips.every(f => selectedCombos.has(comboKey(f.id, tenorId)))
    forwardChips.forEach(f => {
      const key = comboKey(f.id, tenorId)
      if (allSelected ? selectedCombos.has(key) : !selectedCombos.has(key)) onToggle(f.id, tenorId)
    })
  }

  return (
    <div>
      <div className="mb-1.5 flex items-center gap-2">
        <span className="font-mono text-[10px] uppercase tracking-wider text-slate-400">
          Click cells to select forward×tenor combos
        </span>
        <span className="font-mono text-[9px] text-slate-600">click row/col headers to select entire row/col</span>
      </div>
      <div className="overflow-x-auto rounded border border-slate-800 bg-slate-950/40">
        <table className="border-collapse font-mono text-[10px]">
          <thead>
            <tr>
              <th className="sticky left-0 z-10 bg-slate-950 px-1.5 py-1 text-left text-[9px] text-slate-500">fwd \ tenor</th>
              {tenorChips.map(t => (
                <th key={t.id} className="cursor-pointer px-1 py-1 text-center text-[9px] text-slate-400 hover:text-indigo-300"
                  onClick={() => selectCol(t.id)}>{t.label}</th>
              ))}
              <th className="px-1 py-1">
                <input ref={tenorInputRef} type="text" placeholder="+"
                  className="w-8 bg-transparent text-center text-[9px] text-slate-500 placeholder:text-slate-600 focus:outline-none focus:text-slate-300"
                  onKeyDown={(e) => {
                    if (e.key !== 'Enter') return
                    const v = Number(tenorInputRef.current?.value)
                    if (Number.isFinite(v) && v > 0) { onAddCustomTenor(v); if (tenorInputRef.current) tenorInputRef.current.value = '' }
                  }} />
              </th>
            </tr>
          </thead>
          <tbody>
            {forwardChips.map(f => (
              <tr key={f.id}>
                <td className="sticky left-0 z-10 cursor-pointer whitespace-nowrap bg-slate-950 px-1.5 py-0.5 text-[9px] text-slate-400 hover:text-indigo-300"
                  onClick={() => selectRow(f.id)}>{f.label}</td>
                {tenorChips.map(t => {
                  const active = selectedCombos.has(comboKey(f.id, t.id))
                  return (
                    <td key={t.id} className="p-0.5">
                      <button type="button" onClick={() => onToggle(f.id, t.id)}
                        className={`h-5 w-full min-w-[28px] rounded-sm border text-[8px] transition-colors ${
                          active
                            ? 'border-indigo-400/60 bg-indigo-500/40 text-indigo-200'
                            : 'border-slate-800 text-slate-600 hover:border-slate-600 hover:text-slate-400'
                        }`}>
                        {active ? '●' : ''}
                      </button>
                    </td>
                  )
                })}
                <td />
              </tr>
            ))}
            <tr>
              <td className="sticky left-0 z-10 bg-slate-950 px-1.5 py-0.5">
                <input ref={fwdInputRef} type="text" placeholder="+ fwd"
                  className="w-12 bg-transparent text-[9px] text-slate-500 placeholder:text-slate-600 focus:outline-none focus:text-slate-300"
                  onKeyDown={(e) => {
                    if (e.key !== 'Enter') return
                    const v = Number(fwdInputRef.current?.value)
                    if (Number.isFinite(v) && v >= 0) { onAddCustomForward(v); if (fwdInputRef.current) fwdInputRef.current.value = '' }
                  }} />
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  )
}

function ChipSection({ title, chips, selected, onToggle, onAddCustom, onRemoveCustom, presets, onPreset, placeholder }: {
  title: string; chips: ChipDef[]; selected: Set<string>
  onToggle: (id: string) => void; onAddCustom: (years: number) => void; onRemoveCustom: (id: string) => void
  presets: { label: string; ids: string[] }[]; onPreset: (ids: string[]) => void; placeholder: string
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
          {presets.map(p => (
            <button key={p.label} type="button" onClick={() => onPreset(p.ids)}
              className="rounded border border-slate-700/60 px-1.5 py-[0px] font-mono text-[9px] text-slate-500 hover:bg-slate-800 hover:text-slate-300">{p.label}</button>
          ))}
          {presets.length > 0 && (
            <button type="button" onClick={() => onPreset([])}
              className="rounded border border-slate-700/60 px-1.5 py-[0px] font-mono text-[9px] text-slate-500 hover:bg-slate-800 hover:text-slate-300">Clear</button>
          )}
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-1">
        {chips.map(chip => {
          const active = selected.has(chip.id)
          return (
            <div key={chip.id} className="group relative">
              <button type="button" onClick={() => onToggle(chip.id)}
                className={`rounded border px-2.5 py-[3px] font-mono text-[11px] transition-colors ${
                  active ? 'border-indigo-400/50 bg-indigo-500/30 text-indigo-100'
                    : 'border-slate-700 text-slate-400 hover:border-slate-600 hover:text-slate-200'
                }`}>{chip.label}</button>
              {chip.custom && (
                <button type="button" onClick={(e) => { e.stopPropagation(); onRemoveCustom(chip.id) }}
                  className="absolute -right-1 -top-1 hidden h-3.5 w-3.5 items-center justify-center rounded-full bg-slate-700 text-[8px] text-slate-300 hover:bg-rose-600 group-hover:flex">×</button>
              )}
            </div>
          )
        })}
        <input ref={inputRef} type="text" placeholder={placeholder} onKeyDown={handleKeyDown}
          className="w-20 rounded border border-dashed border-slate-600 bg-transparent px-1.5 py-[3px] font-mono text-[10px] text-slate-300 placeholder:text-slate-600 focus:border-indigo-500/50 focus:outline-none" />
      </div>
    </div>
  )
}
