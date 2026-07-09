// ABOUTME: Edit / soft-delete a single trader note (author-only, no password).
export const dynamic = 'force-dynamic'
import { NextResponse } from 'next/server'
import { query } from '@/lib/db'
import { NOTES_TABLE, normalizeAuthor, normalizeNoteBody } from '@/lib/tape-notes'

type NotePatchPayload = { body?: unknown; author?: unknown }
type NoteDeletePayload = { author?: unknown }

async function loadNote(noteId: string) {
  const result = await query(
    `SELECT note_id, author, is_active FROM ${NOTES_TABLE} WHERE note_id = $1`,
    [noteId],
  )
  return result.rows[0] ?? null
}

export async function PATCH(
  request: Request,
  context: { params: Promise<{ noteId: string }> },
) {
  const { noteId } = await context.params
  let payload: NotePatchPayload
  try {
    payload = (await request.json()) as NotePatchPayload
  } catch {
    return NextResponse.json({ error: 'Invalid JSON payload' }, { status: 400 })
  }
  const author = normalizeAuthor(payload.author)
  if (!author) {
    return NextResponse.json({ error: 'author is required.' }, { status: 400 })
  }
  const body = normalizeNoteBody(payload.body)
  if (!body) {
    return NextResponse.json({ error: 'body is required.' }, { status: 400 })
  }
  try {
    const note = await loadNote(noteId)
    if (!note) {
      return NextResponse.json({ error: 'Note not found.' }, { status: 404 })
    }
    if (note.author !== author) {
      return NextResponse.json(
        { error: 'Only the author can edit this note.' },
        { status: 403 },
      )
    }
    await query(
      `UPDATE ${NOTES_TABLE}
       SET body = $1, updated_at = NOW()
       WHERE note_id = $2`,
      [body, noteId],
    )
    return NextResponse.json({ success: true })
  } catch (error: any) {
    console.error('tape note PATCH error', error)
    return NextResponse.json(
      { error: error?.message || 'Failed to update note' },
      { status: 500 },
    )
  }
}

export async function DELETE(
  request: Request,
  context: { params: Promise<{ noteId: string }> },
) {
  const { noteId } = await context.params
  let payload: NoteDeletePayload
  try {
    payload = (await request.json()) as NoteDeletePayload
  } catch {
    return NextResponse.json({ error: 'Invalid JSON payload' }, { status: 400 })
  }
  const author = normalizeAuthor(payload.author)
  if (!author) {
    return NextResponse.json({ error: 'author is required.' }, { status: 400 })
  }
  try {
    const note = await loadNote(noteId)
    if (!note) {
      return NextResponse.json({ error: 'Note not found.' }, { status: 404 })
    }
    if (note.author !== author) {
      return NextResponse.json(
        { error: 'Only the author can delete this note.' },
        { status: 403 },
      )
    }
    await query(
      `UPDATE ${NOTES_TABLE}
       SET is_active = FALSE, updated_at = NOW()
       WHERE note_id = $1`,
      [noteId],
    )
    return NextResponse.json({ success: true })
  } catch (error: any) {
    console.error('tape note DELETE error', error)
    return NextResponse.json(
      { error: error?.message || 'Failed to delete note' },
      { status: 500 },
    )
  }
}
