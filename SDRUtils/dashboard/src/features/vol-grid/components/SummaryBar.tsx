import type { VolGridCell, VolGridSessionMeta } from '../types'

type SummaryBarProps = {
  cells: VolGridCell[]
  lastUpdate: number | null
  session: VolGridSessionMeta | null
  hasData?: boolean
  comparisonActive?: boolean
  comparisonLabel?: string | null
}

function formatTime(value: number | null) {
  if (!value) return '--'
  return new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/New_York',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit'
  }).format(new Date(value))
}

function formatChange(value: number | null) {
  if (value === null || !Number.isFinite(value)) return '--'
  const sign = value > 0 ? '+' : value < 0 ? '-' : ''
  return `${sign}${Math.abs(value).toFixed(1)}`
}

export function SummaryBar({
  cells,
  lastUpdate,
  session,
  hasData = true,
  comparisonActive = false,
  comparisonLabel
}: SummaryBarProps) {
  const isClosingView = session?.isClosingView ?? false
  const observationCount = cells.reduce(
    (sum, cell) =>
      sum +
      (cell.atmfVolSource === 'direct_observation'
        ? Math.max(cell.observationCount, 0)
        : 0),
    0
  )
  const freshestMinutes = cells
    .map((cell) => cell.staleness)
    .filter((value): value is number => value !== null && Number.isFinite(value))
    .sort((left, right) => left - right)[0]
  const topMovers = cells
    .filter((cell) => {
      const value = comparisonActive ? cell.comparisonDiff : cell.atmfVolChange
      return value !== null && Number.isFinite(value)
    })
    .sort(
      (left, right) =>
        Math.abs(
          (comparisonActive ? right.comparisonDiff : right.atmfVolChange) ?? 0
        ) -
        Math.abs(
          (comparisonActive ? left.comparisonDiff : left.atmfVolChange) ?? 0
        )
    )
    .slice(0, 3)
  const regimeCounts = cells.reduce(
    (acc, cell) => {
      if (cell.regimeLabel === 'trending') acc.trending += 1
      else if (cell.regimeLabel === 'breakout') acc.breakout += 1
      else if (cell.regimeLabel === 'range-bound') acc.rangeBound += 1
      return acc
    },
    { trending: 0, breakout: 0, rangeBound: 0 }
  )

  return (
    <div className="mt-4 grid gap-3 rounded-2xl border border-slate-800 bg-slate-900/70 p-4 text-xs text-slate-300 lg:grid-cols-[1.2fr_1.8fr_1.2fr]">
      <div>
        <div className="font-semibold text-slate-100">Coverage</div>
        <div className="mt-1 text-slate-400">
          {hasData
            ? `${observationCount} direct observations, freshest mapped print ${
                freshestMinutes === undefined ? '--' : `${Math.round(freshestMinutes)}m`
              } ago.`
            : 'No stored live snapshots or EOD closes are available yet.'}
        </div>
        <div className="mt-1 text-slate-500">
          {hasData ? session?.label ?? 'Session unavailable' : 'Waiting for first stored surface'} at {formatTime(lastUpdate)} ET
        </div>
      </div>
      <div>
        <div className="font-semibold text-slate-100">
          {comparisonActive ? comparisonLabel ?? 'Close Basis' : 'Top Movers'}
        </div>
        <div className="mt-1 flex flex-wrap gap-2">
          {topMovers.length === 0 && (
            <span className="text-slate-500">
              {!hasData
                ? 'No stored movers available yet.'
                : comparisonActive
                ? 'No close basis available.'
                : isClosingView
                  ? 'No closing movers available.'
                  : 'No live movers yet.'}
            </span>
          )}
          {topMovers.map((cell) => (
            <span
              key={cell.nodeKey}
              className="rounded-full border border-slate-700 px-3 py-1"
            >
              {cell.expiry}x{cell.tenor}{' '}
              {formatChange(comparisonActive ? cell.comparisonDiff : cell.atmfVolChange)}
            </span>
          ))}
        </div>
      </div>
      <div>
        <div className="font-semibold text-slate-100">Signals</div>
        <div className="mt-1 text-slate-400">
          {hasData
            ? `${regimeCounts.trending} trending, ${regimeCounts.breakout} breakout, ${regimeCounts.rangeBound} range-bound.`
            : 'Signals will populate after the first stored surface is available.'}
        </div>
      </div>
    </div>
  )
}
