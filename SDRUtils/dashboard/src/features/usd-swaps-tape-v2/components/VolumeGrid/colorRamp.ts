// ABOUTME: Maps a 0..100 percentile to a coolwarm background colour and a
// foreground tailwind class. Low-percentile cells are blue, the midpoint is
// neutral, and high-percentile cells are red.

const STOPS: Array<{ at: number; r: number; g: number; b: number }> = [
  { at: 0, r: 59, g: 76, b: 192 },
  { at: 25, r: 141, g: 176, b: 254 },
  { at: 50, r: 221, g: 221, b: 221 },
  { at: 75, r: 244, g: 152, b: 122 },
  { at: 100, r: 180, g: 4, b: 38 },
]

function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t
}

export function colorForPercentile(p: number | null): string {
  if (p == null) return 'rgb(30, 41, 59)'
  const clamped = Math.max(0, Math.min(100, p))
  for (let i = 1; i < STOPS.length; i += 1) {
    const lo = STOPS[i - 1]
    const hi = STOPS[i]
    if (clamped <= hi.at) {
      const t = (clamped - lo.at) / (hi.at - lo.at)
      return `rgb(${lerp(lo.r, hi.r, t).toFixed(0)}, ${lerp(lo.g, hi.g, t).toFixed(0)}, ${lerp(lo.b, hi.b, t).toFixed(0)})`
    }
  }
  const last = STOPS[STOPS.length - 1]
  return `rgb(${last.r}, ${last.g}, ${last.b})`
}

export function foregroundForPercentile(p: number | null): string {
  if (p == null) return 'text-slate-500'
  return p <= 15 || p >= 90 ? 'text-slate-100' : 'text-slate-950'
}
