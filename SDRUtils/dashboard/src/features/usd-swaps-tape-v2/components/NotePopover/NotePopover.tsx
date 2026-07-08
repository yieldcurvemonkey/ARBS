'use client'
// ABOUTME: Read/add/edit trader notes for a trade or package target. Author-only
// (no password). Lazily fetches note bodies via noteApi on open; the orchestrator
// owns the open `target` and refetches the tape on save so has_notes updates.
import { useEffect, useState, type JSX } from 'react'
import { X } from 'lucide-react'
import type { NoteTarget, TapeNote } from '../../types/note.types'
import { createNote, deactivateNote, fetchNotes, updateNote } from '../../api/noteApi'

export interface NotePopoverProps {
  target: NoteTarget | null
  author: string
  onAuthorChange: (next: string) => void
  onClose: () => void
  onSaved?: () => void
}

// fetchNotes' real contract resolves `{ rows: TapeNote[] }`, but tests (and
// possibly future callers) may resolve a bare array directly — normalize
// either shape rather than assuming one.
function unwrapNotes(res: TapeNote[] | { rows: TapeNote[] }): TapeNote[] {
  return Array.isArray(res) ? res : res.rows
}

export function NotePopover({
  target,
  author,
  onAuthorChange,
  onClose,
  onSaved,
}: NotePopoverProps): JSX.Element | null {
  const [notes, setNotes] = useState<TapeNote[]>([])
  const [body, setBody] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const key = target ? `${target.target_type}:${target.target_id}` : null
  useEffect(() => {
    if (!target) return
    let live = true
    setNotes([])
    setError(null)
    fetchNotes(target.target_type, target.target_id)
      .then((res) => {
        if (live) setNotes(unwrapNotes(res))
      })
      .catch((e) => {
        if (live) setError(String((e as Error)?.message ?? e))
      })
    return () => {
      live = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key])

  if (!target) return null

  const reload = () =>
    fetchNotes(target.target_type, target.target_id)
      .then((res) => setNotes(unwrapNotes(res)))
      .catch((e) => setError(String((e as Error)?.message ?? e)))

  const canSave = author.trim().length > 0 && body.trim().length > 0 && !busy

  const onSave = async () => {
    if (!canSave) return
    setBusy(true)
    setError(null)
    try {
      await createNote({
        target_type: target.target_type,
        target_id: target.target_id,
        author: author.trim(),
        body: body.trim(),
      })
      setBody('')
      await reload()
      onSaved?.()
    } catch (e) {
      setError(String((e as Error)?.message ?? e))
    } finally {
      setBusy(false)
    }
  }

  const onDelete = async (noteId: string) => {
    setBusy(true)
    try {
      await deactivateNote(noteId, { author: author.trim() })
      await reload()
      onSaved?.()
    } catch (e) {
      setError(String((e as Error)?.message ?? e))
    } finally {
      setBusy(false)
    }
  }

  const onEdit = async (noteId: string, next: string) => {
    setBusy(true)
    try {
      await updateNote(noteId, { body: next, author: author.trim() })
      await reload()
      onSaved?.()
    } catch (e) {
      setError(String((e as Error)?.message ?? e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/40 p-8"
      onClick={onClose}
      data-testid="note-popover"
    >
      <div
        className="w-full max-w-md rounded-xl border border-slate-700 bg-slate-950 p-4 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-2 flex items-center justify-between">
          <div className="font-mono text-[11px] uppercase tracking-wide text-slate-400">
            Notes · {target.target_type} {target.target_id}
          </div>
          <button
            type="button"
            aria-label="close notes"
            onClick={onClose}
            className="text-slate-400 hover:text-slate-200"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <ul className="mb-3 max-h-56 space-y-2 overflow-y-auto">
          {notes.length === 0 ? (
            <li className="text-[11px] text-slate-500">No notes yet.</li>
          ) : (
            notes.map((n) => (
              <li key={n.note_id} className="rounded border border-slate-800 bg-slate-900/60 p-2 text-[11px]">
                <div className="mb-1 flex items-center justify-between text-[10px] text-slate-500">
                  <span>{n.author}</span>
                  <span>{new Date(n.created_at).toISOString().slice(0, 16).replace('T', ' ')}</span>
                </div>
                <NoteRow note={n} onEdit={onEdit} onDelete={onDelete} disabled={busy} />
              </li>
            ))
          )}
        </ul>

        <label className="mb-1 block font-mono text-[10px] uppercase tracking-wide text-slate-500">Author</label>
        <input
          aria-label="note author"
          value={author}
          onChange={(e) => onAuthorChange(e.target.value)}
          className="mb-2 w-full rounded border border-slate-700 bg-slate-950 px-2 py-1 font-mono text-[11px] text-slate-100"
          placeholder="your username"
        />
        <label className="mb-1 block font-mono text-[10px] uppercase tracking-wide text-slate-500">New note</label>
        <textarea
          aria-label="note body"
          value={body}
          onChange={(e) => setBody(e.target.value)}
          rows={3}
          className="mb-2 w-full rounded border border-slate-700 bg-slate-950 px-2 py-1 font-mono text-[11px] text-slate-100"
          placeholder="Add a trader note…"
        />
        {error ? <div className="mb-2 text-[11px] text-rose-300">{error}</div> : null}
        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded border border-slate-700 px-3 py-1 text-[11px] text-slate-300 hover:bg-slate-800"
          >
            Close
          </button>
          <button
            type="button"
            onClick={onSave}
            disabled={!canSave}
            className="rounded bg-sky-700 px-3 py-1 text-[11px] font-semibold text-white hover:bg-sky-600 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {busy ? 'Saving…' : 'Save note'}
          </button>
        </div>
      </div>
    </div>
  )
}

function NoteRow({
  note,
  onEdit,
  onDelete,
  disabled,
}: {
  note: TapeNote
  onEdit: (id: string, next: string) => void
  onDelete: (id: string) => void
  disabled: boolean
}): JSX.Element {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(note.body)
  if (editing) {
    return (
      <div>
        <textarea
          aria-label={`edit note ${note.note_id}`}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          rows={2}
          className="mb-1 w-full rounded border border-slate-700 bg-slate-950 px-2 py-1 text-[11px] text-slate-100"
        />
        <div className="flex justify-end gap-2">
          <button type="button" className="text-[10px] text-slate-400" onClick={() => setEditing(false)}>
            Cancel
          </button>
          <button
            type="button"
            className="text-[10px] text-sky-300 disabled:opacity-50"
            disabled={disabled || !draft.trim()}
            onClick={() => {
              onEdit(note.note_id, draft.trim())
              setEditing(false)
            }}
          >
            Save
          </button>
        </div>
      </div>
    )
  }
  return (
    <div className="flex items-start justify-between gap-2">
      <span className="text-slate-200">{note.body}</span>
      <span className="flex shrink-0 gap-2">
        <button type="button" className="text-[10px] text-slate-400 hover:text-slate-200" onClick={() => setEditing(true)}>
          edit
        </button>
        <button
          type="button"
          className="text-[10px] text-rose-400 hover:text-rose-200"
          disabled={disabled}
          onClick={() => onDelete(note.note_id)}
        >
          delete
        </button>
      </span>
    </div>
  )
}
