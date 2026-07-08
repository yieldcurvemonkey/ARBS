import { describe, expect, it } from '@jest/globals'
import type { OverrideType, TapeOverride, OverrideValidationItem } from '../override.types'
import type { NoteTargetType, TapeNote } from '../note.types'
import type { UsdSwapTapeRow } from '../trade.types'

describe('override + note types', () => {
  it('TapeOverride literal is assignable', () => {
    const o: TapeOverride = {
      override_id: 'o1',
      override_type: 'GROUP',
      manual_package_id: 'SMO-20260708-ABCD1234',
      trade_ids: ['t1', 't2'],
      created_by: 'chris',
      created_at: '2026-07-08T00:00:00Z',
      updated_at: null,
      is_active: true,
      reason: null,
      tags: null,
      metrics: {},
    }
    const t: OverrideType = 'SPLIT'
    const v: OverrideValidationItem = { level: 'error', code: 'GROUP_MIN', message: 'need >=2' }
    expect(o.override_type).toBe('GROUP')
    expect(t).toBe('SPLIT')
    expect(v.level).toBe('error')
  })

  it('TapeNote literal is assignable', () => {
    const tt: NoteTargetType = 'TRADE'
    const n: TapeNote = {
      note_id: 'n1',
      target_type: tt,
      target_id: 't1',
      author: 'chris',
      body: 'watch this',
      created_at: '2026-07-08T00:00:00Z',
      updated_at: null,
      is_active: true,
    }
    expect(n.target_type).toBe('TRADE')
  })

  it('UsdSwapTapeRow carries the v2 override/notes columns', () => {
    const row = {
      package_id: 'PKG1',
      legs_json: [],
      override_map: { t1: 'o1' },
      override_type: 'GROUP',
      manual_package_id: 'SMO-20260708-ABCD1234',
      has_notes: true,
      notes_count: 2,
    } as unknown as UsdSwapTapeRow
    expect(row.override_map?.t1).toBe('o1')
    expect(row.override_type).toBe('GROUP')
    expect(row.has_notes).toBe(true)
    expect(row.notes_count).toBe(2)
  })
})
