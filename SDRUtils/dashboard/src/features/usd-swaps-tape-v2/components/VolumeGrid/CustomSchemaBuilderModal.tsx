'use client'
// ABOUTME: PrimeReact Dialog modal for building custom volume-grid schemas.
// Lets users define tenor and forward bucket axes with lo/hi ranges,
// pick a package type, and optionally load a preset as a starting point.
// Schemas are persisted to localStorage by the parent CustomGridView.

import { useCallback, useEffect, useState } from 'react'
import type { JSX } from 'react'
import { Dialog } from 'primereact/dialog'
import type { BucketDef, PackageTypeGroupId } from '@/lib/usd-swaps-tape-v2/volumeGridBuckets'
import {
  PACKAGE_TYPE_GROUP_IDS,
  PACKAGE_TYPE_GROUP_LABELS,
  resolveForwardSchema,
  resolveTenorSchema,
} from '@/lib/usd-swaps-tape-v2/volumeGridBuckets'

// ---- Types ------------------------------------------------------------------

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

// ---- Mutable row used only inside the editor --------------------------------

interface BucketRow {
  id: string
  label: string
  lo: string  // text input; empty = null
  hi: string
}

function bucketDefToRow(b: BucketDef): BucketRow {
  return {
    id: b.id,
    label: b.label,
    lo: b.lo == null ? '' : String(b.lo),
    hi: b.hi == null ? '' : String(b.hi),
  }
}

function rowToBucketDef(r: BucketRow): BucketDef {
  const lo = r.lo.trim() === '' ? null : Number(r.lo)
  const hi = r.hi.trim() === '' ? null : Number(r.hi)
  const id = r.id || r.label.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/_+$/,'')
  return { id, label: r.label, lo, hi }
}

function emptyRow(): BucketRow {
  return { id: '', label: '', lo: '', hi: '' }
}

// ---- Presets ----------------------------------------------------------------

type PresetId = 'default' | 'legacy'
const PRESET_OPTIONS: ReadonlyArray<{ id: PresetId; label: string }> = [
  { id: 'default', label: 'Default' },
  { id: 'legacy', label: 'Legacy' },
]

function loadPreset(id: PresetId): { tenor: BucketRow[]; forward: BucketRow[] } {
  const fwd = resolveForwardSchema(id)
  const tnr = resolveTenorSchema(id)
  return {
    forward: fwd.buckets.map(bucketDefToRow),
    tenor: tnr.buckets.map(bucketDefToRow),
  }
}

// ---- Validation -------------------------------------------------------------

interface ValidationResult {
  valid: boolean
  errors: string[]
}

function validate(
  name: string,
  tenorRows: BucketRow[],
  forwardRows: BucketRow[],
): ValidationResult {
  const errors: string[] = []
  if (!name.trim()) errors.push('Name is required.')
  if (tenorRows.length === 0) errors.push('At least one tenor bucket is required.')
  if (forwardRows.length === 0) errors.push('At least one forward bucket is required.')

  const checkBounds = (rows: BucketRow[], axis: string) => {
    for (const r of rows) {
      if (!r.label.trim()) { errors.push(`${axis}: every bucket needs a label.`); break }
      const lo = r.lo.trim() === '' ? null : Number(r.lo)
      const hi = r.hi.trim() === '' ? null : Number(r.hi)
      if (lo != null && isNaN(lo)) { errors.push(`${axis} "${r.label}": Lo is not a number.`); continue }
      if (hi != null && isNaN(hi)) { errors.push(`${axis} "${r.label}": Hi is not a number.`); continue }
      if (lo != null && hi != null && lo >= hi) {
        errors.push(`${axis} "${r.label}": Lo must be less than Hi.`)
      }
    }
  }
  checkBounds(tenorRows, 'Tenor')
  checkBounds(forwardRows, 'Forward')
  return { valid: errors.length === 0, errors }
}

// ---- Component --------------------------------------------------------------

export function CustomSchemaBuilderModal({
  open,
  onClose,
  onApply,
  initialSchema,
}: CustomSchemaBuilderModalProps): JSX.Element {
  const [name, setName] = useState('')
  const [tenorRows, setTenorRows] = useState<BucketRow[]>([])
  const [forwardRows, setForwardRows] = useState<BucketRow[]>([])
  const [packageType, setPackageType] = useState<PackageTypeGroupId>('all')
  const [errors, setErrors] = useState<string[]>([])

  // Reset form state whenever the modal opens or initialSchema changes
  useEffect(() => {
    if (!open) return
    if (initialSchema) {
      setName(initialSchema.name)
      setTenorRows(initialSchema.tenorBuckets.map(bucketDefToRow))
      setForwardRows(initialSchema.forwardBuckets.map(bucketDefToRow))
      setPackageType(initialSchema.packageType)
    } else {
      setName('')
      setTenorRows([emptyRow()])
      setForwardRows([emptyRow()])
      setPackageType('all')
    }
    setErrors([])
  }, [open, initialSchema])

  const handleLoadPreset = useCallback((presetId: PresetId) => {
    const preset = loadPreset(presetId)
    setTenorRows(preset.tenor)
    setForwardRows(preset.forward)
  }, [])

  const handleApply = useCallback(() => {
    const result = validate(name, tenorRows, forwardRows)
    if (!result.valid) { setErrors(result.errors); return }
    setErrors([])
    onApply({
      name: name.trim(),
      tenorBuckets: tenorRows.map(rowToBucketDef),
      forwardBuckets: forwardRows.map(rowToBucketDef),
      packageType,
    })
  }, [name, tenorRows, forwardRows, packageType, onApply])

  return (
    <Dialog
      header="Custom Schema Builder"
      visible={open}
      onHide={onClose}
      style={{ width: '70vw', maxWidth: 900 }}
      modal
    >
      <div className="flex flex-col gap-4 text-slate-200">
        {/* ── Name + Preset row ──────────────────────────────── */}
        <div className="flex flex-wrap items-end gap-3">
          <label className="flex flex-col gap-1">
            <span className="font-mono text-[10px] uppercase tracking-wider text-slate-400">Name</span>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="My Schema"
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
          <label className="flex flex-col gap-1">
            <span className="font-mono text-[10px] uppercase tracking-wider text-slate-400">Load Preset</span>
            <select
              value=""
              onChange={(e) => { if (e.target.value) handleLoadPreset(e.target.value as PresetId) }}
              className="rounded border border-slate-700 bg-slate-900 px-2 py-[3px] font-mono text-[10.5px] text-slate-200 hover:bg-slate-800"
            >
              <option value="">-- select --</option>
              {PRESET_OPTIONS.map((p) => (
                <option key={p.id} value={p.id}>{p.label}</option>
              ))}
            </select>
          </label>
        </div>

        {/* ── Forward Axis ───────────────────────────────────── */}
        <BucketEditor
          axis="Forward"
          rows={forwardRows}
          onChange={setForwardRows}
        />

        {/* ── Tenor Axis ─────────────────────────────────────── */}
        <BucketEditor
          axis="Tenor"
          rows={tenorRows}
          onChange={setTenorRows}
        />

        {/* ── Errors ─────────────────────────────────────────── */}
        {errors.length > 0 && (
          <div className="rounded border border-rose-500/30 bg-rose-500/10 px-3 py-2 font-mono text-[10.5px] text-rose-300">
            {errors.map((e, i) => <div key={i}>{e}</div>)}
          </div>
        )}

        {/* ── Actions ────────────────────────────────────────── */}
        <div className="flex items-center justify-end gap-2 pt-1">
          <button
            type="button"
            onClick={onClose}
            className="rounded border border-slate-700 px-3 py-[3px] font-mono text-[10.5px] text-slate-300 hover:bg-slate-800"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleApply}
            className="rounded border border-indigo-500/40 bg-indigo-500/25 px-3 py-[3px] font-mono text-[10.5px] text-indigo-100 hover:bg-indigo-500/35"
          >
            Apply
          </button>
        </div>
      </div>
    </Dialog>
  )
}

// ---- BucketEditor sub-component ---------------------------------------------

function BucketEditor({
  axis,
  rows,
  onChange,
}: {
  axis: string
  rows: BucketRow[]
  onChange: (rows: BucketRow[]) => void
}): JSX.Element {
  const updateRow = (idx: number, field: keyof BucketRow, value: string) => {
    const next = rows.map((r, i) => (i === idx ? { ...r, [field]: value } : r))
    // Auto-derive id from label when editing label
    if (field === 'label') {
      next[idx] = { ...next[idx], id: value.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/_+$/, '') }
    }
    onChange(next)
  }
  const removeRow = (idx: number) => onChange(rows.filter((_, i) => i !== idx))
  const addRow = () => onChange([...rows, emptyRow()])
  const moveRow = (idx: number, dir: -1 | 1) => {
    const target = idx + dir
    if (target < 0 || target >= rows.length) return
    const next = [...rows]
    ;[next[idx], next[target]] = [next[target], next[idx]]
    onChange(next)
  }

  return (
    <div>
      <div className="mb-1 font-mono text-[10px] uppercase tracking-wider text-slate-400">
        {axis} Axis
      </div>
      <div className="rounded border border-slate-800 bg-slate-950/40">
        {/* Header */}
        <div className="grid grid-cols-[1fr_2fr_1fr_1fr_auto] gap-1 border-b border-slate-800 px-2 py-1 font-mono text-[9px] uppercase tracking-wider text-slate-500">
          <span>Order</span>
          <span>Label</span>
          <span>Lo (years)</span>
          <span>Hi (years)</span>
          <span> </span>
        </div>
        {rows.map((row, idx) => (
          <div
            key={idx}
            className="grid grid-cols-[1fr_2fr_1fr_1fr_auto] items-center gap-1 border-b border-slate-800/50 px-2 py-[2px]"
          >
            <div className="flex items-center gap-1">
              <button
                type="button"
                disabled={idx === 0}
                onClick={() => moveRow(idx, -1)}
                className="font-mono text-[10px] text-slate-500 hover:text-slate-200 disabled:opacity-25"
                title="Move up"
              >
                ^
              </button>
              <button
                type="button"
                disabled={idx === rows.length - 1}
                onClick={() => moveRow(idx, 1)}
                className="font-mono text-[10px] text-slate-500 hover:text-slate-200 disabled:opacity-25"
                title="Move down"
              >
                v
              </button>
              <span className="font-mono text-[9px] text-slate-600">{idx + 1}</span>
            </div>
            <input
              type="text"
              value={row.label}
              onChange={(e) => updateRow(idx, 'label', e.target.value)}
              placeholder="e.g. 2Y-5Y"
              className="w-full rounded border border-slate-700 bg-slate-900 px-1.5 py-[2px] font-mono text-[10.5px] text-slate-200 placeholder:text-slate-600"
            />
            <input
              type="text"
              value={row.lo}
              onChange={(e) => updateRow(idx, 'lo', e.target.value)}
              placeholder="null"
              className="w-full rounded border border-slate-700 bg-slate-900 px-1.5 py-[2px] font-mono text-[10.5px] text-slate-200 placeholder:text-slate-600"
            />
            <input
              type="text"
              value={row.hi}
              onChange={(e) => updateRow(idx, 'hi', e.target.value)}
              placeholder="null"
              className="w-full rounded border border-slate-700 bg-slate-900 px-1.5 py-[2px] font-mono text-[10.5px] text-slate-200 placeholder:text-slate-600"
            />
            <button
              type="button"
              onClick={() => removeRow(idx)}
              className="px-1 font-mono text-[10.5px] text-rose-400 hover:text-rose-200"
              title="Remove bucket"
            >
              x
            </button>
          </div>
        ))}
        <div className="px-2 py-1">
          <button
            type="button"
            onClick={addRow}
            className="rounded border border-slate-700 px-2 py-[1px] font-mono text-[10.5px] text-slate-400 hover:bg-slate-800 hover:text-slate-200"
          >
            + Add Bucket
          </button>
        </div>
      </div>
    </div>
  )
}
