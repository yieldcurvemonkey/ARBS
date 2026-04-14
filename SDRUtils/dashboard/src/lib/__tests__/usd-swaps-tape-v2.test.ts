import { describe, expect, it } from '@jest/globals'
import {
  DISPLAY_VIEW,
  PACKAGES_TABLE,
  LEGS_TABLE,
} from '../usd-swaps-tape-v2'

describe('usd-swaps-tape-v2 constants', () => {
  it('exposes the tape v1 display view name', () => {
    expect(DISPLAY_VIEW).toBe('arbs_usd_swap_tape_display_v1')
  })

  it('exposes the backing table names', () => {
    expect(PACKAGES_TABLE).toBe('arbs_usd_swap_tape_packages_v1')
    expect(LEGS_TABLE).toBe('arbs_usd_swap_tape_legs_v1')
  })
})
