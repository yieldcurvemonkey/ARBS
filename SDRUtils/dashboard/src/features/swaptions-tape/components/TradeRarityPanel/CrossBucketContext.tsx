import type { TapeRow } from '../../types/trade.types';
import type { TradeQuadrantContext } from '../../types/quadrant.types';
import { QuadrantTradeContext } from '../QuadrantDashboard/QuadrantTradeContext';

export type CrossBucketContextProps = {
  context?: TradeQuadrantContext | null;
  trade?: TapeRow | null;
};

export function CrossBucketContext({ context, trade }: CrossBucketContextProps) {
  if (!context || !trade) {
    return (
      <div className="rounded-lg border border-slate-800 bg-slate-950/50 p-3 text-[11px] text-slate-400">
        Select a trade with valid expiry/tenor to see quadrant context.
      </div>
    );
  }

  return <QuadrantTradeContext context={context} trade={trade} />;
}
