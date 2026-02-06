// 2x2 Quadrant Flow Dashboard — "30-second state of the market" view
import { memo, useMemo } from 'react';
import type { GridFlowState, QuadrantFlowSnapshot, VolGridQuadrant, QuadrantAnomaly } from '../../types/quadrant.types';
import { QUADRANT_COLORS, REGIME_COLORS } from '../../quadrant/quadrant.config';
import { formatCompactNotional, formatPremium, formatPace, quadrantNarrative } from '../../quadrant/quadrant.utils';

export type QuadrantFlowDashboardProps = {
  gridState: GridFlowState;
  anomalies: QuadrantAnomaly[];
  /** Date label for the header */
  dateLabel?: string;
  /** Callback when a quadrant cell is clicked */
  onQuadrantClick?: (quadrant: VolGridQuadrant) => void;
};

/** Activity bar: shows intensity relative to typical */
function ActivityBar({ pace, accent }: { pace: number; accent: string }) {
  const filledBars = Math.min(Math.round(pace * 5), 10);
  const totalBars = 10;
  return (
    <div className="flex gap-[2px] mt-1">
      {Array.from({ length: totalBars }, (_, i) => (
        <div
          key={i}
          className="h-[6px] w-[8px] rounded-[1px]"
          style={{
            backgroundColor: i < filledBars ? accent : 'rgba(255,255,255,0.08)',
          }}
        />
      ))}
    </div>
  );
}

/** Individual quadrant cell in the 2x2 grid */
const QuadrantCell = memo(function QuadrantCell({
  snapshot,
  label,
  anomalies,
  onClick,
}: {
  snapshot: QuadrantFlowSnapshot;
  label: string;
  anomalies: QuadrantAnomaly[];
  onClick?: () => void;
}) {
  const colors = QUADRANT_COLORS[snapshot.quadrant];
  const narrative = quadrantNarrative(snapshot);

  const netLabel = snapshot.netNotional >= 0 ? 'payer' : 'receiver';
  const paceArrow = snapshot.paceVsBaseline > 1.3 ? ' \u25B2' : snapshot.paceVsBaseline < 0.7 ? ' \u25BC' : '';

  return (
    <div
      className={`${colors.bg} ${colors.border} border rounded-md p-3 cursor-pointer hover:brightness-110 transition-all min-h-[140px] flex flex-col`}
      onClick={onClick}
      role="button"
      tabIndex={0}
    >
      {/* Header */}
      <div className="flex items-baseline justify-between mb-2">
        <span className={`${colors.text} font-semibold text-sm`}>{label}</span>
        <span className="text-slate-400 text-[11px]">
          {snapshot.tradeCount} trade{snapshot.tradeCount !== 1 ? 's' : ''}
        </span>
      </div>

      {/* Metrics */}
      <div className="space-y-1 text-[11px] flex-1">
        <div className="flex justify-between">
          <span className="text-slate-500">Gross:</span>
          <span className="text-slate-300">{formatCompactNotional(snapshot.grossNotional)}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-slate-500">Net:</span>
          <span className={snapshot.dominantDirection === 'payer' ? 'text-red-400' : snapshot.dominantDirection === 'receiver' ? 'text-green-400' : 'text-slate-400'}>
            {formatCompactNotional(snapshot.netNotional)} {netLabel}
          </span>
        </div>
        <div className="flex justify-between">
          <span className="text-slate-500">Premium:</span>
          <span className="text-slate-300">{formatPremium(snapshot.totalPremium)}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-slate-500">Pace:</span>
          <span className={`${snapshot.paceVsBaseline > 1.3 ? 'text-amber-400' : snapshot.paceVsBaseline < 0.7 ? 'text-blue-400' : 'text-slate-400'}`}>
            {formatPace(snapshot.paceVsBaseline)} normal{paceArrow}
          </span>
        </div>
      </div>

      {/* Activity bar */}
      <ActivityBar pace={snapshot.paceVsBaseline} accent={colors.accent} />

      {/* Narrative */}
      <div className="mt-1.5 text-[10px] text-slate-500 italic truncate">
        {narrative}
      </div>

      {/* Anomaly badges */}
      {anomalies.length > 0 && (
        <div className="mt-1.5 flex flex-wrap gap-1">
          {anomalies.slice(0, 2).map((a, i) => (
            <span
              key={i}
              className={`text-[9px] px-1.5 py-0.5 rounded ${
                a.severity === 'extreme'
                  ? 'bg-red-900/50 text-red-300'
                  : 'bg-amber-900/40 text-amber-300'
              }`}
            >
              {a.type === 'volume' ? '\u26A0 Volume' : a.type === 'direction' ? '\u2194 Direction' : a.type === 'premium' ? '\u0024 Premium' : '\u2716 Cross'}
            </span>
          ))}
        </div>
      )}
    </div>
  );
});

/** Full 2x2 Quadrant Flow Dashboard */
export const QuadrantFlowDashboard = memo(function QuadrantFlowDashboard({
  gridState,
  anomalies,
  dateLabel,
  onQuadrantClick,
}: QuadrantFlowDashboardProps) {
  const anomalyMap = useMemo(() => {
    const map: Record<VolGridQuadrant, QuadrantAnomaly[]> = {
      ULC: [], URC: [], LLC: [], LRC: [], BOUNDARY: [],
    };
    for (const a of anomalies) {
      map[a.quadrant].push(a);
    }
    return map;
  }, [anomalies]);

  const regimeColor = gridState.detectedRegime
    ? REGIME_COLORS[gridState.detectedRegime.id] || 'text-slate-400'
    : 'text-slate-500';

  return (
    <div className="rounded-lg border border-slate-800 bg-slate-950/60 p-4">
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-slate-200">VOL GRID FLOW</span>
          {dateLabel && (
            <span className="text-[11px] text-slate-500">{dateLabel}</span>
          )}
        </div>
        {gridState.detectedRegime && (
          <span className={`text-[11px] font-medium ${regimeColor}`}>
            {gridState.detectedRegime.label} ({Math.round(gridState.regimeConfidence * 100)}%)
          </span>
        )}
      </div>

      {/* Axis labels + Grid */}
      <div className="grid grid-cols-[auto_1fr_1fr] grid-rows-[auto_auto_auto_auto_auto] gap-0">
        {/* Column headers */}
        <div />
        <div className="text-center text-[10px] text-slate-500 font-medium pb-1">
          SHORT TENOR (2Y-5Y)
        </div>
        <div className="text-center text-[10px] text-slate-500 font-medium pb-1">
          LONG TENOR (10Y-30Y)
        </div>

        {/* Row 1: Short Expiry */}
        <div className="flex items-center pr-2">
          <div className="text-[10px] text-slate-500 font-medium leading-tight text-right">
            <div>SHORT</div>
            <div>EXPIRY</div>
            <div className="text-slate-600">(\u22641Y)</div>
            <div className="text-[9px] text-slate-600 mt-0.5">&ldquo;Gamma&rdquo;</div>
          </div>
        </div>
        <div className="p-1">
          <QuadrantCell
            snapshot={gridState.ulc}
            label="ULC"
            anomalies={anomalyMap.ULC}
            onClick={() => onQuadrantClick?.('ULC')}
          />
        </div>
        <div className="p-1">
          <QuadrantCell
            snapshot={gridState.urc}
            label="URC"
            anomalies={anomalyMap.URC}
            onClick={() => onQuadrantClick?.('URC')}
          />
        </div>

        {/* Row 2: Long Expiry */}
        <div className="flex items-center pr-2">
          <div className="text-[10px] text-slate-500 font-medium leading-tight text-right">
            <div>LONG</div>
            <div>EXPIRY</div>
            <div className="text-slate-600">(&gt;1Y)</div>
            <div className="text-[9px] text-slate-600 mt-0.5">&ldquo;Vega&rdquo;</div>
          </div>
        </div>
        <div className="p-1">
          <QuadrantCell
            snapshot={gridState.llc}
            label="LLC"
            anomalies={anomalyMap.LLC}
            onClick={() => onQuadrantClick?.('LLC')}
          />
        </div>
        <div className="p-1">
          <QuadrantCell
            snapshot={gridState.lrc}
            label="LRC"
            anomalies={anomalyMap.LRC}
            onClick={() => onQuadrantClick?.('LRC')}
          />
        </div>
      </div>

      {/* Dominant theme */}
      <div className="mt-3 text-[11px] text-slate-400 border-t border-slate-800 pt-2">
        <span className="text-slate-500 font-medium">Theme: </span>
        {gridState.dominantTheme}
      </div>

      {/* Cross-quadrant signals */}
      {gridState.crossQuadrantSignals.length > 0 && (
        <div className="mt-1.5 space-y-1">
          {gridState.crossQuadrantSignals.map((signal) => (
            <div key={signal.signalId} className="text-[10px] text-slate-500">
              <span className="text-amber-400/80 font-medium">Cross: </span>
              {signal.label} — {signal.description.slice(0, 120)}
              {signal.description.length > 120 ? '...' : ''}
            </div>
          ))}
        </div>
      )}

      {/* Anomaly alerts */}
      {anomalies.length > 0 && (
        <div className="mt-2 space-y-1 border-t border-slate-800 pt-2">
          {anomalies.slice(0, 4).map((anomaly, i) => (
            <div
              key={i}
              className={`text-[10px] ${
                anomaly.severity === 'extreme' ? 'text-red-400' : 'text-amber-400/80'
              }`}
            >
              {anomaly.severity === 'extreme' ? '\u26A0\uFE0F ' : '\u2022 '}
              {anomaly.message}
            </div>
          ))}
        </div>
      )}

      {/* Boundary trades count */}
      {gridState.boundary.tradeCount > 0 && (
        <div className="mt-1.5 text-[10px] text-slate-600">
          {gridState.boundary.tradeCount} boundary trade{gridState.boundary.tradeCount !== 1 ? 's' : ''} (near quadrant edges)
        </div>
      )}
    </div>
  );
});
