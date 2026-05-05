// ABOUTME: Maps a 0..100 percentile to an hsl() background colour and a
// foreground tailwind class. Single hue ramp from slate -> indigo ->
// fuchsia -> rose so high-percentile cells visually dominate.

const STOPS: Array<{ at: number; hue: number; sat: number; light: number }> = [
  { at: 0,   hue: 210, sat: 25, light: 14 },
  { at: 30,  hue: 210, sat: 18, light: 22 },
  { at: 60,  hue: 222, sat: 30, light: 32 },
  { at: 70,  hue: 240, sat: 65, light: 50 },
  { at: 85,  hue: 290, sat: 75, light: 52 },
  { at: 95,  hue: 320, sat: 80, light: 58 },
  { at: 100, hue: 350, sat: 82, light: 60 },
]

function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t
}

export function colorForPercentile(p: number | null): string {
  if (p == null) return 'hsl(220, 14%, 18%)'
  const clamped = Math.max(0, Math.min(100, p))
  for (let i = 1; i < STOPS.length; i += 1) {
    const lo = STOPS[i - 1]
    const hi = STOPS[i]
    if (clamped <= hi.at) {
      const t = (clamped - lo.at) / (hi.at - lo.at)
      return `hsl(${lerp(lo.hue, hi.hue, t).toFixed(0)}, ${lerp(lo.sat, hi.sat, t).toFixed(0)}%, ${lerp(lo.light, hi.light, t).toFixed(0)}%)`
    }
  }
  const last = STOPS[STOPS.length - 1]
  return `hsl(${last.hue}, ${last.sat}%, ${last.light}%)`
}

export function foregroundForPercentile(p: number | null): string {
  if (p == null) return 'text-slate-500'
  return p >= 70 ? 'text-slate-100' : 'text-slate-300'
}
