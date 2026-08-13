// ABOUTME: The panel's guard and its diverging ramp, pinned by known answer.
import { describe, expect, it } from '@jest/globals'
import {
  assertNotCrossBucketLevel,
  CrossBucketLevelComparison,
  fmtSignedDv01,
  fmtZ,
  heatmapState,
  panelState,
  indexByBucketDate,
  latestDate,
  levelKey,
  recentDates,
  slug,
  TENOR_BUCKETS,
  Z_CLAMP,
  zColor,
  zInk,
} from '../DealerLadderPanel.helpers'

describe('the panel cannot draw a cross-bucket level', () => {
  it('lets a single bucket carry its level', () => {
    expect(() =>
      assertNotCrossBucketLevel([
        { bucket_key: '5-7Y', delta_dv01__5_7Y: 1 },
        { bucket_key: '5-7Y', delta_dv01__5_7Y: 2 },
      ]),
    ).not.toThrow()
  })

  it('lets many buckets carry z', () => {
    expect(() =>
      assertNotCrossBucketLevel([
        { bucket_key: '5-7Y', z_raw: 1 },
        { bucket_key: '7-10Y', z_raw: -2 },
      ]),
    ).not.toThrow()
  })

  it('throws on many buckets carrying a level, suffixed or not', () => {
    for (const key of ['delta_dv01', 'delta_dv01__5_7Y', 'abs_dv01', 'delta_dv01_cov_adj']) {
      expect(() =>
        assertNotCrossBucketLevel([
          { bucket_key: '5-7Y', [key]: 1 },
          { bucket_key: '7-10Y', [key]: 2 },
        ]),
      ).toThrow(CrossBucketLevelComparison)
    }
  })

  it('names the measurement in the message, not just the rule', () => {
    try {
      assertNotCrossBucketLevel([
        { bucket_key: '0-1Y', delta_dv01: 1 },
        { bucket_key: '15-20Y', delta_dv01: 2 },
      ])
      throw new Error('should have thrown')
    } catch (e) {
      expect(String(e)).toContain('0.761')
      expect(String(e)).toContain('0.495')
      expect(String(e)).toContain('1.54')
    }
  })
})

describe('the bucket order is canonical, never sorted by value', () => {
  it('is the indicator order', () => {
    expect([...TENOR_BUCKETS]).toEqual([
      '0-1Y', '1-2Y', '2-3Y', '3-5Y', '5-7Y',
      '7-10Y', '10-15Y', '15-20Y', '20-30Y', '30Y+',
    ])
  })
})

describe('the level key matches the Python name exactly', () => {
  it('slugs the same way', () => {
    expect(slug('5-7Y')).toBe('5_7Y')
    expect(slug('30Y+')).toBe('30Yplus')
  })
  it('builds the same column names', () => {
    expect(levelKey('5-7Y')).toBe('delta_dv01__5_7Y')
    expect(levelKey('30Y+', 'cov_adj')).toBe('delta_dv01_cov_adj__30Yplus')
    expect(levelKey('20-30Y', 'gross')).toBe('abs_dv01__20_30Y')
  })
})

describe('the diverging ramp', () => {
  it('is NEUTRAL GREY at zero — never a hue at the midpoint', () => {
    expect(zColor(0)).toBe('rgb(51, 65, 85)') // slate-700, no hue
  })

  it('goes to sky for a positive z and amber for a negative one', () => {
    // +z = dealer received = long duration.
    expect(zColor(Z_CLAMP)).toBe('rgb(56, 189, 248)')
    expect(zColor(-Z_CLAMP)).toBe('rgb(245, 158, 11)')
  })

  it('clamps rather than continuing to darken', () => {
    expect(zColor(10)).toBe(zColor(Z_CLAMP))
    expect(zColor(-10)).toBe(zColor(-Z_CLAMP))
  })

  it('is monotone in |z| on each side', () => {
    const mid = zColor(1.5)
    expect(mid).not.toBe(zColor(0))
    expect(mid).not.toBe(zColor(Z_CLAMP))
  })

  it('renders nothing for a missing cell rather than a zero', () => {
    // A day with no data is not a day with z = 0.
    expect(zColor(null)).toBe('transparent')
  })

  it('flips the ink so a saturated cell stays legible', () => {
    expect(zInk(0)).toBe('#cbd5e1')
    expect(zInk(3)).toBe('#0f172a')
    expect(zInk(-3)).toBe('#0f172a')
  })
})

describe('formatting keeps the sign', () => {
  it('never drops it — the sign is the whole content', () => {
    expect(fmtSignedDv01(1_500_000)).toBe('+1.50MM')
    expect(fmtSignedDv01(-1_500_000)).toBe('−1.50MM')
    expect(fmtSignedDv01(2_400)).toBe('+2K')
    expect(fmtSignedDv01(-2_400)).toBe('−2K')
    expect(fmtSignedDv01(0)).toBe('0')
    expect(fmtSignedDv01(null)).toBe('—')
  })
  it('signs z too', () => {
    expect(fmtZ(1.24)).toBe('+1.2')
    expect(fmtZ(-1.24)).toBe('-1.2')
    expect(fmtZ(null)).toBe('—')
  })
})

describe('heatmap indexing', () => {
  const rows = [
    { bucket_key: '5-7Y', visibility_date: '2026-04-01', z_raw: 1 },
    { bucket_key: '5-7Y', visibility_date: '2026-04-02', z_raw: 2 },
    { bucket_key: '7-10Y', visibility_date: '2026-04-02', z_raw: -1 },
  ] as never[]

  it('finds the latest date', () => {
    expect(latestDate(rows)).toBe('2026-04-02')
    expect(latestDate([])).toBeNull()
  })

  it('takes the last n distinct dates, oldest first', () => {
    expect(recentDates(rows, 1)).toEqual(['2026-04-02'])
    expect(recentDates(rows, 5)).toEqual(['2026-04-01', '2026-04-02'])
  })

  it('keys on (bucket, date)', () => {
    const m = indexByBucketDate(rows)
    expect(m.get('5-7Y|2026-04-01')).toBeDefined()
    expect(m.get('7-10Y|2026-04-01')).toBeUndefined()
    expect(m.size).toBe(3)
  })
})


describe('an empty heatmap says WHY it is empty', () => {
  // OBSERVED, and the reason this exists: /standardised returns 6,290 rows and
  // a screenshot taken 2.5s after the Analytics tab opens caught the panel
  // mid-flight. It drew ten labelled bucket rows with empty strips and an
  // em-dash where z goes -- pixel-for-pixel what "nothing could be oriented
  // here" looks like. On a panel whose governing rule is that an abstention is
  // information rather than a blank, an in-flight fetch rendering as an empty
  // ladder is the same defect wearing a different hat.
  it('is ready as soon as there is one column, loading or not', () => {
    expect(heatmapState(true, ['2026-08-07'])).toBe('ready')
    expect(heatmapState(false, ['2026-08-07'])).toBe('ready')
  })

  it('separates in-flight from genuinely empty', () => {
    // These need DIFFERENT sentences. A bare `loading` boolean cannot tell
    // them apart, and neither can an empty array.
    expect(heatmapState(true, [])).toBe('loading')
    expect(heatmapState(false, [])).toBe('empty')
  })

  it('never returns ready with nothing to draw', () => {
    for (const loading of [true, false]) {
      expect(heatmapState(loading, [])).not.toBe('ready')
    }
  })
})

describe('panelState is the one rule, because three panels hit it', () => {
  // The heatmap, the exclusion drawer and the prints chart each rendered an
  // unlabelled blank while a fetch was in flight. Every one of them was found
  // by LOOKING at a screenshot -- none by a test, because all three render
  // perfectly. One function so a fix to one is a fix to all.
  it('is ready on any non-empty result', () => {
    expect(panelState(true, 1)).toBe('ready')
    expect(panelState(false, 6290)).toBe('ready')
  })

  it('separates in-flight from genuinely empty at zero', () => {
    expect(panelState(true, 0)).toBe('loading')
    expect(panelState(false, 0)).toBe('empty')
  })

  it('agrees with heatmapState, which delegates to it', () => {
    expect(heatmapState(true, [])).toBe(panelState(true, 0))
    expect(heatmapState(false, [])).toBe(panelState(false, 0))
    expect(heatmapState(false, ['2026-08-07'])).toBe(panelState(false, 1))
  })
})
