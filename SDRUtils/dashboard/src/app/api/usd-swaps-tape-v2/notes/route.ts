// ABOUTME: List + create trader notes for tape trades/packages (no password).
export const dynamic = 'force-dynamic'
import { NextResponse } from 'next/server'
import { query } from '@/lib/db'
import {
  NOTES_TABLE,
  isValidNoteTargetType,
  normalizeAuthor,
  normalizeNoteBody,
} from '@/lib/tape-notes'

type NotePostPayload = {
  target_type?: unknown
  target_id?: unknown
  author?: unknown
  body?: unknown
}

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url)
  const targetType = searchParams.get('target_type')
  const targetId = searchParams.get('target_id')
  if (!isValidNoteTargetType(targetType) || !targetId) {
    return NextResponse.json(
      { error: 'target_type (TRADE|PACKAGE) and target_id are required.' },
      { status: 400 },
    )
  }
  try {
    const result = await query(
      `SELECT note_id, target_type, target_id, author, body, created_at, updated_at, is_active
       FROM ${NOTES_TABLE}
       WHERE target_type = $1 AND target_id = $2 AND is_active = TRUE
       ORDER BY created_at DESC`,
      [targetType, targetId],
    )
    return NextResponse.json({ rows: result.rows })
  } catch (error: any) {
    console.error('tape notes GET error', error)
    return NextResponse.json(
      { error: error?.message || 'Failed to fetch notes' },
      { status: 500 },
    )
  }
}

export async function POST(request: Request) {
  let payload: NotePostPayload
  try {
    payload = (await request.json()) as NotePostPayload
  } catch {
    return NextResponse.json({ error: 'Invalid JSON payload' }, { status: 400 })
  }
  if (!isValidNoteTargetType(payload.target_type)) {
    return NextResponse.json(
      { error: "target_type must be 'TRADE' or 'PACKAGE'." },
      { status: 400 },
    )
  }
  const targetId = normalizeAuthor(payload.target_id)
  const author = normalizeAuthor(payload.author)
  const body = normalizeNoteBody(payload.body)
  if (!targetId) {
    return NextResponse.json({ error: 'target_id is required.' }, { status: 400 })
  }
  if (!author) {
    return NextResponse.json({ error: 'author is required.' }, { status: 400 })
  }
  if (!body) {
    return NextResponse.json({ error: 'body is required.' }, { status: 400 })
  }
  try {
    const result = await query(
      `INSERT INTO ${NOTES_TABLE} (target_type, target_id, author, body)
       VALUES ($1, $2, $3, $4)
       RETURNING note_id`,
      [payload.target_type, targetId, author, body],
    )
    return NextResponse.json({ success: true, note_id: result.rows[0].note_id })
  } catch (error: any) {
    console.error('tape notes POST error', error)
    return NextResponse.json(
      { error: error?.message || 'Failed to create note' },
      { status: 500 },
    )
  }
}
