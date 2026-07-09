'use client'
// ABOUTME: Inline commit popover for a structural override. override_type
// is fixed by the triggering action; collects reason/tags/user/password,
// runs validate_only then the real create via overrideApi. Errors inline
// (no toast lib). Password is a controlled prop persisted in the orchestrator.
import { useCallback, useState, type JSX } from 'react'
import type { OverrideType, OverrideValidationItem } from '../../types/override.types'
import {
  createOverride,
  validateOverride,
  type CreateOverrideBody,
  type CreateOverrideResult,
} from '../../api/overrideApi'

export interface OverrideCommitPopoverProps {
  overrideType: OverrideType
  tradeIds: string[]
  /** Source package for SPLIT/DETACH (informational); undefined for GROUP. */
  manualPackageId?: string | null
  user: string
  /** Optional: if provided, the user field becomes editable. */
  onUserChange?: (next: string) => void
  password: string
  onPasswordChange: (next: string) => void
  onSuccess: (result: CreateOverrideResult) => void
  onCancel: () => void
}

function splitTags(raw: string): string[] {
  return raw
    .split(',')
    .map((t) => t.trim())
    .filter((t) => t.length > 0)
}

export function OverrideCommitPopover({
  overrideType,
  tradeIds,
  manualPackageId,
  user,
  onUserChange,
  password,
  onPasswordChange,
  onSuccess,
  onCancel,
}: OverrideCommitPopoverProps): JSX.Element {
  const [reason, setReason] = useState('')
  const [tags, setTags] = useState('')
  const [validation, setValidation] = useState<OverrideValidationItem[]>([])
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const buildBody = useCallback(
    (validateOnly: boolean): CreateOverrideBody => ({
      override_type: overrideType,
      trade_ids: tradeIds,
      manual_package_id: manualPackageId ?? undefined,
      reason: reason.trim() || undefined,
      tags: splitTags(tags),
      user,
      admin_password: password,
      validate_only: validateOnly ? true : undefined,
    }),
    [overrideType, tradeIds, manualPackageId, reason, tags, user, password],
  )

  const hasErrors = validation.some((v) => v.level === 'error')

  const handleValidate = useCallback(async () => {
    setBusy(true)
    setError(null)
    try {
      const res = await validateOverride(buildBody(true))
      setValidation(res.validation)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }, [buildBody])

  const handleCommit = useCallback(async () => {
    setBusy(true)
    setError(null)
    try {
      const res = await createOverride(buildBody(false))
      onSuccess(res)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }, [buildBody, onSuccess])

  return (
    <div className="absolute right-0 top-full z-50 mt-1 w-72 rounded border border-slate-700 bg-slate-900 p-3 shadow-xl">
      <div className="mb-2 flex items-center justify-between">
        <span className="font-mono text-[10px] uppercase tracking-wider text-slate-400">
          {overrideType} · {tradeIds.length} trades
        </span>
        <button
          type="button"
          aria-label="Cancel"
          onClick={onCancel}
          className="font-mono text-[10px] text-slate-400 hover:text-slate-200"
        >
          ✕
        </button>
      </div>

      <label className="mb-1 block font-mono text-[10px] text-slate-400" htmlFor="ovr-reason">
        Reason
      </label>
      <input
        id="ovr-reason"
        type="text"
        aria-label="Reason"
        value={reason}
        onChange={(e) => setReason(e.target.value)}
        className="mb-2 w-full rounded border border-slate-700 bg-slate-800 px-2 py-1 font-mono text-[11px] text-slate-100"
      />

      <label className="mb-1 block font-mono text-[10px] text-slate-400" htmlFor="ovr-tags">
        Tags (comma-separated)
      </label>
      <input
        id="ovr-tags"
        type="text"
        aria-label="Tags"
        value={tags}
        onChange={(e) => setTags(e.target.value)}
        className="mb-2 w-full rounded border border-slate-700 bg-slate-800 px-2 py-1 font-mono text-[11px] text-slate-100"
      />

      <label className="mb-1 block font-mono text-[10px] text-slate-400" htmlFor="ovr-user">
        User
      </label>
      <input
        id="ovr-user"
        type="text"
        aria-label="User"
        value={user}
        readOnly={!onUserChange}
        onChange={(e) => onUserChange?.(e.target.value)}
        className="mb-2 w-full rounded border border-slate-700 bg-slate-800 px-2 py-1 font-mono text-[11px] text-slate-100"
      />

      <label className="mb-1 block font-mono text-[10px] text-slate-400" htmlFor="ovr-pw">
        Override password
      </label>
      <input
        id="ovr-pw"
        type="password"
        aria-label="Override password"
        value={password}
        onChange={(e) => onPasswordChange(e.target.value)}
        className="mb-2 w-full rounded border border-slate-700 bg-slate-800 px-2 py-1 font-mono text-[11px] text-slate-100"
      />

      {validation.length > 0 && (
        <ul className="mb-2 space-y-0.5">
          {validation.map((v, i) => (
            <li
              key={`${v.code}-${i}`}
              className={`font-mono text-[10px] ${
                v.level === 'error'
                  ? 'text-rose-300'
                  : v.level === 'warning'
                    ? 'text-amber-300'
                    : 'text-slate-400'
              }`}
            >
              {v.message}
            </li>
          ))}
        </ul>
      )}

      {error && (
        <p role="alert" className="mb-2 font-mono text-[10px] text-rose-300">
          {error}
        </p>
      )}

      <div className="flex items-center justify-end gap-2">
        <button
          type="button"
          onClick={handleValidate}
          disabled={busy}
          className="rounded border border-slate-700 px-2.5 py-1 font-mono text-[10.5px] text-slate-200 hover:bg-slate-800 disabled:opacity-50"
        >
          Validate
        </button>
        <button
          type="button"
          onClick={handleCommit}
          disabled={busy || hasErrors || !password}
          className="rounded border border-indigo-500/40 bg-indigo-500/20 px-2.5 py-1 font-mono text-[10.5px] text-indigo-100 hover:bg-indigo-500/30 disabled:opacity-50"
        >
          Commit
        </button>
      </div>
    </div>
  )
}
