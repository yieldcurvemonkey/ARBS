export type NoteTargetType = 'TRADE' | 'PACKAGE'

export interface NoteTarget {
  target_type: NoteTargetType
  target_id: string
}

export interface TapeNote {
  note_id: string
  target_type: NoteTargetType
  target_id: string
  author: string
  body: string
  created_at: string
  updated_at: string | null
  is_active: boolean
}
