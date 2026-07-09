'use client'
// ABOUTME: Minimal management panel for the currently-active structural
// overrides. Lists active overrides (fetchOverrides({is_active:true})),
// exposes a per-row Revert (deactivate) + an audit-history expander, and
// hands the orchestrator a `recreate` body so its Undo can re-POST a reverted
// override (the contract API has no reactivate endpoint). Rendered as a
// fixed-overlay modal so it mounts sanely anywhere in the shell.
import { useCallback, useEffect, useState, type JSX } from 'react'
import { X } from 'lucide-react'
import {
  createOverride,
  deactivateOverride,
  fetchOverrideDetail,
  fetchOverrides,
  type CreateOverrideBody,
  type OverrideHistoryRow,
} from '../../api/overrideApi'
import type { TapeOverride } from '../../types/override.types'

export interface OverridesPanelProps {
  user: string
  adminPassword: string
  onClose: () => void
  onReverted: (overrideId: string, recreate: Parameters<typeof createOverride>[0]) => void
}

function formatTs(value: string | null | undefined): string {
  if (!value) return '—'
  try {
    return new Date(value).toISOString().slice(0, 16).replace('T', ' ')
  } catch {
    return String(value)
  }
}

export function OverridesPanel({
  user,
  adminPassword,
  onClose,
  onReverted,
}: OverridesPanelProps): JSX.Element {
  const [rows, setRows] = useState<TapeOverride[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [expanded, setExpanded] = useState<string | null>(null)
  const [history, setHistory] = useState<OverrideHistoryRow[]>([])
  const [historyLoading, setHistoryLoading] = useState(false)
  // Password used to authorise a revert. Seeds from the shared
  // `adminPassword` prop (persisted by the orchestrator) so a trader who
  // already committed an override this session doesn't re-type it; editable
  // here so the panel is usable standalone.
  const [pw, setPw] = useState(adminPassword)

  useEffect(() => {
    let live = true
    setLoading(true)
    setError(null)
    fetchOverrides({ is_active: true })
      .then((res) => {
        if (live) setRows(res.rows)
      })
      .catch((e) => {
        if (live) setError(String((e as Error)?.message ?? e))
      })
      .finally(() => {
        if (live) setLoading(false)
      })
    return () => {
      live = false
    }
  }, [])

  const toggleHistory = useCallback(
    async (overrideId: string) => {
      if (expanded === overrideId) {
        setExpanded(null)
        setHistory([])
        return
      }
      setExpanded(overrideId)
      setHistory([])
      setHistoryLoading(true)
      try {
        const detail = await fetchOverrideDetail(overrideId)
        setHistory(detail.history ?? [])
      } catch (e) {
        setError(String((e as Error)?.message ?? e))
      } finally {
        setHistoryLoading(false)
      }
    },
    [expanded],
  )

  const revert = useCallback(
    async (o: TapeOverride) => {
      setBusyId(o.override_id)
      setError(null)
      try {
        await deactivateOverride(o.override_id, { user, admin_password: pw })
        // Build a recreate body from the PARENT override so the orchestrator's
        // Undo can re-POST an equivalent override (no reactivate endpoint).
        const recreate: CreateOverrideBody = {
          override_type: o.override_type,
          trade_ids: o.trade_ids,
          manual_package_id: o.manual_package_id ?? undefined,
          user,
          admin_password: pw,
        }
        onReverted(o.override_id, recreate)
        setRows((prev) => prev.filter((r) => r.override_id !== o.override_id))
        if (expanded === o.override_id) {
          setExpanded(null)
          setHistory([])
        }
      } catch (e) {
        setError(String((e as Error)?.message ?? e))
      } finally {
        setBusyId(null)
      }
    },
    [user, pw, expanded, onReverted],
  )

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/40 p-8"
      onClick={onClose}
      data-testid="overrides-panel"
    >
      <div
        className="w-full max-w-2xl rounded-xl border border-slate-700 bg-slate-950 p-4 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-2 flex items-center justify-between">
          <div className="font-mono text-[11px] uppercase tracking-wide text-slate-400">
            Active overrides
          </div>
          <button
            type="button"
            aria-label="close overrides"
            onClick={onClose}
            className="text-slate-400 hover:text-slate-200"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="mb-3 flex items-center gap-2">
          <label className="font-mono text-[10px] uppercase tracking-wide text-slate-500">
            Override password
          </label>
          <input
            type="password"
            aria-label="override password"
            value={pw}
            onChange={(e) => setPw(e.target.value)}
            className="flex-1 rounded border border-slate-700 bg-slate-900 px-2 py-1 font-mono text-[11px] text-slate-100"
            placeholder="required to revert"
          />
        </div>

        {error ? (
          <div role="alert" className="mb-2 font-mono text-[11px] text-rose-300">
            {error}
          </div>
        ) : null}

        {loading ? (
          <div className="py-6 text-center text-[11px] text-slate-500">Loading…</div>
        ) : rows.length === 0 ? (
          <div className="py-6 text-center text-[11px] text-slate-500">
            No active overrides.
          </div>
        ) : (
          <div className="max-h-[60vh] overflow-y-auto">
            <table className="min-w-full font-mono text-[11px]">
              <thead>
                <tr className="text-[10px] uppercase tracking-wide text-slate-500">
                  <th className="px-2 py-1 text-left">Type</th>
                  <th className="px-2 py-1 text-left">Manual pkg</th>
                  <th className="px-2 py-1 text-right">Trades</th>
                  <th className="px-2 py-1 text-left">By</th>
                  <th className="px-2 py-1 text-left">Created</th>
                  <th className="px-2 py-1 text-right">Actions</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((o) => (
                  <tr
                    key={o.override_id}
                    className="border-t border-slate-800/80 text-slate-200"
                    data-testid={`override-row-${o.override_id}`}
                  >
                    <td className="px-2 py-1">{o.override_type}</td>
                    <td className="px-2 py-1 text-slate-400">
                      {o.manual_package_id ?? '—'}
                    </td>
                    <td className="px-2 py-1 text-right">{o.trade_ids.length}</td>
                    <td className="px-2 py-1 text-slate-400">{o.created_by}</td>
                    <td className="px-2 py-1 text-slate-400">{formatTs(o.created_at)}</td>
                    <td className="px-2 py-1">
                      <div className="flex items-center justify-end gap-2">
                        <button
                          type="button"
                          onClick={() => toggleHistory(o.override_id)}
                          className="rounded border border-slate-700 px-1.5 py-0.5 text-[10px] text-slate-300 hover:bg-slate-800"
                          aria-expanded={expanded === o.override_id}
                        >
                          {expanded === o.override_id ? 'Hide' : 'History'}
                        </button>
                        <button
                          type="button"
                          onClick={() => revert(o)}
                          disabled={busyId === o.override_id || !pw}
                          aria-label={`revert override ${o.override_id}`}
                          className="rounded border border-rose-700/50 bg-rose-900/30 px-1.5 py-0.5 text-[10px] text-rose-200 hover:bg-rose-900/50 disabled:cursor-not-allowed disabled:opacity-50"
                        >
                          {busyId === o.override_id ? '…' : 'Revert'}
                        </button>
                      </div>
                      {expanded === o.override_id ? (
                        <div className="mt-1 rounded border border-slate-800 bg-slate-900/60 p-2 text-left">
                          {historyLoading ? (
                            <div className="text-[10px] text-slate-500">Loading history…</div>
                          ) : history.length === 0 ? (
                            <div className="text-[10px] text-slate-500">No history.</div>
                          ) : (
                            <ul className="space-y-0.5">
                              {history.map((h) => (
                                <li key={h.history_id} className="text-[10px] text-slate-400">
                                  <span className="text-slate-300">{h.action}</span> ·{' '}
                                  {h.changed_by} · {formatTs(h.changed_at)}
                                </li>
                              ))}
                            </ul>
                          )}
                        </div>
                      ) : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
