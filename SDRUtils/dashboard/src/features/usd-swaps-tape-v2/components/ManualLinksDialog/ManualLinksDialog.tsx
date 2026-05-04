'use client'
// ABOUTME: Dialog for creating manual package links from selected rows.
// Builds on the shared useManualLinkForm state machine: auto-validates
// on open, surfaces server-side validation items + computed metrics,
// and POSTs the create payload through the shared manualLinkApi. The
// editing / deactivate flow lives in <ManualLinkDetailModal> which is
// mounted at the orchestrator level (UsdSwapsTradeTape).

import type { JSX } from 'react'
import { useEffect, useMemo, useState } from 'react'
import { Dialog } from 'primereact/dialog'
import { TAPE_V2_API_BASE } from '../../constants'
import { useSavedUser } from '../../hooks/useSavedUser'
import type { UsdSwapTapeRow } from '../../types'
import { useManualLinkForm } from '@/lib/manual-links-ui/hooks/useManualLinkForm'
import { ManualLinkValidationList } from '@/lib/manual-links-ui/components/ManualLinkValidationList'
import { ManualLinkMetricsTable } from '@/lib/manual-links-ui/components/ManualLinkMetricsTable'

const V2_LINKS_BASE = `${TAPE_V2_API_BASE}/links`

const PACKAGE_TYPE_OPTIONS = [
  { value: 'MANUAL', label: 'Manual' },
  { value: 'USER_STRADDLE_PAIR', label: 'Straddle Pair' },
  { value: 'USER_VERTICAL_SPREAD', label: 'Vertical Spread' },
  { value: 'USER_TIME_SPREAD', label: 'Time Spread' },
  { value: 'USER_CUSTOM', label: 'Custom' },
]

const LINK_REASON_OPTIONS = [
  { value: '', label: 'Select reason...' },
  { value: 'Vega hedge', label: 'Vega hedge' },
  { value: 'Customer flow', label: 'Customer flow' },
  { value: 'Time spread', label: 'Time spread' },
  { value: 'Skew Trade', label: 'Skew Trade' },
  { value: 'Structure repair', label: 'Structure repair' },
  { value: 'Other', label: 'Other' },
]

export interface ManualLinksDialogProps {
  open: boolean
  onClose: () => void
  selected: UsdSwapTapeRow[]
  onSuccess?: () => void
}

export function ManualLinksDialog(props: ManualLinksDialogProps): JSX.Element {
  const [user, setUser] = useSavedUser()
  const [manualPackageId, setManualPackageId] = useState('')

  const tradeIds = useMemo(
    () =>
      props.selected.flatMap((row) =>
        (row.legs_json ?? []).map((l) => String(l.trade_id)).filter(Boolean),
      ),
    [props.selected],
  )

  const form = useManualLinkForm({
    basePath: V2_LINKS_BASE,
    selectedIds: tradeIds,
    currentUser: user,
    isOpen: props.open,
    initialPackageType: PACKAGE_TYPE_OPTIONS[0]?.value ?? 'MANUAL',
    initialLinkReason: '',
    manualPackageId: manualPackageId || undefined,
  })

  // Sync the local manual_package_id input back into the form's
  // manualPackageId option without retriggering on every keystroke.
  useEffect(() => {
    if (!props.open) {
      setManualPackageId('')
    }
  }, [props.open])

  const selectedPackageCount = props.selected.length
  const hasValidationErrors = form.validation.some((v) => v.status === 'error')
  const canSubmit =
    !!user &&
    !!manualPackageId.trim() &&
    selectedPackageCount >= 2 &&
    tradeIds.length >= 2 &&
    !hasValidationErrors

  async function onSubmit() {
    if (!canSubmit) return
    await form.handleCreate(
      () => {
        props.onSuccess?.()
      },
      () => {
        props.onClose()
      },
    )
  }

  const disabled = !canSubmit || form.submitting

  return (
    <Dialog
      visible={props.open}
      onHide={props.onClose}
      header="Link selected trades"
      style={{ width: 600 }}
      modal
      data-testid="usd-swaps-manual-links-dialog"
    >
      <div className="flex flex-col gap-3 text-sm">
        <label className="flex flex-col gap-1">
          <span className="text-slate-400">Your name</span>
          <input
            className="bg-slate-900 border border-slate-800 rounded px-2 py-1"
            value={user}
            onChange={(e) => setUser(e.target.value)}
            data-testid="usd-swaps-manual-links-user"
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-slate-400">Manual package ID</span>
          <input
            className="bg-slate-900 border border-slate-800 rounded px-2 py-1"
            value={manualPackageId}
            onChange={(e) => setManualPackageId(e.target.value)}
            data-testid="usd-swaps-manual-links-package-id"
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-slate-400">Package type</span>
          <select
            className="bg-slate-900 border border-slate-800 rounded px-2 py-1"
            value={form.packageType}
            onChange={(e) => form.setPackageType(e.target.value)}
          >
            {PACKAGE_TYPE_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-slate-400">Reason</span>
          <select
            className="bg-slate-900 border border-slate-800 rounded px-2 py-1"
            value={form.linkReason}
            onChange={(e) => form.setLinkReason(e.target.value)}
          >
            {LINK_REASON_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-slate-400">Comment</span>
          <textarea
            className="bg-slate-900 border border-slate-800 rounded px-2 py-1 h-20"
            value={form.comment}
            onChange={(e) => form.setComment(e.target.value)}
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-slate-400">Tags</span>
          <div className="flex gap-2">
            <input
              className="flex-1 bg-slate-900 border border-slate-800 rounded px-2 py-1"
              value={form.tagInput}
              onChange={(e) => form.setTagInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault()
                  form.addTag()
                }
              }}
              placeholder="Type a tag and press Enter"
            />
            <button
              type="button"
              onClick={() => form.addTag()}
              className="text-xs px-2 rounded bg-slate-800/70 text-slate-200"
            >
              Add
            </button>
          </div>
          {form.tags.length > 0 && (
            <div className="mt-1 flex flex-wrap gap-2">
              {form.tags.map((tag) => (
                <span
                  key={tag}
                  className="inline-flex items-center gap-1 rounded-full border border-slate-700 bg-slate-900 px-2 py-0.5 text-[10px] uppercase tracking-wide text-slate-200"
                >
                  {tag}
                  <button
                    type="button"
                    onClick={() => form.removeTag(tag)}
                    className="text-slate-400 hover:text-slate-200"
                    aria-label={`Remove ${tag}`}
                  >
                    ×
                  </button>
                </span>
              ))}
            </div>
          )}
        </label>
        <div className="text-xs text-slate-400">
          {tradeIds.length} trade-ids across {selectedPackageCount} packages selected.
        </div>
        {form.validating ? (
          <div className="text-xs text-slate-400">Validating selection…</div>
        ) : null}
        {form.validation.length > 0 ? (
          <div className="rounded border border-slate-800 bg-slate-950/50 p-2">
            <div className="text-[11px] uppercase tracking-wide text-slate-400 mb-1">
              Validation
            </div>
            <ManualLinkValidationList items={form.validation} />
          </div>
        ) : null}
        {form.metrics ? (
          <div className="rounded border border-slate-800 bg-slate-950/50 p-2">
            <div className="text-[11px] uppercase tracking-wide text-slate-400 mb-1">
              Metrics
            </div>
            <ManualLinkMetricsTable metrics={form.metrics} />
          </div>
        ) : null}
        {form.error ? <p className="text-red-300 text-sm" data-testid="usd-swaps-manual-links-error">{form.error}</p> : null}
        <div className="flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={props.onClose}
            className="text-xs px-3 py-1.5 rounded bg-slate-800/70 text-slate-200"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={() => form.validateLink()}
            disabled={form.validating || tradeIds.length < 2}
            className="text-xs px-3 py-1.5 rounded bg-slate-800/70 text-slate-200 disabled:opacity-50"
          >
            {form.validating ? 'Validating…' : 'Re-validate'}
          </button>
          <button
            type="button"
            onClick={onSubmit}
            disabled={disabled}
            className="text-xs px-3 py-1.5 rounded bg-emerald-800/80 text-emerald-50 disabled:opacity-50"
            data-testid="usd-swaps-manual-links-submit"
          >
            {form.submitting ? 'Linking…' : 'Create link'}
          </button>
        </div>
      </div>
    </Dialog>
  )
}
