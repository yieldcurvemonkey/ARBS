'use client'
// ABOUTME: Dialog for creating manual package links from selected rows.
import type { JSX } from 'react'
import { useState } from 'react'
import { Dialog } from 'primereact/dialog'
import { useManualLinks } from '../../hooks/useManualLinks'
import { useSavedUser } from '../../hooks/useSavedUser'
import type { UsdSwapTapeRow } from '../../types'

export interface ManualLinksDialogProps {
  open: boolean
  onClose: () => void
  selected: UsdSwapTapeRow[]
  onSuccess?: () => void
}

export function ManualLinksDialog(props: ManualLinksDialogProps): JSX.Element {
  const [user, setUser] = useSavedUser()
  const [manualId, setManualId] = useState('')
  const [reason, setReason] = useState('')
  const [comment, setComment] = useState('')
  const [tags, setTags] = useState('')
  const { createLink, creating, error } = useManualLinks()

  const tradeIds = props.selected.flatMap((row) =>
    (row.legs_json ?? []).map((l) => String(l.trade_id)).filter(Boolean),
  )

  // A manual link must span at least 2 distinct packages — linking
  // legs within a single package to itself is meaningless. The
  // earlier guard only checked tradeIds.length, which let a 3-leg
  // package self-link.
  const selectedPackageCount = props.selected.length
  const canSubmit =
    !!user && !!manualId.trim() && selectedPackageCount >= 2 && tradeIds.length >= 2

  async function onSubmit() {
    if (!canSubmit) return
    const result = await createLink({
      manual_package_id: manualId,
      package_type: 'MANUAL',
      linked_trade_ids: tradeIds,
      created_by: user,
      user_comment: comment || undefined,
      link_reason: reason || undefined,
      tags: tags ? tags.split(',').map((s) => s.trim()).filter(Boolean) : undefined,
    })
    if (result) {
      props.onSuccess?.()
      props.onClose()
    }
  }

  const disabled = !canSubmit || creating

  return (
    <Dialog
      visible={props.open}
      onHide={props.onClose}
      header="Link selected trades"
      style={{ width: 480 }}
      modal
    >
      <div className="flex flex-col gap-3 text-sm">
        <label className="flex flex-col gap-1">
          <span className="text-slate-400">Your name</span>
          <input
            className="bg-slate-900 border border-slate-800 rounded px-2 py-1"
            value={user}
            onChange={(e) => setUser(e.target.value)}
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-slate-400">Manual package ID</span>
          <input
            className="bg-slate-900 border border-slate-800 rounded px-2 py-1"
            value={manualId}
            onChange={(e) => setManualId(e.target.value)}
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-slate-400">Reason</span>
          <input
            className="bg-slate-900 border border-slate-800 rounded px-2 py-1"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-slate-400">Comment</span>
          <textarea
            className="bg-slate-900 border border-slate-800 rounded px-2 py-1 h-20"
            value={comment}
            onChange={(e) => setComment(e.target.value)}
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-slate-400">Tags (comma separated)</span>
          <input
            className="bg-slate-900 border border-slate-800 rounded px-2 py-1"
            value={tags}
            onChange={(e) => setTags(e.target.value)}
          />
        </label>
        <div className="text-xs text-slate-400">
          {tradeIds.length} trade-ids selected.
        </div>
        {error ? <p className="text-red-300 text-sm">{error}</p> : null}
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
            onClick={onSubmit}
            disabled={disabled}
            className="text-xs px-3 py-1.5 rounded bg-emerald-800/80 text-emerald-50 disabled:opacity-50"
          >
            {creating ? 'Linking…' : 'Create link'}
          </button>
        </div>
      </div>
    </Dialog>
  )
}
