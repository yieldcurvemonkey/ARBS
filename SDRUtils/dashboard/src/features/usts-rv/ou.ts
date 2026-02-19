/**
 * Ornstein-Uhlenbeck process calibration and simulation.
 *
 * Ported from:
 *   - RVUtils/plt_timeseries.py  _ou_calibrate()   (AR(1) OLS calibration)
 *   - RVUtils/mean_reversion.py  simulate_mean_reversion_ou()  (forward bands)
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type OUCalibrationResult = {
  /** Long-run equilibrium level */
  mu: number
  /** Mean reversion speed (kappa = -ln(phi)) */
  kappa: number
  /** OU volatility */
  sigma: number
  /** AR(1) coefficient (phi = exp(-kappa)) */
  phi: number
  /** AR(1) intercept */
  intercept: number
  /** Half-life in steps = ln(2) / kappa */
  halfLife: number
  /** Standardized distance from equilibrium: (last - mu) / steadyStateSigma */
  zScore: number
}

export type OUForecastPoint = {
  step: number
  date: string
  mean: number
  plus1Sigma: number
  minus1Sigma: number
  plus2Sigma: number
  minus2Sigma: number
}

// ---------------------------------------------------------------------------
// OU Calibration  (AR(1) OLS)
// ---------------------------------------------------------------------------

/**
 * Calibrate an Ornstein-Uhlenbeck process from an observed time series.
 *
 * Fits y[t] = a + b * y[t-1] via ordinary least squares (normal equations)
 * and derives OU parameters.
 *
 * Returns null when the series is too short (<20 obs) or non-stationary
 * (phi outside (0, 1)).
 */
export function ouCalibrate(values: number[], dt: number = 1.0): OUCalibrationResult | null {
  if (values.length < 20) return null

  // y0 = values[0..n-2],  y1 = values[1..n-1]
  const n = values.length - 1
  let sumY0 = 0
  let sumY1 = 0
  let sumY0Y0 = 0
  let sumY0Y1 = 0
  let sumY1Y1 = 0

  for (let i = 0; i < n; i++) {
    const y0 = values[i]
    const y1 = values[i + 1]
    sumY0 += y0
    sumY1 += y1
    sumY0Y0 += y0 * y0
    sumY0Y1 += y0 * y1
    sumY1Y1 += y1 * y1
  }

  // Normal equations for y1 = a + b * y0
  // [n,       sumY0   ] [a]   [sumY1  ]
  // [sumY0,   sumY0Y0 ] [b] = [sumY0Y1]
  const det = n * sumY0Y0 - sumY0 * sumY0
  if (Math.abs(det) < 1e-15) return null

  const a = (sumY1 * sumY0Y0 - sumY0 * sumY0Y1) / det
  const b = (n * sumY0Y1 - sumY0 * sumY1) / det

  // Non-stationary guard
  if (b <= 0 || b >= 1 || !Number.isFinite(b)) return null

  const mu = a / (1 - b)
  const kappa = -Math.log(b) / dt
  if (!Number.isFinite(kappa) || kappa <= 0) return null

  // Residual variance
  let sse = 0
  for (let i = 0; i < n; i++) {
    const eps = values[i + 1] - (a + b * values[i])
    sse += eps * eps
  }
  const s2Eta = sse / Math.max(1, n - 1)

  const sigmaSquared = s2Eta * (2 * kappa) / (1 - b * b)
  const sigma = Math.sqrt(Math.max(0, sigmaSquared))

  const halfLife = Math.LN2 / kappa

  // Steady-state standard deviation
  const steadyStateSigma = sigma / Math.sqrt(2 * kappa)
  const lastValue = values[values.length - 1]
  const zScore = steadyStateSigma > 1e-15
    ? (lastValue - mu) / steadyStateSigma
    : 0

  return {
    mu,
    kappa,
    sigma,
    phi: b,
    intercept: a,
    halfLife,
    zScore
  }
}

// ---------------------------------------------------------------------------
// OU Forward Simulation (deterministic bands)
// ---------------------------------------------------------------------------

/**
 * Add `n` business days (skip weekends) to an ISO date string.
 */
export function addBusinessDays(dateStr: string, n: number): string {
  const d = new Date(dateStr + 'T00:00:00')
  let added = 0
  while (added < n) {
    d.setDate(d.getDate() + 1)
    const dow = d.getDay()
    if (dow !== 0 && dow !== 6) added++
  }
  return d.toISOString().slice(0, 10)
}

/**
 * Simulate deterministic forward OU bands from a starting value.
 *
 * Expected path:  E[t+1] = E[t] * exp(-kappa) + mu * (1 - exp(-kappa))
 * Variance:       V(t) = (sigma^2 / (2*kappa)) * (1 - exp(-2*kappa*t))
 * Bands:          E +/- n * sqrt(V)
 */
export function simulateOUBands(
  startValue: number,
  mu: number,
  kappa: number,
  sigma: number,
  steps: number,
  lastDate: string
): OUForecastPoint[] {
  const result: OUForecastPoint[] = []
  const expNegKappa = Math.exp(-kappa)
  const sigma2 = sigma * sigma
  let expected = startValue

  for (let t = 0; t < steps; t++) {
    expected = expected * expNegKappa + mu * (1 - expNegKappa)
    const driftVariance = (sigma2 / (2 * kappa)) * (1 - Math.exp(-2 * kappa * (t + 1)))
    const sd = Math.sqrt(Math.max(0, driftVariance))

    result.push({
      step: t,
      date: addBusinessDays(lastDate, t + 1),
      mean: expected,
      plus1Sigma: expected + sd,
      minus1Sigma: expected - sd,
      plus2Sigma: expected + 2 * sd,
      minus2Sigma: expected - 2 * sd
    })
  }

  return result
}
