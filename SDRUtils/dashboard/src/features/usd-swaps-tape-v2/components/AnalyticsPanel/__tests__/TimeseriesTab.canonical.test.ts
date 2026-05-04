import { describe, expect, it } from '@jest/globals'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const timeseriesTabSource = readFileSync(
  resolve(
    process.cwd(),
    'src/features/usd-swaps-tape-v2/components/AnalyticsPanel/TimeseriesTab.tsx',
  ),
  'utf8',
)

const useAnalyticsTimeseriesSource = readFileSync(
  resolve(
    process.cwd(),
    'src/features/usd-swaps-tape-v2/hooks/useAnalyticsTimeseries.ts',
  ),
  'utf8',
)

const analyticsTypesSource = readFileSync(
  resolve(
    process.cwd(),
    'src/features/usd-swaps-tape-v2/components/AnalyticsPanel/analytics-types.ts',
  ),
  'utf8',
)

describe('AnalyticsPanel canonical groupBy', () => {
  it('exposes an AnalyticsGroupBy union including canonical', () => {
    expect(analyticsTypesSource).toMatch(/AnalyticsGroupBy/)
    expect(analyticsTypesSource).toMatch(/['"]canonical['"]/)
  })

  it('renders the canonical groupBy option in the dropdown', () => {
    expect(timeseriesTabSource).toContain('canonical')
    expect(timeseriesTabSource).toContain('canonicalDisplayLabel')
  })

  it('forwards the groupBy override through the timeseries hook', () => {
    expect(useAnalyticsTimeseriesSource).toMatch(/groupBy/)
    expect(useAnalyticsTimeseriesSource).toMatch(/canonical/)
  })
})
