import { addBusinessDays, ouCalibrate, simulateOUBands } from '@/features/usts-rv/ou'

describe('usts-rv/ou', () => {
  test('rejects short samples', () => {
    const values = Array.from({ length: 10 }, (_, i) => i)
    expect(ouCalibrate(values)).toBeNull()
  })

  test('rejects non-stationary samples', () => {
    const values = Array.from({ length: 80 }, (_, i) => i * 2)
    expect(ouCalibrate(values)).toBeNull()
  })

  test('calibrates stationary AR(1)-like sample', () => {
    const values: number[] = [1.0]
    for (let i = 1; i < 320; i += 1) {
      const prev = values[i - 1]
      const eps = 0.03 * Math.sin(i * 0.77)
      values.push(0.12 + 0.95 * prev + eps)
    }

    const out = ouCalibrate(values)
    expect(out).not.toBeNull()
    expect(out!.phi).toBeGreaterThan(0)
    expect(out!.phi).toBeLessThan(1)
    expect(out!.halfLife).toBeGreaterThan(0)
    expect(Number.isFinite(out!.zScore)).toBe(true)
  })

  test('addBusinessDays skips weekends', () => {
    expect(addBusinessDays('2026-01-02', 1)).toBe('2026-01-05')
    expect(addBusinessDays('2026-01-02', 2)).toBe('2026-01-06')
  })

  test('simulateOUBands builds expected fields and ordering', () => {
    const bands = simulateOUBands(10, 8, 0.2, 1.5, 6, '2026-01-02')
    expect(bands.length).toBe(6)
    expect(bands[0].date).toBe('2026-01-05')
    expect(bands[0].plus1Sigma).toBeGreaterThan(bands[0].mean)
    expect(bands[0].minus1Sigma).toBeLessThan(bands[0].mean)
    expect(bands[0].plus2Sigma).toBeGreaterThan(bands[0].plus1Sigma)
    expect(bands[0].minus2Sigma).toBeLessThan(bands[0].minus1Sigma)
  })
})
