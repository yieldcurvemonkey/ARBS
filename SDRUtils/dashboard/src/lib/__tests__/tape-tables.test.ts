import {
  MANUAL_LINKS,
  TAPE_DISPLAY,
  TAPE_GENERATION,
  TAPE_LEGS,
  TAPE_PACKAGES,
} from '../tape-tables'

describe('tape table generation seam', () => {
  it('is pinned to v3', () => {
    expect(TAPE_GENERATION).toBe('v3')
  })

  it('derives table names from the generation', () => {
    expect(TAPE_LEGS).toBe('arbs_usd_swap_tape_legs_v3')
    expect(TAPE_PACKAGES).toBe('arbs_usd_swap_tape_packages_v3')
    expect(TAPE_DISPLAY).toBe('arbs_usd_swap_tape_display_v3')
  })

  it('leaves manual links unversioned', () => {
    expect(MANUAL_LINKS).toBe('arbs_usd_swap_manual_links_v2')
  })
})
