// ABOUTME: Source-string contract test for VolumeGridCard.
import { describe, expect, it } from '@jest/globals'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const cardSource = readFileSync(
  resolve(
    process.cwd(),
    'src/features/usd-swaps-tape-v2/components/VolumeGrid/VolumeGridCard.tsx',
  ),
  'utf8',
)

describe('VolumeGridCard — localStorage keys', () => {
  it('uses the documented keys for collapsed/metric/period state', () => {
    expect(cardSource).toMatch(/'usd-tape-v2:volume-grid:collapsed'/)
    expect(cardSource).toMatch(/'usd-tape-v2:volume-grid:metric'/)
    expect(cardSource).toMatch(/'usd-tape-v2:volume-grid:period'/)
  })
  it('uses keys for lookback baseline and active-view state', () => {
    // Refactor: forward-schema/tenor-schema/package-type/view-mode moved into
    // per-view state managed by VolumeGridViewSwitcher; card now owns
    // lookback (baseline window) and active-view (which view tab is open).
    expect(cardSource).toMatch(/'usd-tape-v2:volume-grid:lookback'/)
    expect(cardSource).toMatch(/'usd-tape-v2:volume-grid:active-view'/)
  })
  it('delegates view rendering to VolumeGridViewSwitcher', () => {
    // Color-mode, forward-schema, tenor-schema, package-type state moved
    // into per-view components; VolumeGridCard is now a thin shell.
    expect(cardSource).toMatch(/VolumeGridViewSwitcher/)
  })
  it('uses VolumeGridCellModal for cell drilldown', () => {
    expect(cardSource).toMatch(/VolumeGridCellModal/)
  })
  it('uses a version key for default-state migrations', () => {
    expect(cardSource).toMatch(/'usd-tape-v2:volume-grid:defaults-version'/)
  })
})

describe('VolumeGridCard — toggles', () => {
  it('exposes Notional and DV01 metric options', () => {
    expect(cardSource).toMatch(/id: 'notional'[\s\S]*Notional/)
    expect(cardSource).toMatch(/id: 'dv01'[\s\S]*DV01/)
  })
  it('exposes Today/1h/24h/1w/2w/3w/1m/3m period options', () => {
    expect(cardSource).toMatch(/id: 'today'[\s\S]*Today/)
    expect(cardSource).toMatch(/id: '1h'/)
    expect(cardSource).toMatch(/id: '24h'/)
    expect(cardSource).toMatch(/id: '1w'/)
    expect(cardSource).toMatch(/id: '2w'/)
    expect(cardSource).toMatch(/id: '3w'/)
    expect(cardSource).toMatch(/id: '1m'/)
    expect(cardSource).toMatch(/id: '3m'/)
  })
  it('exposes baseline lookback options (1w–2y)', () => {
    // Color-mode moved into individual views. The card now owns a lookback
    // "baseline" toggle with 8 options spanning 1w → 2y.
    expect(cardSource).toMatch(/LOOKBACK_IDS/)
    expect(cardSource).toMatch(/'1w'/)
    expect(cardSource).toMatch(/'1m'/)
    expect(cardSource).toMatch(/'2y'/)
  })
})

describe('VolumeGridCard — defaults', () => {
  it('starts open', () => {
    // DEFAULT_COLLAPSED constant replaced by inline useState(false)
    expect(cardSource).toMatch(/useState\(false\)/)
  })
  it('defaults metric to dv01', () => {
    // DEFAULT_METRIC constant replaced by inline useState<VolumeMetric>('dv01')
    expect(cardSource).toMatch(/useState<VolumeMetric>\('dv01'\)/)
  })
  it('defaults period to today', () => {
    // Default period changed from '1w' → 'today' in the view-switcher refactor.
    // DEFAULT_PERIOD constant replaced by inline useState<VolumePeriod>('today').
    expect(cardSource).toMatch(/useState<VolumePeriod>\('today'\)/)
  })
  it('applies updated defaults before honoring persisted grid state', () => {
    // shouldApplyCurrentDefaults() helper replaced by inline shouldApplyDefaults variable
    expect(cardSource).toMatch(/shouldApplyDefaults/)
    expect(cardSource).toMatch(/useState<VolumeMetric>\('dv01'\)/)
    expect(cardSource).toMatch(/useState<VolumePeriod>\('today'\)/)
  })
  it('defaults lookback to 1m', () => {
    // Forward/tenor/package-type per-view state moved to VolumeGridViewSwitcher.
    // Card now owns lookback with a default of '1m' (≈30 days baseline).
    expect(cardSource).toMatch(/useState<LookbackId>\('1m'\)/)
  })
})

describe('VolumeGridCard — wires state into VolumeGridViewSwitcher', () => {
  it('passes metric, period, lookbackDays to VolumeGridViewSwitcher', () => {
    // useVolumeGrid() replaced by VolumeGridViewSwitcher which accepts
    // metric/period/lookbackDays as props and owns per-view state internally.
    expect(cardSource).toMatch(/metric=\{metric\}/)
    expect(cardSource).toMatch(/period=\{period\}/)
    expect(cardSource).toMatch(/lookbackDays=/)
  })
})

describe('VolumeGridCard — controls', () => {
  // Axis dropdowns (Package type, Forward schema, Tenor schema, View mode)
  // moved into VolumeGridViewSwitcher per-view; VolumeGridCard now owns
  // the shared top-bar controls: window toggle, baseline lookback, and text filter.
  it('renders the lookback (baseline) toggle with LOOKBACK_DAYS mapping', () => {
    expect(cardSource).toMatch(/LOOKBACK_DAYS/)
    expect(cardSource).toMatch(/lookbackDays=\{LOOKBACK_DAYS\[lookback\]\}/)
  })
  it('renders a TextFilterInput for tape-label filtering', () => {
    expect(cardSource).toMatch(/TextFilterInput/)
    expect(cardSource).toMatch(/textFilter/)
  })
  it('renders the window period toggle with today through 3m', () => {
    // The period toggle is shared and lives in VolumeGridCard, not individual views.
    expect(cardSource).toMatch(/id: 'today'/)
    expect(cardSource).toMatch(/id: '3m'/)
  })
  it('threads textFilter into VolumeGridViewSwitcher and VolumeGridCellModal', () => {
    expect(cardSource).toMatch(/textFilter=\{textFilter/)
  })
})

describe('VolumeGridCard — refresh + toggle aria labels', () => {
  it('renders an aria-labeled toggle button', () => {
    // Refresh button was removed in the view-switcher refactor (per-view refresh
    // is handled inside each view component). Toggle button remains on the card.
    expect(cardSource).toMatch(/aria-label="Toggle volume grid"/)
  })
})
