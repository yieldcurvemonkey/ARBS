/**
 * Ornstein-Uhlenbeck calibration and simulation for mean-reversion analytics.
 *
 * AR(1) OLS: y_t = a + b * y_{t-1}
 * Stationarity: 0 < b < 1, minimum 20 observations.
 */

export type OUCalibration = {
  mu: number
  kappa: number
  sigma: number
  phi: number
  halfLife: number
  zScore: number
}

export type OUBandPoint = {
  date: string
  mean: number
  plus1Sigma: number
  minus1Sigma: number
  plus2Sigma: number
  minus2Sigma: number
}

const MIN_OBSERVATIONS = 20

export function ouCalibrate(values: number[]): OUCalibration | null {
  const clean = values.filter((v) => Number.isFinite(v))
  if (clean.length < MIN_OBSERVATIONS) return null

  // AR(1) OLS: y_t = a + b * y_{t-1}
  const n = clean.length - 1
  const yLag = clean.slice(0, n)
  const yLead = clean.slice(1, n + 1)

  // Compute means
  let sumLag = 0
  let sumLead = 0
  for (let i = 0; i < n; i++) {
    sumLag += yLag[i]
    sumLead += yLead[i]
  }
  const meanLag = sumLag / n
  const meanLead = sumLead / n

  // OLS regression
  let ssXX = 0
  let ssXY = 0
  for (let i = 0; i < n; i++) {
    const dx = yLag[i] - meanLag
    const dy = yLead[i] - meanLead
    ssXX += dx * dx
    ssXY += dx * dy
  }

  if (ssXX < 1e-15) return null

  const b = ssXY / ssXX
  const a = meanLead - b * meanLag

  // Stationarity gate
  if (b <= 0 || b >= 1) return null

  // Compute residual variance
  let ssResid = 0
  for (let i = 0; i < n; i++) {
    const eps = yLead[i] - (a + b * yLag[i])
    ssResid += eps * eps
  }
  const varEps = ssResid / Math.max(1, n - 2)

  // OU parameters
  const mu = a / (1 - b)
  const kappa = -Math.log(b)
  const sigmaSquared = varEps * 2 * kappa / (1 - b * b)
  if (sigmaSquared <= 0) return null
  const sigma = Math.sqrt(sigmaSquared)

  const halfLife = Math.LN2 / kappa
  const stationaryStd = sigma / Math.sqrt(2 * kappa)
  const zScore = stationaryStd > 1e-15 ? (clean[clean.length - 1] - mu) / stationaryStd : 0

  return {
    mu,
    kappa,
    sigma,
    phi: b,
    halfLife,
    zScore
  }
}

export function simulateOUBands(
  startValue: number,
  mu: number,
  kappa: number,
  sigma: number,
  steps: number,
  lastDate: string
): OUBandPoint[] {
  const points: OUBandPoint[] = []
  let currentDate = lastDate

  for (let t = 1; t <= steps; t++) {
    currentDate = addBusinessDays(currentDate, 1)
    const decay = Math.exp(-kappa * t)
    const mean = startValue * decay + mu * (1 - decay)
    const variance = (sigma * sigma / (2 * kappa)) * (1 - Math.exp(-2 * kappa * t))
    const std = Math.sqrt(Math.max(0, variance))

    points.push({
      date: currentDate,
      mean,
      plus1Sigma: mean + std,
      minus1Sigma: mean - std,
      plus2Sigma: mean + 2 * std,
      minus2Sigma: mean - 2 * std
    })
  }

  return points
}

export function addBusinessDays(dateStr: string, n: number): string {
  const d = new Date(dateStr + 'T12:00:00Z')
  let added = 0
  while (added < n) {
    d.setUTCDate(d.getUTCDate() + 1)
    const dow = d.getUTCDay()
    if (dow !== 0 && dow !== 6) {
      added++
    }
  }
  return d.toISOString().slice(0, 10)
}
