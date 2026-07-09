// ABOUTME: Tape-local helpers for trader notes on trades/packages.
export const NOTES_TABLE = 'arbs_usd_swap_tape_notes_v2'

export type NoteTargetType = 'TRADE' | 'PACKAGE'
const NOTE_TARGET_TYPES: NoteTargetType[] = ['TRADE', 'PACKAGE']

export function isValidNoteTargetType(value: unknown): value is NoteTargetType {
  return typeof value === 'string' && (NOTE_TARGET_TYPES as string[]).includes(value)
}

export function normalizeAuthor(value: unknown): string | null {
  if (typeof value !== 'string') return null
  const trimmed = value.trim()
  return trimmed ? trimmed : null
}

export function normalizeNoteBody(value: unknown): string | null {
  if (typeof value !== 'string') return null
  const trimmed = value.trim()
  return trimmed ? trimmed : null
}
