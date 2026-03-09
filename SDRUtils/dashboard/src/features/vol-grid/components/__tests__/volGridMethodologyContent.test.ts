import {
  VOL_GRID_METHODOLOGY_SECTIONS,
  VOL_GRID_METHODOLOGY_TITLE
} from '../volGridMethodologyContent'

describe('VOL_GRID_METHODOLOGY_SECTIONS', () => {
  it('documents the implemented quant stack and transparency caveats', () => {
    expect(VOL_GRID_METHODOLOGY_TITLE).toBe('Live ATMF Vol Grid Methodology')
    expect(VOL_GRID_METHODOLOGY_SECTIONS).toHaveLength(10)

    const ids = VOL_GRID_METHODOLOGY_SECTIONS.map((section) => section.id)
    expect(ids).toEqual([
      'overview',
      'surface-grid',
      'observations',
      'mapping',
      'pca',
      'bayesian-update',
      'anchors',
      'premiums',
      'sessions',
      'repro'
    ])
  })

  it('captures the key implementation details needed for reproduction', () => {
    const combinedMarkdown = VOL_GRID_METHODOLOGY_SECTIONS
      .map((section) => section.markdown)
      .join('\n')

    expect(combinedMarkdown).toContain('conditional_mvn_update')
    expect(combinedMarkdown).toContain('DIRECT_OBSERVATION_ANCHOR_MIN_WEIGHT')
    expect(combinedMarkdown).toContain('const _ = params.config')
    expect(combinedMarkdown).toContain('arbs_live_atmf_grid_snapshots_v1')
    expect(combinedMarkdown).toContain('1.45')
    expect(combinedMarkdown).toContain('2.95')
  })
})
