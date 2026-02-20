export type OuCalibration = {
  mu: number
  kappa: number
  sigma: number
  phi: number
  halfLife: number
  zScore: number
}

export type OuBandPoint = {
  date: string
  mean: number
  plus1Sigma: number
  minus1Sigma: number
  plus2Sigma: number
  minus2Sigma: number
}

function variance(values: number[]) {
  if (values.length < 2) return 0
  const mean = values.reduce((sum, v) => sum + v, 0) / values.length
  let sumSq = 0
  for (const v of values) {
    const d = v - mean
    sumSq += d * d
  }
  return sumSq / (values.length - 1)
}

function toValidSeries(values: number[]) {
  return values.filter((v) => typeof v === 'number' && Number.isFinite(v))
}

export function ouCalibrate(values: number[]): OuCalibration | null {
  const y = toValidSeries(values)
  if (y.length < 20) return null

  const x: number[] = []
  const y1: number[] = []
  for (let i = 1; i < y.length; i += 1) {
    x.push(y[i - 1])
    y1.push(y[i])
  }
  if (x.length < 5) return null

  const xMean = x.reduce((sum, v) => sum + v, 0) / x.length
  const yMean = y1.reduce((sum, v) => sum + v, 0) / y1.length

  let sxx = 0
  let sxy = 0
  for (let i = 0; i < x.length; i += 1) {
    const dx = x[i] - xMean
    sxx += dx * dx
    sxy += dx * (y1[i] - yMean)
  }
  if (!(sxx > 0)) return null

  const phi = sxy / sxx
  const intercept = yMean - phi * xMean
  if (!(phi > 0 && phi < 1) || !Number.isFinite(phi)) return null

  const mu = intercept / (1 - phi)
  const kappa = -Math.log(phi)
  if (!(kappa > 0) || !Number.isFinite(kappa)) return null

  const eps: number[] = []
  for (let i = 0; i < x.length; i += 1) {
    eps.push(y1[i] - (intercept + phi * x[i]))
  }
  const s2Eta = variance(eps)
  const sigma = Math.sqrt(Math.max(0, s2Eta * (2 * kappa) / (1 - phi * phi)))
  if (!Number.isFinite(sigma)) return null

  const halfLife = Math.log(2) / kappa
  const eqStd = sigma / Math.sqrt(2 * kappa)
  if (!(eqStd > 0) || !Number.isFinite(eqStd)) return null

  const zScore = (y[y.length - 1] - mu) / eqStd
  if (!Number.isFinite(zScore)) return null

  return {
    mu,
    kappa,
    sigma,
    phi,
    halfLife,
    zScore
  }
}

export function addBusinessDays(dateStr: string, n: number): string {
  const baseIso = String(dateStr || '').slice(0, 10)
  const base = new Date(`${baseIso}T00:00:00Z`)
  if (Number.isNaN(base.getTime())) {
    throw new Error(`Invalid date '${dateStr}'`)
  }

  const count = Math.max(0, Math.trunc(Number(n)))
  let moved = 0
  while (moved < count) {
    base.setUTCDate(base.getUTCDate() + 1)
    const day = base.getUTCDay()
    if (day !== 0 && day !== 6) moved += 1
  }
  return base.toISOString().slice(0, 10)
}

export function simulateOUBands(
  startValue: number,
  mu: number,
  kappa: number,
  sigma: number,
  steps: number,
  lastDate: string
): OuBandPoint[] {
  if (!Number.isFinite(startValue)) return []
  if (!(Number.isFinite(mu) && Number.isFinite(kappa) && Number.isFinite(sigma))) return []
  if (!(kappa > 0)) return []
  const count = Math.max(0, Math.trunc(Number(steps)))
  if (!count) return []

  const out: OuBandPoint[] = []
  const decay = Math.exp(-kappa)
  let mean = startValue

  for (let t = 1; t <= count; t += 1) {
    mean = mean * decay + mu * (1 - decay)
    const varianceAtT = (sigma * sigma / (2 * kappa)) * (1 - Math.exp(-2 * kappa * t))
    const std = Math.sqrt(Math.max(0, varianceAtT))
    out.push({
      date: addBusinessDays(lastDate, t),
      mean,
      plus1Sigma: mean + std,
      minus1Sigma: mean - std,
      plus2Sigma: mean + 2 * std,
      minus2Sigma: mean - 2 * std
    })
  }

  return out
}
