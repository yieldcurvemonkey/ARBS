// ABOUTME: Tape-local REST client for trader notes (TRADE/PACKAGE). No
// password gate (author-only). Mirrors overrideApi's error parsing.
import { TAPE_V2_API_BASE } from '../constants'
import type { NoteTargetType, TapeNote } from '../types/note.types'

const NOTES_BASE = `${TAPE_V2_API_BASE}/notes`

export interface CreateNoteBody {
  target_type: NoteTargetType
  target_id: string
  author: string
  body: string
}

export interface UpdateNoteBody {
  body?: string
  author: string
}

export interface DeactivateNoteBody {
  author: string
}

async function parseError(res: Response): Promise<Error> {
  try {
    const payload = await res.json()
    if (payload && typeof payload === 'object' && 'error' in payload && payload.error) {
      return new Error(String((payload as { error: unknown }).error))
    }
  } catch {
    // ignore
  }
  return new Error(`Request failed with status ${res.status}`)
}

export async function fetchNotes(
  targetType: NoteTargetType,
  targetId: string,
): Promise<{ rows: TapeNote[] }> {
  const qs = new URLSearchParams({ target_type: targetType, target_id: targetId }).toString()
  const res = await fetch(`${NOTES_BASE}?${qs}`)
  if (!res.ok) throw await parseError(res)
  const payload = await res.json()
  return { rows: (payload?.rows as TapeNote[]) ?? [] }
}

export async function createNote(body: CreateNoteBody): Promise<{ success: true; note_id: string }> {
  const res = await fetch(NOTES_BASE, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw await parseError(res)
  return (await res.json()) as { success: true; note_id: string }
}

export async function updateNote(
  noteId: string,
  body: UpdateNoteBody,
): Promise<{ success: true }> {
  const res = await fetch(`${NOTES_BASE}/${encodeURIComponent(noteId)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw await parseError(res)
  return (await res.json()) as { success: true }
}

export async function deactivateNote(
  noteId: string,
  body: DeactivateNoteBody,
): Promise<{ success: true }> {
  const res = await fetch(`${NOTES_BASE}/${encodeURIComponent(noteId)}`, {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw await parseError(res)
  return (await res.json()) as { success: true }
}
