import { tapeTagBadgesFor } from '../RowBadges.helpers'

describe('tapeTagBadgesFor — LEVERED', () => {
  it('renders a LEVERED badge from tape_tags', () => {
    const badges = tapeTagBadgesFor({ tape_tags: 'LEVERED', legs_json: [] } as any)
    const lev = badges.find((b) => b.key === 'LEVERED')
    expect(lev).toBeTruthy()
    expect(lev!.label).toBe('LEVERED')
    expect(lev!.className).not.toBe('bg-zinc-700/50 text-zinc-300') // not the default tone
  })
})
