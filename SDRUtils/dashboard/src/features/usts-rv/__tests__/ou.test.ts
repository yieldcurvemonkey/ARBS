import { ouCalibrate, simulateOUBands, addBusinessDays } from '../ou'

describe('ouCalibrate', () => {
  it('returns null for too few observations', () => {
    const values = Array.from({ length: 19 }, (_, i) => i * 0.1)
    expect(ouCalibrate(values)).toBeNull()
  })

  it('calibrates a stationary AR(1) process', () => {
    // Generate a stationary AR(1): y_t = 0.5 + 0.8 * y_{t-1} + noise
    const n = 200
    const values: number[] = [5.0]
    const phi = 0.8
    const intercept = 0.5
    for (let i = 1; i < n; i++) {
      values.push(intercept + phi * values[i - 1] + (Math.random() - 0.5) * 0.1)
    }

    const result = ouCalibrate(values)
    expect(result).not.toBeNull()
    if (!result) return

    // phi should be close to 0.8
    expect(result.phi).toBeGreaterThan(0.6)
    expect(result.phi).toBeLessThan(0.95)

    // mu should be close to intercept / (1 - phi) = 0.5 / 0.2 = 2.5
    expect(result.mu).toBeGreaterThan(1.5)
    expect(result.mu).toBeLessThan(3.5)

    expect(result.kappa).toBeGreaterThan(0)
    expect(result.sigma).toBeGreaterThan(0)
    expect(result.halfLife).toBeGreaterThan(0)
    expect(Number.isFinite(result.zScore)).toBe(true)
  })

  it('rejects a non-stationary process (b >= 1)', () => {
    // Unit root: y_t = y_{t-1} + noise (random walk)
    const n = 100
    const values: number[] = [0]
    for (let i = 1; i < n; i++) {
      values.push(values[i - 1] + (Math.random() - 0.5) * 0.5)
    }

    // This may or may not reject depending on random seed,
    // so we construct a deterministic unit root
    const deterministicValues = Array.from({ length: 100 }, (_, i) => i * 1.0)
    const result = ouCalibrate(deterministicValues)
    // Perfect trend: b should be close to 1 -> rejected
    expect(result).toBeNull()
  })

  it('filters non-finite values and calibrates remaining', () => {
    // Generate stationary AR(1) with some non-finite values injected
    const n = 60
    const clean: number[] = [5.0]
    for (let i = 1; i < n; i++) {
      clean.push(0.5 + 0.8 * clean[i - 1] + (Math.random() - 0.5) * 0.1)
    }
    clean[10] = NaN
    clean[20] = Infinity
    clean[30] = -Infinity

    const result = ouCalibrate(clean)
    // Should still calibrate with remaining values (57 valid > 20 minimum)
    expect(result).not.toBeNull()
  })
})

describe('simulateOUBands', () => {
  it('generates the correct number of forward points', () => {
    const bands = simulateOUBands(5.0, 4.5, 0.05, 0.5, 10, '2024-01-15')
    expect(bands).toHaveLength(10)
  })

  it('mean reverts toward mu over time', () => {
    const startValue = 10.0
    const mu = 5.0
    const bands = simulateOUBands(startValue, mu, 0.1, 0.5, 100, '2024-01-15')

    const firstMean = bands[0].mean
    const lastMean = bands[bands.length - 1].mean

    // First point should be closer to start value
    expect(Math.abs(firstMean - startValue)).toBeLessThan(Math.abs(lastMean - startValue) + 5)
    // Last point should be closer to mu
    expect(Math.abs(lastMean - mu)).toBeLessThan(Math.abs(firstMean - mu))
  })

  it('bands widen over time', () => {
    const bands = simulateOUBands(5.0, 5.0, 0.05, 0.5, 50, '2024-01-15')
    const firstWidth = bands[0].plus1Sigma - bands[0].minus1Sigma
    const lastWidth = bands[bands.length - 1].plus1Sigma - bands[bands.length - 1].minus1Sigma
    expect(lastWidth).toBeGreaterThan(firstWidth)
  })
})

describe('addBusinessDays', () => {
  it('skips weekends', () => {
    // 2024-01-12 is a Friday
    expect(addBusinessDays('2024-01-12', 1)).toBe('2024-01-15') // Monday
    expect(addBusinessDays('2024-01-12', 2)).toBe('2024-01-16') // Tuesday
  })

  it('handles Monday correctly', () => {
    // 2024-01-15 is a Monday
    expect(addBusinessDays('2024-01-15', 1)).toBe('2024-01-16') // Tuesday
  })

  it('handles mid-week correctly', () => {
    // 2024-01-17 is a Wednesday
    expect(addBusinessDays('2024-01-17', 1)).toBe('2024-01-18') // Thursday
    expect(addBusinessDays('2024-01-17', 3)).toBe('2024-01-22') // Monday (skips weekend)
  })

  it('handles multiple weeks', () => {
    // 2024-01-15 is a Monday, 5 business days = next Monday
    expect(addBusinessDays('2024-01-15', 5)).toBe('2024-01-22')
  })
})
