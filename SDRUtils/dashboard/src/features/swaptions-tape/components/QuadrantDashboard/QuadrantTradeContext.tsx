// Quadrant context enrichment for individual trade / rarity panel
import { memo, useMemo } from 'react';
import type { TapeRow } from '../../types/trade.types';
import type { TradeQuadrantContext, VolGridQuadrant } from '../../types/quadrant.types';
import { QUADRANT_COLORS } from '../../quadrant/quadrant.config';
import { formatCompactNotional } from '../../quadrant/quadrant.utils';

export type QuadrantTradeContextProps = {
  context: TradeQuadrantContext;
  trade: TapeRow;
};

const DIRECTION_LABELS: Record<string, string> = {
  payer: 'net payer',
  receiver: 'net receiver',
  balanced: 'balanced',
};

export const QuadrantTradeContext = memo(function QuadrantTradeContext({
  context,
  trade,
}: QuadrantTradeContextProps) {
  const { classification, quadrantMeta, quadrantFlow, reinforcesDirection, shareOfQuadrant, simultaneousActivity, crossQuadrantPattern } = context;
  const colors = QUADRANT_COLORS[classification.quadrant];

  const paceLabel = quadrantFlow.paceVsBaseline > 1.3
    ? 'most active'
    : quadrantFlow.paceVsBaseline > 0.8
    ? 'normally active'
    : 'quiet';

  return (
    <div className="rounded-lg border border-slate-800 bg-slate-950/50 p-3 space-y-3 text-[11px]">
      {/* Quadrant identification */}
      <div className="flex items-center gap-2">
        <span className={`${colors.bg} ${colors.border} border rounded px-2 py-0.5 font-semibold ${colors.text}`}>
          {classification.quadrant}
        </span>
        <span className="text-slate-300 font-medium">{quadrantMeta.fullName}</span>
        {classification.quadrant === 'BOUNDARY' && classification.adjacentQuadrants && (
          <span className="text-slate-500 text-[10px]">
            (straddles {classification.adjacentQuadrants.join(', ')})
          </span>
        )}
      </div>

      {/* Quadrant description */}
      <div className="text-slate-500 text-[10px]">{quadrantMeta.description}</div>

      {/* Today's quadrant flow summary */}
      <div className="border border-slate-800 rounded p-2 space-y-1.5">
        <div className="text-slate-400 font-medium text-[10px] uppercase tracking-wide">
          Quadrant Flow Today
        </div>
        <div className="grid grid-cols-2 gap-x-4 gap-y-1">
          <div className="flex justify-between">
            <span className="text-slate-500">Trades:</span>
            <span className="text-slate-300">{quadrantFlow.tradeCount}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-slate-500">Gross:</span>
            <span className="text-slate-300">{formatCompactNotional(quadrantFlow.grossNotional)}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-slate-500">Net:</span>
            <span className={quadrantFlow.dominantDirection === 'payer' ? 'text-red-400' : quadrantFlow.dominantDirection === 'receiver' ? 'text-green-400' : 'text-slate-400'}>
              {formatCompactNotional(quadrantFlow.netNotional)} {DIRECTION_LABELS[quadrantFlow.dominantDirection]}
            </span>
          </div>
          <div className="flex justify-between">
            <span className="text-slate-500">Pace:</span>
            <span className="text-slate-300">{quadrantFlow.paceVsBaseline.toFixed(1)}x ({paceLabel})</span>
          </div>
        </div>
      </div>

      {/* This trade's context within the quadrant */}
      <div className="space-y-1">
        <div className="text-slate-400">
          This trade is <span className="text-slate-300">{(shareOfQuadrant * 100).toFixed(1)}%</span> of {classification.quadrant} gross today.
          {reinforcesDirection
            ? <span className="text-emerald-400"> Reinforces the {DIRECTION_LABELS[quadrantFlow.dominantDirection]} lean.</span>
            : <span className="text-amber-400"> Counters the quadrant direction.</span>
          }
        </div>
      </div>

      {/* Simultaneous activity in other quadrants */}
      {simultaneousActivity.length > 0 && (
        <div className="border border-slate-800 rounded p-2 space-y-1">
          <div className="text-slate-400 font-medium text-[10px] uppercase tracking-wide">
            Simultaneous Activity (\u00B130 min)
          </div>
          {simultaneousActivity.map((a) => {
            const qColors = QUADRANT_COLORS[a.quadrant];
            return (
              <div key={a.quadrant} className="flex items-center gap-2">
                <span className={`${qColors.text} font-medium`}>{a.quadrant}:</span>
                <span className="text-slate-400">
                  {a.tradeCount} trade{a.tradeCount !== 1 ? 's' : ''},{' '}
                  {formatCompactNotional(a.netNotional)} {a.direction}
                </span>
              </div>
            );
          })}
        </div>
      )}

      {/* Cross-quadrant pattern */}
      {crossQuadrantPattern && (
        <div className="border border-amber-900/40 bg-amber-950/20 rounded p-2">
          <div className="text-amber-400/80 font-medium text-[10px] uppercase tracking-wide mb-1">
            Cross-Quadrant Pattern
          </div>
          <div className="text-slate-300 text-[10px]">{crossQuadrantPattern.label}</div>
          <div className="text-slate-500 text-[10px] mt-0.5">{crossQuadrantPattern.description}</div>
        </div>
      )}

      {/* Typical participants & desk view */}
      <div className="grid grid-cols-2 gap-3">
        <div>
          <div className="text-slate-500 font-medium text-[10px] uppercase tracking-wide mb-1">
            Typical Participants
          </div>
          <div className="space-y-0.5">
            {quadrantMeta.typicalParticipants.map((p, i) => (
              <div key={i} className="text-slate-400 text-[10px]">\u2022 {p}</div>
            ))}
          </div>
        </div>
        <div>
          <div className="text-slate-500 font-medium text-[10px] uppercase tracking-wide mb-1">
            Supply/Demand
          </div>
          <div className="text-slate-400 text-[10px]">{quadrantMeta.supplyDemandDrivers}</div>
          <div className="mt-1.5">
            <div className="text-slate-500 font-medium text-[10px] uppercase tracking-wide mb-0.5">
              Desk View
            </div>
            <div className="text-slate-300 text-[10px] font-medium">{quadrantMeta.deskView}</div>
          </div>
        </div>
      </div>
    </div>
  );
});
